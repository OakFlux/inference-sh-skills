from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-10-05"
COMPANY = "甘源食品股份有限公司"
SHORT_NAME = "甘源食品"
STOCK_CODE = "002991"
PACKAGE = "甘源食品_002991_全部年报_招股说明书_最新季报"
ROOT = Path(PACKAGE)
ANNUAL_DIR = ROOT / "01_年度报告"
PROSPECTUS_DIR = ROOT / "02_招股说明书"
QUARTER_DIR = ROOT / "03_最新季度报告"
VERIFY_DIR = ROOT / "04_说明与校验"
WORK_DIR = Path("_ganyuan_002991_filings_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (ANNUAL_DIR, PROSPECTUS_DIR, QUARTER_DIR, VERIFY_DIR, RENDER_DIR):
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
            response = SESSION.get(
                url,
                headers=HEADERS,
                timeout=timeout,
                stream=stream,
                allow_redirects=True,
            )
            print(
                "HTTP", attempt, response.status_code,
                response.headers.get("content-type"),
                response.headers.get("content-length"),
                response.url,
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(attempt * 2, 10))
    raise RuntimeError(f"request failed for {url}: {errors[-6:]}")


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", "", title or "")


def notice_date(item: dict[str, Any]) -> str:
    raw = str(item.get("notice_date") or item.get("display_time") or item.get("noticeDate") or "")
    return raw[:10]


def item_title(item: dict[str, Any]) -> str:
    return str(item.get("title") or item.get("notice_title") or "")


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
        if page > 40:
            raise RuntimeError("unexpected announcement pagination length")
    if not notices:
        raise RuntimeError("no announcements returned")
    return notices


def revision_priority(title: str) -> int:
    t = normalize_title(title)
    if any(word in t for word in ("更新后", "更正后", "修订版", "修订稿", "更新版")):
        return 4
    if any(word in t for word in ("更新", "更正", "修订")):
        return 3
    if "申报稿" in t:
        return 2
    return 1


def valid_annual_title(title: str) -> bool:
    t = normalize_title(title)
    excluded = (
        "摘要", "英文版", "英文", "取消", "审计报告", "财务报表",
        "社会责任报告", "内部控制", "独立董事", "董事会", "监事会",
        "问询函", "回复", "更正公告", "关于", "说明", "提示性公告",
    )
    return not any(word in t for word in excluded)


def valid_quarter_title(title: str) -> bool:
    t = normalize_title(title)
    excluded = (
        "英文版", "英文", "取消", "更正公告", "关于", "说明", "提示性公告",
        "审阅报告", "财务报表",
    )
    return not any(word in t for word in excluded)


def valid_prospectus_title(title: str) -> bool:
    t = normalize_title(title)
    if "首次公开发行" not in t or "招股说明书" not in t:
        return False
    excluded = (
        "摘要", "招股意向书", "提示性公告", "上市公告书", "发行公告",
        "网上路演", "询价", "申购", "配售结果", "发行结果", "更正公告",
        "关于", "说明", "问询函", "回复",
    )
    return not any(word in t for word in excluded)


def select_documents(notices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []

    # The company listed in 2020, so 2020-2025 are all post-listing annual reports
    # available as of the check date.
    for year in range(2020, 2026):
        marker = f"{year}年年度报告"
        candidates: list[dict[str, Any]] = []
        for item in notices:
            title = item_title(item)
            if marker in normalize_title(title) and valid_annual_title(title):
                candidates.append(item)
        if not candidates:
            raise RuntimeError(f"annual report not found for {year}")
        candidates.sort(
            key=lambda row: (
                revision_priority(item_title(row)),
                notice_date(row),
                str(row.get("art_code") or ""),
            ),
            reverse=True,
        )
        chosen = dict(candidates[0])
        chosen.update({"category": "annual_report", "report_year": year, "quarter": None})
        selected.append(chosen)

    prospectus_candidates: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for item in notices:
        title = item_title(item)
        art_code = str(item.get("art_code") or "").strip()
        if art_code and valid_prospectus_title(title) and art_code not in seen_codes:
            prospectus_candidates.append(item)
            seen_codes.add(art_code)
    prospectus_candidates.sort(
        key=lambda row: (notice_date(row), str(row.get("art_code") or ""))
    )
    if not prospectus_candidates:
        raise RuntimeError("no prospectus announcement found")
    for item in prospectus_candidates:
        chosen = dict(item)
        chosen.update({"category": "prospectus", "report_year": None, "quarter": None})
        selected.append(chosen)

    quarter_candidates: list[tuple[int, int, int, str, dict[str, Any]]] = []
    pattern = re.compile(r"(20\d{2})年(第一季度|第三季度)报告")
    for item in notices:
        title = item_title(item)
        t = normalize_title(title)
        if not valid_quarter_title(title):
            continue
        match = pattern.search(t)
        if not match:
            continue
        year = int(match.group(1))
        quarter = 1 if match.group(2) == "第一季度" else 3
        quarter_candidates.append(
            (year, quarter, revision_priority(title), notice_date(item), item)
        )
    if not quarter_candidates:
        raise RuntimeError("no first- or third-quarter report found")
    quarter_candidates.sort(key=lambda row: (row[0], row[1], row[2], row[3]), reverse=True)
    year, quarter, _, _, item = quarter_candidates[0]
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
                    "title": item_title(item),
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
    return value[:180] or "document"


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
    valid = (
        process.returncode == 0
        and png.exists()
        and png.stat().st_size > 3000
        and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(
            f"render failed for {path.name} page {page_number}: "
            f"return={process.returncode}, stderr={process.stderr[-1500:]}"
        )
    return str(png.relative_to(WORK_DIR))


def validate_pdf(path: Path, item: dict[str, Any]) -> dict[str, Any]:
    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {qpdf.stderr[-2000:]}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    minimum = 5 if item["category"] != "prospectus" else 50
    if pages < minimum:
        raise RuntimeError(f"unexpectedly short PDF: {path.name}, pages={pages}")

    sample_indices = sorted({0, min(1, pages - 1), min(2, pages - 1), max(0, pages // 2), pages - 1})
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

    marker_ok = True
    if item["category"] == "annual_report":
        marker_ok = f"{item['report_year']}年年度报告" in text if text else False
    elif item["category"] == "prospectus":
        marker_ok = "招股说明书" in text if text else False
    else:
        quarter_cn = "第一季度" if item["quarter"] == 1 else "第三季度"
        marker_ok = quarter_cn in text and "报告" in text if text else False
    if text and not marker_ok:
        print("MARKER_WARNING", path.name, item["category"], flush=True)

    middle = max(1, (pages + 1) // 2)
    render_pages = sorted({1, middle, pages})
    render_files = [
        render_page(path, page_number, f"p{page_number}")
        for page_number in render_pages
    ]
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "sample_text_extractable": bool(text),
        "identity_verified_when_text_extractable": identity_ok,
        "document_marker_verified_when_text_extractable": marker_ok,
        "rendered_pages": render_pages,
        "render_files": render_files,
    }


notices = fetch_all_notices()
selected = select_documents(notices)
records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()
prospectus_duplicate_notes: list[dict[str, str]] = []

for item in selected:
    art_code = str(item.get("art_code") or "").strip()
    if not art_code:
        raise RuntimeError(f"missing art_code: {item}")
    title = item_title(item)
    date = notice_date(item)

    if item["category"] == "annual_report":
        folder = ANNUAL_DIR
        filename = f"{date.replace('-', '')}_{STOCK_CODE}_{item['report_year']}年年度报告.pdf"
        category_cn = "年度报告"
        version = "年度完整报告"
    elif item["category"] == "prospectus":
        folder = PROSPECTUS_DIR
        t = normalize_title(title)
        if "申报稿" in t:
            version = "申报稿"
        elif any(word in t for word in ("更新", "修订", "更正")):
            version = "更新或修订稿"
        else:
            version = "正式发行版"
        filename = f"{date.replace('-', '')}_{STOCK_CODE}_{safe_name(title)}.pdf"
        category_cn = "招股说明书"
    else:
        folder = QUARTER_DIR
        quarter_cn = "第一季度" if item["quarter"] == 1 else "第三季度"
        filename = f"{date.replace('-', '')}_{STOCK_CODE}_{item['report_year']}年{quarter_cn}报告.pdf"
        category_cn = "最新季度报告"
        version = "季度完整报告"

    destination = folder / safe_name(filename)
    final_url = download_pdf(art_code, destination)
    validation = validate_pdf(destination, item)

    if validation["sha256"] in seen_hashes:
        if item["category"] == "prospectus":
            prospectus_duplicate_notes.append(
                {
                    "title": title,
                    "art_code": art_code,
                    "sha256": validation["sha256"],
                    "reason": "与已收录招股说明书内容完全相同，已按哈希去重。",
                }
            )
            destination.unlink(missing_ok=True)
            print("SKIP_DUPLICATE_PROSPECTUS", title, art_code, validation["sha256"], flush=True)
            continue
        raise RuntimeError(f"duplicate non-prospectus PDF detected: {destination.name}")
    seen_hashes.add(validation["sha256"])

    record = {
        "category": item["category"],
        "category_cn": category_cn,
        "version": version,
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
prospectus_records = [r for r in records if r["category"] == "prospectus"]
if not prospectus_records:
    raise RuntimeError("no unique prospectus PDF retained")
quarter_records = [r for r in records if r["category"] == "latest_quarterly_report"]
if len(quarter_records) != 1:
    raise RuntimeError(f"latest quarterly report count mismatch: {len(quarter_records)}")

latest_quarter = quarter_records[0]
manifest = {
    "package_name": PACKAGE,
    "company": COMPANY,
    "short_name": SHORT_NAME,
    "stock_code": STOCK_CODE,
    "checked_as_of": CHECKED_AS_OF,
    "scope": {
        "annual_reports": "上市以来2020—2025年度完整年度报告；同一年度存在更新、修订或更正版本时，采用后续披露的最新完整版本。",
        "prospectus": "公开公告库中可取得的全部非摘要版首次公开发行股票招股说明书，包括申报稿、更新或修订稿及正式发行版；内容完全相同的文件按SHA-256去重。",
        "latest_quarterly_report": (
            f"截至{CHECKED_AS_OF}公开披露的最新第一季度或第三季度报告："
            f"{latest_quarter['report_year']}年第{latest_quarter['quarter']}季度报告。"
        ),
        "exclusions": "排除年度报告摘要、英文版、招股说明书摘要、招股意向书、发行公告、半年度报告及仅说明更正事项的公告。",
    },
    "document_count": len(records),
    "prospectus_duplicate_notes": prospectus_duplicate_notes,
    "records": records,
}
(ROOT / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as fh:
    writer = csv.writer(fh)
    writer.writerow([
        "类别", "版本", "报告年度", "季度", "披露日期", "标题", "页数",
        "字节数", "SHA-256", "文件路径", "公告代码", "PDF来源", "公告详情页",
    ])
    for record in records:
        writer.writerow([
            record["category_cn"], record["version"], record["report_year"],
            record["quarter"], record["notice_date"], record["title"],
            record["pages"], record["bytes"], record["sha256"],
            record["relative_path"], record["art_code"], record["source_url"],
            record["source_detail_url"],
        ])

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as fh:
    for record in records:
        fh.write(f"{record['sha256']}  {record['relative_path']}\n")

readme_lines = [
    f"{SHORT_NAME}（{STOCK_CODE}）全部年报、招股说明书及最新季报",
    "",
    f"核对日期：{CHECKED_AS_OF}",
    f"公司全称：{COMPANY}",
    f"文件总数：{len(records)}份PDF",
    "",
    "目录说明：",
    "- 01_年度报告：2020—2025年度完整年报，每年度保留最新有效版本；",
    "- 02_招股说明书：公开可取得的申报稿、更新/修订稿及正式发行版，内容相同者已去重；",
    "- 03_最新季度报告：截至核对日期最新的一季报或三季报；",
    "- 04_说明与校验：文件清单、来源、哈希值及机器可读manifest。",
    "",
    "收录文件：",
]
for index, record in enumerate(records, start=1):
    readme_lines.append(
        f"{index}. {record['notice_date']} | {record['category_cn']} | "
        f"{record['version']} | {record['title']} | {record['pages']}页"
    )
if prospectus_duplicate_notes:
    readme_lines.extend(["", "招股说明书去重记录："])
    for note in prospectus_duplicate_notes:
        readme_lines.append(
            f"- {note['title']}（{note['art_code']}）：{note['reason']}"
        )
readme_lines.extend([
    "",
    "校验说明：",
    "- 所有PDF均验证文件头、qpdf结构和实际页数；",
    "- 抽取样本文本核验公司名称、股票代码及文档类型；",
    "- 每份PDF均渲染首页、中间页和末页，确认可正常显示；",
    "- 全部文件按SHA-256检查重复；",
    "- 压缩包完成ZIP CRC完整性测试。",
])
(VERIFY_DIR / "README.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

zip_path = Path(PACKAGE + ".zip")
zip_path.unlink(missing_ok=True)
with zipfile.ZipFile(
    zip_path,
    "w",
    compression=zipfile.ZIP_DEFLATED,
    compresslevel=6,
    allowZip64=True,
) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, path.as_posix())

with zipfile.ZipFile(zip_path, "r") as archive:
    bad_member = archive.testzip()
    if bad_member:
        raise RuntimeError(f"ZIP integrity failure at {bad_member}")
    pdf_count = sum(1 for name in archive.namelist() if name.lower().endswith(".pdf"))
    if pdf_count != len(records):
        raise RuntimeError(f"ZIP PDF count mismatch: expected {len(records)}, got {pdf_count}")

print(
    "FINAL_ZIP", zip_path,
    "bytes", zip_path.stat().st_size,
    "sha256", sha256(zip_path),
    flush=True,
)
print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
