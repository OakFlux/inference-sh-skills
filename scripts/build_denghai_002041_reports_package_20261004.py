from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import time
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-10-04"
COMPANY = "登海种业"
FULL_COMPANY = "山东登海种业股份有限公司"
STOCK_CODE = "002041"
PACKAGE = "登海种业_002041_2020-2025年报_2026最新季报及半年报"
ROOT = Path(PACKAGE)
ANNUAL_DIR = ROOT / "01_年度报告"
QUARTER_DIR = ROOT / "02_最新季报"
SUPPLEMENT_DIR = ROOT / "03_补充定期报告"
VERIFY_DIR = ROOT / "04_说明与校验"
WORK_DIR = Path("_denghai_002041_filings_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (ANNUAL_DIR, QUARTER_DIR, SUPPLEMENT_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
    "Accept": "application/json,text/javascript,application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
CNINFO_QUERY = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STOCK_LIST = "https://www.cninfo.com.cn/new/data/szse_stock.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_title(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value or "")
    return re.sub(r"\s+", "", value).replace("：", ":")


def request(method: str, url: str, *, data: dict[str, Any] | None = None,
            stream: bool = False, referer: str | None = None,
            timeout: tuple[int, int] = (20, 360)) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        headers = dict(HEADERS)
        if referer:
            headers["Referer"] = referer
        if method.upper() == "POST":
            headers.update({
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": "https://www.cninfo.com.cn",
                "X-Requested-With": "XMLHttpRequest",
            })
        try:
            response = SESSION.request(
                method.upper(), url, data=data, headers=headers,
                timeout=timeout, stream=stream, allow_redirects=True,
            )
            print(
                "HTTP", method.upper(), url, "attempt", attempt,
                "status", response.status_code,
                "type", response.headers.get("content-type"),
                "length", response.headers.get("content-length"),
                "final", response.url,
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(attempt * 2, 10))
    raise RuntimeError(f"request failed for {url}: {errors[-6:]}")


def get_org_id() -> str:
    response = request(
        "GET", CNINFO_STOCK_LIST,
        referer="https://www.cninfo.com.cn/",
        timeout=(20, 120),
    )
    try:
        payload = response.json()
    finally:
        response.close()
    for row in payload.get("stockList", []):
        if str(row.get("code")) == STOCK_CODE:
            org_id = str(row.get("orgId") or "")
            if not org_id:
                break
            print("STOCK_ROW", json.dumps(row, ensure_ascii=False), flush=True)
            return org_id
    raise RuntimeError(f"CNInfo orgId not found for {STOCK_CODE}")


ORG_ID = get_org_id()


def query_announcements(search_key: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    form = {
        "pageNum": "1",
        "pageSize": "100",
        "column": "szse",
        "tabName": "fulltext",
        "plate": "sz",
        "stock": f"{STOCK_CODE},{ORG_ID}",
        "searchkey": search_key,
        "secid": "",
        "category": "",
        "trade": "",
        "seDate": f"{start_date}~{end_date}",
        "sortName": "time",
        "sortType": "desc",
        "isHLtitle": "false",
    }
    response = request(
        "POST", CNINFO_QUERY, data=form,
        referer=f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={STOCK_CODE}&orgId={ORG_ID}",
        timeout=(20, 120),
    )
    try:
        payload = response.json()
    finally:
        response.close()
    rows = payload.get("announcements") or []
    print(
        "QUERY", search_key, start_date, end_date,
        "total", payload.get("totalAnnouncement"),
        "returned", len(rows),
        flush=True,
    )
    for row in rows:
        print(
            "ROW",
            json.dumps(
                {
                    "title": clean_title(str(row.get("announcementTitle") or "")),
                    "time": row.get("announcementTime"),
                    "adjunctUrl": row.get("adjunctUrl"),
                    "announcementId": row.get("announcementId"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return rows


def row_date(row: dict[str, Any]) -> str:
    ts = row.get("announcementTime")
    if not ts:
        return ""
    return datetime.fromtimestamp(
        float(ts) / 1000,
        timezone(timedelta(hours=8)),
    ).strftime("%Y-%m-%d")


def choose_annual(year: int) -> dict[str, Any]:
    key = f"{year}年年度报告"
    rows = query_announcements(key, f"{year + 1}-01-01", f"{year + 2}-12-31")
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for row in rows:
        title = clean_title(str(row.get("announcementTitle") or ""))
        if key not in title:
            continue
        if any(token in title for token in ("摘要", "审计报告", "问询函", "说明会", "已取消")):
            continue
        adjunct = str(row.get("adjunctUrl") or "")
        if not adjunct.lower().endswith(".pdf"):
            continue
        score = 10
        if title == key:
            score += 30
        if any(token in title for token in ("更正后", "更新后", "修订版", "修订稿")):
            score += 80
        if any(token in title for token in ("更新前", "更正前")):
            score -= 40
        ts = int(row.get("announcementTime") or 0)
        candidates.append((score, ts, row))
    if not candidates:
        raise RuntimeError(f"no full annual report found for {year}")
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = candidates[0][2]
    print("SELECTED_ANNUAL", year, json.dumps(selected, ensure_ascii=False, default=str), flush=True)
    return selected


def choose_periodic(search_keys: list[str], start_date: str, end_date: str,
                    exclude_tokens: tuple[str, ...] = ("摘要", "更正公告")) -> dict[str, Any] | None:
    all_rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for key in search_keys:
        for row in query_announcements(key, start_date, end_date):
            rid = str(row.get("announcementId") or row.get("adjunctUrl") or "")
            if rid and rid not in seen_ids:
                seen_ids.add(rid)
                all_rows.append(row)
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for row in all_rows:
        title = clean_title(str(row.get("announcementTitle") or ""))
        if not any(key in title for key in search_keys):
            continue
        if any(token in title for token in exclude_tokens):
            continue
        adjunct = str(row.get("adjunctUrl") or "")
        if not adjunct.lower().endswith(".pdf"):
            continue
        score = 10
        if any(token in title for token in ("更正后", "更新后", "修订版")):
            score += 60
        ts = int(row.get("announcementTime") or 0)
        candidates.append((score, ts, row))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = candidates[0][2]
    print("SELECTED_PERIODIC", json.dumps(selected, ensure_ascii=False, default=str), flush=True)
    return selected


def static_url(row: dict[str, Any]) -> str:
    adjunct = str(row.get("adjunctUrl") or "").lstrip("/")
    if not adjunct:
        raise RuntimeError("announcement has no adjunctUrl")
    return "https://static.cninfo.com.cn/" + adjunct


def download_pdf(url: str, destination: Path) -> str:
    temp = destination.with_suffix(destination.suffix + ".part")
    temp.unlink(missing_ok=True)
    response = request(
        "GET", url, stream=True,
        referer="https://www.cninfo.com.cn/",
        timeout=(25, 480),
    )
    try:
        with temp.open("wb") as fh:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    fh.write(chunk)
        final_url = str(response.url)
    finally:
        response.close()
    size = temp.stat().st_size
    head = temp.read_bytes()[:8]
    if size < 50_000 or not head.startswith(b"%PDF-"):
        raise RuntimeError(f"invalid PDF download: {destination.name}, size={size}, head={head!r}")
    temp.replace(destination)
    print("DOWNLOADED", destination, size, final_url, flush=True)
    return final_url


def render_page(path: Path, page_number: int, suffix: str) -> None:
    prefix = RENDER_DIR / f"{path.stem}_{suffix}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
            "-r", "84", "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True, text=True, timeout=300,
    )
    png = Path(str(prefix) + ".png")
    valid = (
        process.returncode == 0 and png.exists() and png.stat().st_size > 1000
        and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(
            f"render failed for {path.name} page {page_number}: "
            f"return={process.returncode}, stderr={process.stderr[-1500:]}"
        )
    png.unlink()


def validate_pdf(path: Path, *, year_token: str, document_type: str, min_pages: int) -> dict[str, Any]:
    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True, text=True, timeout=300,
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {qpdf.stderr[-2500:]}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"page count too small for {path.name}: {pages} < {min_pages}")

    render_page(path, 1, "first")
    if pages > 1:
        render_page(path, pages, "last")

    indices = list(range(min(8, pages)))
    if pages > 8:
        indices.append(pages - 1)
    text = "\n".join((reader.pages[index].extract_text() or "") for index in indices)
    normalized = re.sub(r"\s+", "", text)
    identity_ok = any(token in normalized for token in (COMPANY, FULL_COMPANY, STOCK_CODE))
    year_ok = year_token in normalized
    if text.strip() and not identity_ok:
        raise RuntimeError(f"company identity not found in sampled text: {path.name}")
    if text.strip() and not year_ok:
        raise RuntimeError(f"period token {year_token} not found in sampled text: {path.name}")
    if document_type == "年度报告" and "年度报告摘要" in normalized:
        raise RuntimeError(f"annual report summary detected: {path.name}")

    return {
        "bytes": path.stat().st_size,
        "pages": pages,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "identity_text_verified_when_extractable": identity_ok,
        "period_text_verified_when_extractable": year_ok,
        "render_verified_first_and_last_page": True,
        "sample_text_extractable": bool(text.strip()),
    }


records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()

for year in range(2020, 2026):
    row = choose_annual(year)
    title = clean_title(str(row.get("announcementTitle") or ""))
    suffix = "_更新后" if any(token in title for token in ("更新后", "更正后", "修订版", "修订稿")) else ""
    destination = ANNUAL_DIR / f"{year}_登海种业_年度报告{suffix}.pdf"
    source_url = static_url(row)
    final_url = download_pdf(source_url, destination)
    metadata = validate_pdf(
        destination,
        year_token=str(year),
        document_type="年度报告",
        min_pages=80,
    )
    if metadata["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate report detected: {destination.name}")
    seen_hashes.add(metadata["sha256"])
    records.append({
        "period": str(year),
        "document_type": "年度报告",
        "title": title,
        "publication_date": row_date(row),
        "announcement_id": str(row.get("announcementId") or ""),
        "relative_path": str(destination.relative_to(ROOT)),
        "source": "巨潮资讯网（深交所法定信息披露平台）",
        "source_url": source_url,
        "download_final_url": final_url,
        **metadata,
    })

# As of 2026-10-04, first check whether a 2026 Q3 report has already appeared.
quarter_row = choose_periodic(
    ["2026年第三季度报告", "2026年三季度报告"],
    "2026-10-01", CHECKED_AS_OF,
)
quarter_period = "2026Q3"
quarter_token = "2026"
quarter_title_label = "第三季度报告"
if quarter_row is None:
    quarter_row = choose_periodic(
        ["2026年第一季度报告", "2026年一季度报告"],
        "2026-04-01", "2026-05-31",
    )
    quarter_period = "2026Q1"
    quarter_title_label = "第一季度报告"
if quarter_row is None:
    raise RuntimeError("latest 2026 quarterly report not found")

quarter_title = clean_title(str(quarter_row.get("announcementTitle") or ""))
quarter_destination = QUARTER_DIR / f"{quarter_period}_登海种业_{quarter_title_label}.pdf"
quarter_source_url = static_url(quarter_row)
quarter_final_url = download_pdf(quarter_source_url, quarter_destination)
quarter_metadata = validate_pdf(
    quarter_destination,
    year_token=quarter_token,
    document_type=quarter_title_label,
    min_pages=6,
)
if quarter_metadata["sha256"] in seen_hashes:
    raise RuntimeError(f"duplicate report detected: {quarter_destination.name}")
seen_hashes.add(quarter_metadata["sha256"])
records.append({
    "period": quarter_period,
    "document_type": quarter_title_label,
    "title": quarter_title,
    "publication_date": row_date(quarter_row),
    "announcement_id": str(quarter_row.get("announcementId") or ""),
    "relative_path": str(quarter_destination.relative_to(ROOT)),
    "source": "巨潮资讯网（深交所法定信息披露平台）",
    "source_url": quarter_source_url,
    "download_final_url": quarter_final_url,
    **quarter_metadata,
})

half_row = choose_periodic(
    ["2026年半年度报告"],
    "2026-07-01", "2026-09-30",
)
if half_row is not None:
    half_title = clean_title(str(half_row.get("announcementTitle") or ""))
    half_destination = SUPPLEMENT_DIR / "2026H1_登海种业_半年度报告.pdf"
    half_source_url = static_url(half_row)
    half_final_url = download_pdf(half_source_url, half_destination)
    half_metadata = validate_pdf(
        half_destination,
        year_token="2026",
        document_type="半年度报告",
        min_pages=70,
    )
    if half_metadata["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate report detected: {half_destination.name}")
    seen_hashes.add(half_metadata["sha256"])
    records.append({
        "period": "2026H1",
        "document_type": "半年度报告（补充）",
        "title": half_title,
        "publication_date": row_date(half_row),
        "announcement_id": str(half_row.get("announcementId") or ""),
        "relative_path": str(half_destination.relative_to(ROOT)),
        "source": "巨潮资讯网（深交所法定信息披露平台）",
        "source_url": half_source_url,
        "download_final_url": half_final_url,
        **half_metadata,
    })

manifest = {
    "package_name": PACKAGE,
    "company": FULL_COMPANY,
    "stock_code": STOCK_CODE,
    "checked_as_of": CHECKED_AS_OF,
    "annual_report_count": 6,
    "latest_quarterly_report": quarter_title,
    "supplementary_half_year_report_included": half_row is not None,
    "pdf_count": len(records),
    "selection_notes": [
        "年度报告均为全文版本，排除年度报告摘要。",
        "如同一年度存在更新后、更正后或修订版，优先选择后续版本。",
        "截至2026年10月4日先检索2026年三季度报告；若尚未披露，则以2026年一季度报告作为最新季报。",
        "2026年半年度报告披露时间晚于一季报，作为补充定期报告单独收录，不将其称为季报。",
    ],
    "records": records,
}
(ROOT / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as fh:
    writer = csv.writer(fh)
    writer.writerow([
        "期间", "类型", "标题", "披露日期", "文件", "页数", "字节数",
        "SHA-256", "公告编号", "官方来源网址",
    ])
    for record in records:
        writer.writerow([
            record["period"], record["document_type"], record["title"],
            record["publication_date"], record["relative_path"], record["pages"],
            record["bytes"], record["sha256"], record["announcement_id"],
            record["source_url"],
        ])

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as fh:
    for record in records:
        fh.write(f"{record['sha256']}  {record['relative_path']}\n")

readme_lines = [
    f"{FULL_COMPANY}（{STOCK_CODE}）定期报告文件包",
    "",
    f"核对日期：{CHECKED_AS_OF}",
    "",
    "收录内容：",
    "1. 2020—2025年年度报告全文，共6份；",
    f"2. 最新季报：{quarter_title}，共1份；",
]
if half_row is not None:
    readme_lines.append("3. 2026年半年度报告，共1份，作为披露时间更晚的补充定期报告单独收录。")
readme_lines.extend([
    "",
    "版本口径：",
    "- 年度报告排除摘要版；",
    "- 若存在更新后、更正后或修订版，优先采用后续版本；",
    "- 半年度报告不是季报，已放在补充目录中。",
    "",
    "校验：",
    "- PDF文件头和最低大小检查；",
    "- qpdf结构检查；",
    "- PDF页数、公司身份和报告期间抽样核验；",
    "- 每份PDF首页和末页实际渲染检查；",
    "- SHA-256去重及ZIP完整性测试。",
])
(VERIFY_DIR / "README.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

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
    pdf_count = sum(1 for name in archive.namelist() if name.lower().endswith(".pdf"))
    if pdf_count != len(records):
        raise RuntimeError(f"ZIP PDF count mismatch: expected {len(records)}, got {pdf_count}")

print(
    "FINAL_ZIP", zip_path,
    "bytes", zip_path.stat().st_size,
    "sha256", sha256(zip_path),
    flush=True,
)
print(json.dumps({
    "package_name": PACKAGE,
    "annual_reports": 6,
    "latest_quarterly_report": quarter_title,
    "supplementary_half_year_report_included": half_row is not None,
    "pdf_count": len(records),
    "zip_bytes": zip_path.stat().st_size,
    "zip_sha256": sha256(zip_path),
}, ensure_ascii=False, indent=2), flush=True)
