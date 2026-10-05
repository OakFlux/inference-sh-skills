from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-10-05"
COMPANY = "宁波美诺华药业股份有限公司"
SHORT_NAME = "美诺华"
STOCK_CODE = "603538"
PACKAGE = "美诺华_603538_2020-2025年报_最新季报"
ROOT = Path(PACKAGE)
ANNUAL_DIR = ROOT / "01_年度报告"
QUARTER_DIR = ROOT / "02_最新季度报告"
VERIFY_DIR = ROOT / "03_说明与校验"
WORK_DIR = Path("_meinuohua_603538_filings_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (ANNUAL_DIR, QUARTER_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
    "Accept": "application/json,text/html,application/pdf,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://data.eastmoney.com/",
}


def request(url: str, *, stream: bool = False, timeout: tuple[int, int] = (25, 420)) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        try:
            response = SESSION.get(url, headers=HEADERS, timeout=timeout, stream=stream, allow_redirects=True)
            print(
                "HTTP", attempt, response.status_code, response.headers.get("content-type"),
                response.headers.get("content-length"), response.url, flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"request failed for {url}: {errors[-6:]}")


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", "", title or "")


def notice_date(item: dict[str, Any]) -> str:
    raw = str(item.get("notice_date") or item.get("display_time") or item.get("noticeDate") or "")
    return raw[:10]


def fetch_all_notices() -> list[dict[str, Any]]:
    notices: list[dict[str, Any]] = []
    page = 1
    while True:
        url = (
            "https://np-anotice-stock.eastmoney.com/api/security/ann"
            f"?sr=-1&page_size=100&page_index={page}&ann_type=A&client_source=web"
            f"&stock_list={STOCK_CODE}&f_node=0&s_node=0"
        )
        response = request(url, timeout=(20, 120))
        try:
            payload = response.json()
        finally:
            response.close()
        data = payload.get("data") or {}
        batch = data.get("list") or []
        total_hits = int(data.get("total_hits") or data.get("total") or 0)
        print("PAGE", page, "ITEMS", len(batch), "TOTAL", total_hits, flush=True)
        notices.extend(batch)
        if not batch or len(notices) >= total_hits or len(batch) < 100:
            break
        page += 1
        if page > 30:
            raise RuntimeError("unexpected notice pagination length")
    if not notices:
        raise RuntimeError("no announcements returned")
    return notices


def revision_priority(title: str) -> int:
    t = normalize_title(title)
    if any(word in t for word in ("更新后", "更正后", "修订版", "修订稿", "更新版")):
        return 3
    if any(word in t for word in ("更新", "更正", "修订")):
        return 2
    return 1


def valid_full_report_title(title: str) -> bool:
    t = normalize_title(title)
    excluded = (
        "摘要", "英文版", "英文", "取消", "审计报告", "财务报表", "社会责任报告",
        "内部控制", "独立董事", "董事会", "监事会", "问询函", "回复", "更正公告",
        "关于", "说明", "提示性公告",
    )
    return not any(word in t for word in excluded)


def select_documents(notices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []

    for year in range(2020, 2026):
        marker = f"{year}年年度报告"
        candidates = []
        for item in notices:
            title = str(item.get("title") or item.get("notice_title") or "")
            if marker in normalize_title(title) and valid_full_report_title(title):
                candidates.append(item)
        if not candidates:
            raise RuntimeError(f"annual report not found for {year}")
        candidates.sort(
            key=lambda item: (
                revision_priority(str(item.get("title") or item.get("notice_title") or "")),
                notice_date(item),
                str(item.get("art_code") or ""),
            ),
            reverse=True,
        )
        chosen = dict(candidates[0])
        chosen.update({"category": "annual_report", "report_year": year, "quarter": None})
        selected.append(chosen)

    quarter_candidates: list[tuple[int, int, str, dict[str, Any]]] = []
    pattern = re.compile(r"(20\d{2})年(第一季度|第三季度)报告")
    for item in notices:
        title = str(item.get("title") or item.get("notice_title") or "")
        t = normalize_title(title)
        if not valid_full_report_title(title):
            continue
        match = pattern.search(t)
        if not match:
            continue
        year = int(match.group(1))
        quarter = 1 if match.group(2) == "第一季度" else 3
        quarter_candidates.append((year, quarter, notice_date(item), item))
    if not quarter_candidates:
        raise RuntimeError("no first- or third-quarter report found")
    quarter_candidates.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    year, quarter, _, item = quarter_candidates[0]
    chosen = dict(item)
    chosen.update({"category": "latest_quarterly_report", "report_year": year, "quarter": quarter})
    selected.append(chosen)

    print(
        "SELECTED_JSON",
        json.dumps(
            [
                {
                    "date": notice_date(item),
                    "art_code": item.get("art_code"),
                    "title": item.get("title") or item.get("notice_title"),
                    "category": item["category"],
                    "year": item["report_year"],
                    "quarter": item["quarter"],
                }
                for item in selected
            ],
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return selected


def safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", "", value).strip("._")
    return value[:140] or "report"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pdf_urls(art_code: str) -> list[str]:
    return [
        f"https://pdf.dfcfw.com/pdf/H2_{art_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{art_code}_1.pdf",
    ]


def download_pdf(art_code: str, destination: Path) -> str:
    errors: list[str] = []
    for url in pdf_urls(art_code):
        try:
            response = request(url, stream=True)
            temp = destination.with_suffix(".pdf.part")
            temp.unlink(missing_ok=True)
            try:
                with temp.open("wb") as fh:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            fh.write(chunk)
                final_url = str(response.url)
            finally:
                response.close()
            if temp.stat().st_size < 20_000 or not temp.read_bytes()[:8].startswith(b"%PDF-"):
                raise RuntimeError(f"invalid PDF payload: {temp.stat().st_size} bytes")
            temp.replace(destination)
            return final_url
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc!r}")
    raise RuntimeError(f"unable to download {art_code}: {errors}")


def render_page(path: Path, page_number: int, suffix: str) -> str:
    prefix = RENDER_DIR / f"{path.stem}_{suffix}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
            "-r", "105", "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    png = Path(str(prefix) + ".png")
    if process.returncode != 0 or not png.exists() or png.stat().st_size < 3000:
        raise RuntimeError(
            f"render failed for {path.name} page {page_number}: "
            f"return={process.returncode}, stderr={process.stderr[-1200:]}"
        )
    return str(png.relative_to(WORK_DIR))


def validate_pdf(path: Path, item: dict[str, Any]) -> dict[str, Any]:
    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {qpdf.stderr[-2000:]}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 5:
        raise RuntimeError(f"unexpectedly short report: {path.name}, pages={pages}")

    sample_indices = sorted({0, min(1, pages - 1), max(0, pages // 2), pages - 1})
    text_parts: list[str] = []
    for index in sample_indices:
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_WARNING", path.name, index + 1, repr(exc), flush=True)
    text = re.sub(r"\s+", "", "\n".join(text_parts))
    identity_ok = SHORT_NAME in text or COMPANY in text or STOCK_CODE in text
    if text and not identity_ok:
        raise RuntimeError(f"issuer identity not found in sampled text: {path.name}")

    rendered = [
        render_page(path, 1, "first"),
        render_page(path, pages, "last"),
    ]
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "sample_text_extractable": bool(text),
        "identity_verified_when_text_extractable": identity_ok,
        "rendered_pages": [1, pages],
        "render_files": rendered,
    }


notices = fetch_all_notices()
selected = select_documents(notices)
records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()

for item in selected:
    art_code = str(item.get("art_code") or "").strip()
    if not art_code:
        raise RuntimeError(f"missing art_code: {item}")
    title = str(item.get("title") or item.get("notice_title") or art_code)
    date = notice_date(item)
    if item["category"] == "annual_report":
        folder = ANNUAL_DIR
        filename = f"{date.replace('-', '')}_{STOCK_CODE}_{item['report_year']}年年度报告.pdf"
        category_cn = "年度报告"
    else:
        folder = QUARTER_DIR
        quarter_cn = "第一季度" if item["quarter"] == 1 else "第三季度"
        filename = f"{date.replace('-', '')}_{STOCK_CODE}_{item['report_year']}年{quarter_cn}报告.pdf"
        category_cn = "最新季度报告"
    destination = folder / safe_name(filename)
    final_url = download_pdf(art_code, destination)
    validation = validate_pdf(destination, item)
    if validation["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate PDF detected: {destination.name}")
    seen_hashes.add(validation["sha256"])
    record = {
        "category": item["category"],
        "category_cn": category_cn,
        "report_year": item["report_year"],
        "quarter": item["quarter"],
        "notice_date": date,
        "title": title,
        "art_code": art_code,
        "relative_path": str(destination.relative_to(ROOT)),
        "source_url": final_url,
        "source_detail_url": f"https://data.eastmoney.com/notices/detail/{STOCK_CODE}/{art_code}.html",
        **validation,
    }
    records.append(record)
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

annual_years = sorted(r["report_year"] for r in records if r["category"] == "annual_report")
if annual_years != list(range(2020, 2026)):
    raise RuntimeError(f"annual report year mismatch: {annual_years}")
if sum(r["category"] == "latest_quarterly_report" for r in records) != 1:
    raise RuntimeError("latest quarterly report count mismatch")

latest_quarter = next(r for r in records if r["category"] == "latest_quarterly_report")
manifest = {
    "package_name": PACKAGE,
    "company": COMPANY,
    "short_name": SHORT_NAME,
    "stock_code": STOCK_CODE,
    "checked_as_of": CHECKED_AS_OF,
    "scope": {
        "annual_reports": "2020—2025年度完整年度报告；如同一年度存在修订或更新版本，优先采用后续披露的完整版本。",
        "latest_quarterly_report": (
            f"截至{CHECKED_AS_OF}公开披露的最新季度报告："
            f"{latest_quarter['report_year']}年第{latest_quarter['quarter']}季度报告。"
        ),
        "exclusions": "排除年度报告摘要、英文版、审计报告单行文件、半年度报告及仅用于说明更正事项的公告。",
    },
    "document_count": len(records),
    "records": records,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as fh:
    writer = csv.writer(fh)
    writer.writerow([
        "类别", "报告年度", "季度", "披露日期", "公告标题", "文件", "页数", "字节数",
        "SHA-256", "公告编号", "PDF来源", "公告详情页",
    ])
    for record in records:
        writer.writerow([
            record["category_cn"], record["report_year"], record["quarter"],
            record["notice_date"], record["title"], record["relative_path"],
            record["pages"], record["bytes"], record["sha256"], record["art_code"],
            record["source_url"], record["source_detail_url"],
        ])

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as fh:
    for record in records:
        fh.write(f"{record['sha256']}  {record['relative_path']}\n")

quarter_name = "第一季度" if latest_quarter["quarter"] == 1 else "第三季度"
readme = [
    f"{SHORT_NAME}（{STOCK_CODE}）2020—2025年年度报告及最新季度报告",
    "",
    f"核对日期：{CHECKED_AS_OF}",
    f"文件总数：{len(records)}份PDF",
    "",
    "包含内容：",
    "- 2020—2025年年度报告全文，共6份；",
    f"- {latest_quarter['report_year']}年{quarter_name}报告，共1份。",
    "",
    "说明：",
    "- 年报均为全文版，未收录摘要版；",
    "- 半年度报告不属于季报，本压缩包未纳入；",
    "- 每份PDF均检查文件头、qpdf结构、页数、公司名称或股票代码，并渲染首页与末页；",
    "- 来源、页数及哈希值见文件清单.csv、SHA256SUMS.txt和manifest.json。",
]
(VERIFY_DIR / "README.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")

zip_path = Path(PACKAGE + ".zip")
zip_path.unlink(missing_ok=True)
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, path.as_posix())

with zipfile.ZipFile(zip_path, "r") as archive:
    bad = archive.testzip()
    if bad:
        raise RuntimeError(f"ZIP integrity failure: {bad}")
    pdf_count = sum(name.lower().endswith(".pdf") for name in archive.namelist())
    if pdf_count != 7:
        raise RuntimeError(f"ZIP PDF count mismatch: {pdf_count}")

print(
    "FINAL_ZIP", zip_path,
    "bytes", zip_path.stat().st_size,
    "sha256", sha256(zip_path),
    flush=True,
)
print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
