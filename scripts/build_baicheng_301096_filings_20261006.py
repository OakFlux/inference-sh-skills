from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any, Iterable

import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-10-06"
COMPANY = "杭州百诚医药科技股份有限公司"
SHORT_NAME = "百诚医药"
STOCK_CODE = "301096"
PACKAGE = "百诚医药_301096_2020-2025年报_2026最新季报及半年报"
ROOT = Path(PACKAGE)
ANNUAL_DIR = ROOT / "01_年度报告"
QUARTER_DIR = ROOT / "02_最新季度报告"
HALF_DIR = ROOT / "03_补充半年度报告"
VERIFY_DIR = ROOT / "04_说明与校验"
WORK_DIR = Path("_baicheng_301096_filings_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (ANNUAL_DIR, QUARTER_DIR, HALF_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/pdf,application/octet-stream;q=0.9,text/html;q=0.7,*/*;q=0.5",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request(
    url: str,
    *,
    stream: bool = False,
    referer: str | None = None,
    timeout: tuple[int, int] = (25, 420),
    allow_redirects: bool = True,
) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        headers = dict(HEADERS)
        if referer:
            headers["Referer"] = referer
        try:
            response = SESSION.get(
                url,
                headers=headers,
                timeout=timeout,
                stream=stream,
                allow_redirects=allow_redirects,
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


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def notice_date(item: dict[str, Any]) -> str:
    return str(
        item.get("notice_date")
        or item.get("display_time")
        or item.get("noticeDate")
        or ""
    )[:10]


def item_title(item: dict[str, Any]) -> str:
    return str(item.get("title") or item.get("notice_title") or "")


def revision_priority(title: str) -> int:
    text = normalize(title)
    if any(word in text for word in ("更新后", "更正后", "修订版", "更新版", "修订后")):
        return 5
    if any(word in text for word in ("更新", "更正", "修订")):
        return 3
    return 1


def fetch_all_notices() -> list[dict[str, Any]]:
    notices: list[dict[str, Any]] = []
    for page in range(1, 31):
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
        total = int(data.get("total_hits") or data.get("total") or 0)
        print("NOTICE_PAGE", page, "ITEMS", len(batch), "TOTAL", total, flush=True)
        notices.extend(batch)
        if not batch or len(notices) >= total or len(batch) < 100:
            break
    if not notices:
        raise RuntimeError("no company announcements returned")
    return notices


def valid_annual(title: str) -> bool:
    text = normalize(title)
    excluded = (
        "摘要", "英文版", "英文", "取消", "审计报告", "财务报表",
        "社会责任报告", "可持续发展报告", "环境社会", "ESG报告",
        "内部控制", "独立董事", "董事会", "监事会", "问询函", "回复",
        "更正公告", "关于", "说明", "提示性公告",
    )
    return not any(word in text for word in excluded)


def valid_periodic(title: str) -> bool:
    text = normalize(title)
    excluded = (
        "摘要", "英文版", "英文", "取消", "更正公告", "关于", "说明",
        "提示性公告", "审阅报告", "财务报表", "预约", "预披露",
        "披露时间", "审议",
    )
    return not any(word in text for word in excluded)


def quarter_from_title(title: str) -> tuple[int, int] | None:
    match = re.search(
        r"(20\d{2})年(第一季度|第三季度|一季度|三季度|第1季度|第3季度)报告",
        normalize(title),
    )
    if not match:
        return None
    wording = match.group(2)
    quarter = 1 if wording in ("第一季度", "一季度", "第1季度") else 3
    return int(match.group(1)), quarter


def half_year_from_title(title: str) -> int | None:
    match = re.search(r"(20\d{2})年(半年度|中期)报告", normalize(title))
    return int(match.group(1)) if match else None


def select_documents(notices: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    selected: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []

    for year in range(2020, 2026):
        marker = f"{year}年年度报告"
        candidates = [
            item for item in notices
            if marker in normalize(item_title(item)) and valid_annual(item_title(item))
        ]
        if not candidates:
            missing.append({
                "document": f"{year}年年度报告",
                "reason": "公告检索中未发现该年度的上市公司年度报告全文。",
            })
            continue
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

    if not any(item.get("category") == "annual_report" for item in selected):
        raise RuntimeError("no annual reports found")

    quarterly: list[tuple[int, int, int, str, dict[str, Any]]] = []
    for item in notices:
        title = item_title(item)
        if not valid_periodic(title):
            continue
        parsed = quarter_from_title(title)
        if parsed:
            year, quarter = parsed
            quarterly.append((year, quarter, revision_priority(title), notice_date(item), item))
    if not quarterly:
        raise RuntimeError("no first- or third-quarter report found")
    quarterly.sort(key=lambda row: (row[0], row[1], row[2], row[3]), reverse=True)
    year, quarter, _, _, item = quarterly[0]
    chosen = dict(item)
    chosen.update({"category": "latest_quarterly_report", "report_year": year, "quarter": quarter})
    selected.append(chosen)

    half_years: list[tuple[int, int, str, dict[str, Any]]] = []
    for item in notices:
        title = item_title(item)
        if not valid_periodic(title):
            continue
        year = half_year_from_title(title)
        if year is not None:
            half_years.append((year, revision_priority(title), notice_date(item), item))
    if half_years:
        half_years.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
        year, _, _, item = half_years[0]
        chosen = dict(item)
        chosen.update({"category": "latest_half_year_report", "report_year": year, "quarter": None})
        selected.append(chosen)

    print(
        "SELECTED_NOTICES",
        json.dumps([
            {
                "date": notice_date(item),
                "art_code": item.get("art_code"),
                "title": item_title(item),
                "category": item["category"],
                "year": item["report_year"],
                "quarter": item["quarter"],
            }
            for item in selected
        ], ensure_ascii=False, indent=2),
        flush=True,
    )
    print("MISSING", json.dumps(missing, ensure_ascii=False, indent=2), flush=True)
    return selected, missing


def download_to(
    urls: Iterable[str],
    destination: Path,
    *,
    referer: str | None = None,
    minimum_bytes: int = 20_000,
) -> str:
    errors: list[str] = []
    for url in urls:
        for redirects in (True, False):
            temp = destination.with_suffix(destination.suffix + ".part")
            temp.unlink(missing_ok=True)
            try:
                response = request(url, stream=True, referer=referer, allow_redirects=redirects)
                try:
                    with temp.open("wb") as handle:
                        for chunk in response.iter_content(1024 * 1024):
                            if chunk:
                                handle.write(chunk)
                    final_url = str(response.url)
                    content_type = str(response.headers.get("content-type") or "")
                finally:
                    response.close()
                size = temp.stat().st_size
                head = temp.read_bytes()[:8]
                print("DOWNLOAD_CANDIDATE", url, redirects, size, content_type, head, final_url, flush=True)
                if size < minimum_bytes or not head.startswith(b"%PDF-"):
                    raise RuntimeError(f"invalid PDF payload: size={size}, type={content_type}, head={head!r}")
                temp.replace(destination)
                return final_url
            except Exception as exc:  # noqa: BLE001
                temp.unlink(missing_ok=True)
                errors.append(f"{url} redirects={redirects}: {exc!r}")
    raise RuntimeError(f"all download candidates failed for {destination.name}: {errors}")


def download_notice_pdf(art_code: str, destination: Path) -> str:
    return download_to(
        [
            f"https://pdf.dfcfw.com/pdf/H2_{art_code}_1.pdf",
            f"https://pdf.dfcfw.com/pdf/H3_{art_code}_1.pdf",
        ],
        destination,
        referer="https://data.eastmoney.com/notices/",
    )


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
        process.returncode == 0 and png.exists() and png.stat().st_size > 3000
        and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(
            f"render failed for {path.name} page {page_number}: "
            f"return={process.returncode}, stderr={process.stderr[-1500:]}"
        )
    return str(png.relative_to(WORK_DIR))


def validate_pdf(
    path: Path,
    *,
    category: str,
    year: int,
    quarter: int | None = None,
    minimum_pages: int = 5,
) -> dict[str, Any]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-2500:]}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < minimum_pages:
        raise RuntimeError(f"unexpectedly short PDF: {path.name}, pages={pages}")

    sample_indices = sorted({0, min(1, pages - 1), min(2, pages - 1), max(0, pages // 2), pages - 1})
    text_parts: list[str] = []
    for index in sample_indices:
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_WARNING", path.name, index + 1, repr(exc), flush=True)
    text = normalize("\n".join(text_parts))

    identity_ok = COMPANY in text or SHORT_NAME in text or STOCK_CODE in text
    if text and not identity_ok:
        print("IDENTITY_TEXT_WARNING", path.name, "rely on announcement metadata and rendered pages", flush=True)

    marker_ok = True
    if category == "annual_report":
        marker_ok = f"{year}年年度报告" in text if text else False
    elif category == "latest_quarterly_report" and quarter:
        markers = ("第一季度报告", "一季度报告", "第1季度报告") if quarter == 1 else ("第三季度报告", "三季度报告", "第3季度报告")
        marker_ok = any(marker in text for marker in markers) if text else False
    elif category == "latest_half_year_report":
        marker_ok = any(marker in text for marker in ("半年度报告", "中期报告")) if text else False
    if text and not marker_ok:
        print("MARKER_WARNING", path.name, category, year, quarter, flush=True)

    render_pages = sorted({1, max(1, (pages + 1) // 2), pages})
    renders = [render_page(path, page_number, f"p{page_number}") for page_number in render_pages]

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "sample_text_extractable": bool(text),
        "identity_verified_when_text_extractable": identity_ok,
        "document_marker_verified_when_text_extractable": marker_ok,
        "rendered_pages": render_pages,
        "render_files": renders,
    }


def output_file(item: dict[str, Any]) -> tuple[Path, str, str]:
    category = item["category"]
    year = int(item["report_year"])
    date = notice_date(item).replace("-", "")
    if category == "annual_report":
        return ANNUAL_DIR / f"{date}_{STOCK_CODE}_{year}年年度报告.pdf", "年度报告", "年度完整报告"
    if category == "latest_quarterly_report":
        quarter = int(item["quarter"])
        quarter_cn = "第一季度" if quarter == 1 else "第三季度"
        return QUARTER_DIR / f"{date}_{STOCK_CODE}_{year}年{quarter_cn}报告.pdf", "最新季度报告", "季度完整报告"
    return HALF_DIR / f"{date}_{STOCK_CODE}_{year}年半年度报告.pdf", "补充半年度报告", "半年度完整报告"


notices = fetch_all_notices()
selected, missing_documents = select_documents(notices)
records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()

for item in selected:
    art_code = str(item.get("art_code") or "")
    if not art_code:
        raise RuntimeError(f"missing art_code: {item}")
    destination, category_cn, version = output_file(item)
    final_url = download_notice_pdf(art_code, destination)
    validation = validate_pdf(
        destination,
        category=item["category"],
        year=int(item["report_year"]),
        quarter=item.get("quarter"),
        minimum_pages=5,
    )
    if validation["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate PDF detected: {destination.name}")
    seen_hashes.add(validation["sha256"])
    record = {
        "category": item["category"],
        "category_cn": category_cn,
        "version": version,
        "report_year": int(item["report_year"]),
        "quarter": item.get("quarter"),
        "notice_date": notice_date(item),
        "title": item_title(item),
        "art_code": art_code,
        "relative_path": str(destination.relative_to(ROOT)),
        "source": "东方财富公告镜像（原始披露PDF）",
        "source_url": final_url,
        "source_detail_url": f"https://data.eastmoney.com/notices/detail/{STOCK_CODE}/{art_code}.html",
        **validation,
    }
    records.append(record)
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

annual_years = sorted(record["report_year"] for record in records if record["category"] == "annual_report")
quarter_record = next(record for record in records if record["category"] == "latest_quarterly_report")
half_record = next((record for record in records if record["category"] == "latest_half_year_report"), None)

manifest = {
    "package_name": PACKAGE,
    "company": COMPANY,
    "short_name": SHORT_NAME,
    "stock_code": STOCK_CODE,
    "checked_as_of": CHECKED_AS_OF,
    "scope": {
        "annual_reports": f"公告检索可取得的完整年度报告年份：{annual_years}。2020—2025中未披露的年度已在missing_documents中说明。",
        "latest_quarterly_report": f"截至{CHECKED_AS_OF}公开披露的最新第一季度或第三季度报告：{quarter_record['report_year']}年第{quarter_record['quarter']}季度报告。",
        "latest_half_year_report": f"补充收录：{half_record['report_year']}年半年度报告。" if half_record else "未发现可收录的半年度报告。",
        "exclusions": "排除年度报告摘要、英文版、单独审计文件、公告说明及其他非完整报告。",
    },
    "missing_documents": missing_documents,
    "document_count": len(records),
    "records": records,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as handle:
    writer = csv.writer(handle)
    writer.writerow(["文件", "类别", "报告年度", "季度", "披露日期", "标题", "页数", "字节数", "SHA-256", "来源详情页", "PDF来源"])
    for record in records:
        writer.writerow([
            record["relative_path"], record["category_cn"], record["report_year"], record["quarter"],
            record["notice_date"], record["title"], record["pages"], record["bytes"], record["sha256"],
            record["source_detail_url"], record["source_url"],
        ])

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as handle:
    for record in records:
        handle.write(f"{record['sha256']}  {record['relative_path']}\n")

readme = [
    f"{SHORT_NAME}（{STOCK_CODE}）年度报告及最新定期报告文件包",
    "",
    f"核对日期：{CHECKED_AS_OF}",
    f"收录PDF数量：{len(records)}份",
    "",
    "收录文件：",
]
for index, record in enumerate(records, 1):
    readme.append(f"{index}. {record['notice_date']} | {record['category_cn']} | {record['title']} | {record['pages']}页")
if missing_documents:
    readme.extend(["", "未收录年度及原因："])
    for item in missing_documents:
        readme.append(f"- {item['document']}：{item['reason']}")
readme.extend([
    "",
    "说明：",
    "- 年度报告均为完整全文版，已排除摘要、英文版和单独审计文件；",
    "- “最新季报”按第一季度或第三季度报告口径识别；半年报不称为季报，单独放入补充目录；",
    "- 每份PDF均检查文件头、qpdf结构、实际页数、报告标识，并渲染首页、中间页和末页；",
    "- 详细来源、页数及校验值见文件清单.csv、SHA256SUMS.txt和manifest.json。",
])
(VERIFY_DIR / "README.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")

zip_path = Path(PACKAGE + ".zip")
zip_path.unlink(missing_ok=True)
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, path.as_posix())

with zipfile.ZipFile(zip_path, "r") as archive:
    bad_member = archive.testzip()
    if bad_member:
        raise RuntimeError(f"ZIP integrity test failed at {bad_member}")
    pdf_count = sum(name.lower().endswith(".pdf") for name in archive.namelist())
    if pdf_count != len(records):
        raise RuntimeError(f"ZIP PDF count mismatch: expected {len(records)}, got {pdf_count}")

print("FINAL_ZIP", zip_path, "bytes", zip_path.stat().st_size, "sha256", sha256(zip_path), flush=True)
print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
