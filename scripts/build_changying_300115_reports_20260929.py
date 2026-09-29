from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-09-29"
STOCK_CODE = "300115"
SHORT_NAME = "长盈精密"
ISSUER = "深圳市长盈精密技术股份有限公司"
PACKAGE = "长盈精密_300115_2020-2025年报及2026年最新季报"
ROOT = Path(PACKAGE)
ANNUAL_DIR = ROOT / "01_年度报告"
QUARTER_DIR = ROOT / "02_最新季报"
VERIFY_DIR = ROOT / "03_说明与校验"
WORK_DIR = Path("_changying_300115_work")
RENDER_DIR = WORK_DIR / "renders"
ZIP_PATH = Path(PACKAGE + ".zip")

for directory in (ANNUAL_DIR, QUARTER_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

CNINFO_QUERY = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STOCK_LIST = "https://www.cninfo.com.cn/new/data/szse_stock.json"
CNINFO_TOP_SEARCH = "https://www.cninfo.com.cn/new/information/topSearch/query"
SESSION = requests.Session()
SESSION.trust_env = False
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/json,text/plain,text/html,application/pdf,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
BEIJING = timezone(timedelta(hours=8))


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
            stream: bool = False, timeout: tuple[int, int] = (20, 360)) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        headers = dict(BASE_HEADERS)
        if method.upper() == "POST":
            headers.update({
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": "https://www.cninfo.com.cn",
                "Referer": f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={STOCK_CODE}",
                "X-Requested-With": "XMLHttpRequest",
            })
        else:
            headers["Referer"] = "https://www.cninfo.com.cn/"
        try:
            response = SESSION.request(
                method.upper(), url, data=data, headers=headers, stream=stream,
                timeout=timeout, allow_redirects=True,
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
            time.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"request failed for {url}: {errors[-6:]}")


def get_org_id() -> str | None:
    try:
        response = request("GET", CNINFO_STOCK_LIST, timeout=(20, 120))
        try:
            payload = response.json()
        finally:
            response.close()
        rows = payload.get("stockList", []) if isinstance(payload, dict) else []
        for row in rows:
            if str(row.get("code") or row.get("secCode") or "") == STOCK_CODE:
                org_id = row.get("orgId") or row.get("orgid")
                if org_id:
                    print("CNINFO_ORG_ID_FROM_LIST", org_id, row.get("zwjc"), flush=True)
                    return str(org_id)
    except Exception as exc:  # noqa: BLE001
        print("ORG_ID_LIST_LOOKUP_FAILED", repr(exc), flush=True)

    try:
        response = request(
            "POST", CNINFO_TOP_SEARCH,
            data={"keyWord": STOCK_CODE, "maxNum": "10"},
            timeout=(20, 120),
        )
        try:
            payload = response.json()
        finally:
            response.close()
        rows = payload if isinstance(payload, list) else payload.get("stockList", [])
        for row in rows:
            sec_code = str(row.get("secCode") or row.get("stockCode") or row.get("code") or "")
            if STOCK_CODE in sec_code or str(row.get("zwjc") or "") == SHORT_NAME:
                org_id = row.get("orgId") or row.get("orgid") or row.get("code")
                if org_id and str(org_id) != STOCK_CODE:
                    print("CNINFO_ORG_ID_FROM_SEARCH", org_id, row, flush=True)
                    return str(org_id)
    except Exception as exc:  # noqa: BLE001
        print("ORG_ID_TOP_SEARCH_FAILED", repr(exc), flush=True)

    return None


ORG_ID = get_org_id()


def query_announcements(category: str, start_date: str, end_date: str,
                        search_key: str = "") -> list[dict[str, Any]]:
    stock_candidates = [f"{STOCK_CODE},{ORG_ID}"] if ORG_ID else []
    stock_candidates.extend([STOCK_CODE, ""])
    last_results: list[dict[str, Any]] = []

    for stock_param in stock_candidates:
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for page_num in range(1, 20):
            form = {
                "pageNum": str(page_num),
                "pageSize": "30",
                "column": "szse",
                "tabName": "fulltext",
                "plate": "sz",
                "stock": stock_param,
                "searchkey": search_key,
                "secid": "",
                "category": category,
                "trade": "",
                "seDate": f"{start_date}~{end_date}",
                "sortName": "time",
                "sortType": "desc",
                "isHLtitle": "false",
            }
            response = request("POST", CNINFO_QUERY, data=form, timeout=(20, 150))
            try:
                payload = response.json()
            finally:
                response.close()

            announcements = payload.get("announcements") or []
            for raw in announcements:
                if stock_param == "" and str(raw.get("secCode") or "") != STOCK_CODE:
                    continue
                adjunct = str(raw.get("adjunctUrl") or "").lstrip("/")
                if not adjunct:
                    continue
                url = "https://static.cninfo.com.cn/" + adjunct
                if url in seen:
                    continue
                seen.add(url)
                title = clean_title(str(raw.get("announcementTitle") or ""))
                timestamp = int(raw.get("announcementTime") or 0)
                published = (
                    datetime.fromtimestamp(timestamp / 1000, tz=BEIJING).strftime("%Y-%m-%d")
                    if timestamp else ""
                )
                item = {
                    "title": title,
                    "url": url,
                    "announcement_time": timestamp,
                    "published_date": published,
                    "announcement_id": raw.get("announcementId"),
                    "sec_code": raw.get("secCode"),
                    "sec_name": raw.get("secName"),
                }
                results.append(item)
                print("ANNOUNCEMENT", json.dumps(item, ensure_ascii=False), flush=True)

            total_pages = int(payload.get("totalpages") or payload.get("totalPages") or 0)
            if not announcements or (total_pages and page_num >= total_pages) or len(announcements) < 30:
                break

        if results:
            return results
        last_results = results
    return last_results


def download_pdf(url: str, destination: Path, min_bytes: int) -> str:
    response = request("GET", url, stream=True, timeout=(25, 600))
    temp = destination.with_suffix(destination.suffix + ".part")
    temp.unlink(missing_ok=True)
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
    if size < min_bytes or not head.startswith(b"%PDF-"):
        raise RuntimeError(
            f"invalid PDF for {destination.name}: bytes={size}, head={head!r}, url={url}"
        )
    temp.replace(destination)
    print("DOWNLOADED", destination, size, final_url, flush=True)
    return final_url


def render_page(path: Path, page_number: int, tag: str) -> None:
    prefix = RENDER_DIR / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{tag}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
            "-r", "84", "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    image = Path(str(prefix) + ".png")
    valid = (
        process.returncode == 0
        and image.exists()
        and image.stat().st_size > 1000
        and image.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(
            f"render validation failed for {path.name} page {page_number}: "
            f"{process.stderr[-1500:]}"
        )
    image.unlink()


def validate_pdf(path: Path, *, fiscal_year: int, doc_type: str,
                 min_pages: int) -> dict[str, Any]:
    check = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-2500:]}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"unexpectedly short {path.name}: {pages} pages, expected >= {min_pages}")

    render_page(path, 1, "first")
    if pages > 1:
        render_page(path, pages, "last")

    indices = list(range(min(12, pages)))
    if pages > 12:
        indices.append(pages - 1)
    sample = "\n".join((reader.pages[index].extract_text() or "") for index in indices)
    normalized = re.sub(r"\s+", "", sample)
    identity_ok = SHORT_NAME in normalized or ISSUER in normalized
    if sample.strip() and not identity_ok:
        raise RuntimeError(f"issuer identity not found in sampled text for {path.name}")
    if sample.strip() and str(fiscal_year) not in normalized:
        raise RuntimeError(f"fiscal year {fiscal_year} not found in sampled text for {path.name}")

    first_text = "\n".join((reader.pages[index].extract_text() or "") for index in range(min(8, pages)))
    first_normalized = re.sub(r"\s+", "", first_text)
    if doc_type == "年度报告":
        if "年度报告摘要" in first_normalized:
            raise RuntimeError(f"annual report summary detected: {path.name}")
        if first_text.strip() and "年度报告" not in first_normalized:
            raise RuntimeError(f"annual report title not found: {path.name}")
    elif doc_type == "季度报告":
        if first_text.strip() and "季度报告" not in first_normalized:
            raise RuntimeError(f"quarterly report title not found: {path.name}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "render_verified_first_and_last_page": True,
        "issuer_identity_verified_when_text_extractable": identity_ok,
        "sample_text_extractable": bool(sample.strip()),
    }


def choose_annual(items: list[dict[str, Any]], year: int) -> dict[str, Any]:
    matches = []
    for item in items:
        title = item["title"]
        if f"{year}年年度报告" not in title:
            continue
        if any(term in title for term in ("摘要", "英文", "取消", "提示性公告")):
            continue
        matches.append(item)
    if not matches:
        raise RuntimeError(f"No full annual report found for fiscal year {year}")
    matches.sort(key=lambda item: (item["announcement_time"], item["title"]), reverse=True)
    chosen = matches[0]
    print("CHOSEN_ANNUAL", year, json.dumps(chosen, ensure_ascii=False), flush=True)
    return chosen


def choose_latest_quarter(items: list[dict[str, Any]]) -> dict[str, Any]:
    matches = []
    for item in items:
        title = item["title"]
        if not re.search(r"2026年(?:第一|第三)季度报告", title):
            continue
        if any(term in title for term in ("摘要", "英文", "取消", "提示性公告")):
            continue
        matches.append(item)
    if not matches:
        raise RuntimeError("No 2026 first- or third-quarter report found")
    matches.sort(key=lambda item: (item["announcement_time"], item["title"]), reverse=True)
    chosen = matches[0]
    print("CHOSEN_QUARTER", json.dumps(chosen, ensure_ascii=False), flush=True)
    return chosen


annual_items = query_announcements(
    "category_ndbg_szsh;", "2021-01-01", CHECKED_AS_OF, "年度报告"
)
annual_by_year = {year: choose_annual(annual_items, year) for year in range(2020, 2026)}

q1_items = query_announcements(
    "category_yjdbg_szsh;", "2026-01-01", CHECKED_AS_OF, ""
)
q3_items = query_announcements(
    "category_sjdbg_szsh;", "2026-01-01", CHECKED_AS_OF, ""
)
quarter = choose_latest_quarter(q1_items + q3_items)
quarter_match = re.search(r"2026年(第一|第三)季度报告", quarter["title"])
quarter_name = quarter_match.group(1) if quarter_match else "最新"
quarter_code = "Q1" if quarter_name == "第一" else "Q3" if quarter_name == "第三" else "LATEST"

records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()

for year in range(2020, 2026):
    item = annual_by_year[year]
    destination = ANNUAL_DIR / f"{year}_长盈精密_年度报告全文.pdf"
    final_url = download_pdf(item["url"], destination, min_bytes=100_000)
    metadata = validate_pdf(destination, fiscal_year=year, doc_type="年度报告", min_pages=80)
    if metadata["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate document detected: {destination.name}")
    seen_hashes.add(metadata["sha256"])
    records.append({
        "label": f"{year}年年度报告",
        "document_type": "年度报告",
        "fiscal_year": year,
        "relative_path": str(destination.relative_to(ROOT)),
        "title_on_cninfo": item["title"],
        "published_date": item["published_date"],
        "source": "巨潮资讯网（官方信息披露平台）",
        "source_url": final_url,
        **metadata,
    })

quarter_destination = QUARTER_DIR / f"2026_{quarter_code}_长盈精密_{quarter_name}季度报告.pdf"
quarter_url = download_pdf(quarter["url"], quarter_destination, min_bytes=10_000)
quarter_metadata = validate_pdf(
    quarter_destination, fiscal_year=2026, doc_type="季度报告", min_pages=5
)
if quarter_metadata["sha256"] in seen_hashes:
    raise RuntimeError(f"duplicate document detected: {quarter_destination.name}")
seen_hashes.add(quarter_metadata["sha256"])
records.append({
    "label": f"2026年{quarter_name}季度报告",
    "document_type": "季度报告",
    "fiscal_year": 2026,
    "relative_path": str(quarter_destination.relative_to(ROOT)),
    "title_on_cninfo": quarter["title"],
    "published_date": quarter["published_date"],
    "source": "巨潮资讯网（官方信息披露平台）",
    "source_url": quarter_url,
    **quarter_metadata,
})

manifest_json = VERIFY_DIR / "manifest.json"
manifest_json.write_text(
    json.dumps(
        {
            "issuer": ISSUER,
            "short_name": SHORT_NAME,
            "stock_code": STOCK_CODE,
            "checked_as_of": CHECKED_AS_OF,
            "document_count": len(records),
            "documents": records,
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)

fieldnames = [
    "label", "document_type", "fiscal_year", "relative_path", "title_on_cninfo",
    "published_date", "source", "source_url", "pages", "bytes", "sha256",
    "qpdf_return_code", "render_verified_first_and_last_page",
    "issuer_identity_verified_when_text_extractable", "sample_text_extractable",
]
with (VERIFY_DIR / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(records)

(VERIFY_DIR / "SHA256SUMS.txt").write_text(
    "\n".join(f"{row['sha256']}  {row['relative_path']}" for row in records) + "\n",
    encoding="utf-8",
)

readme_lines = [
    f"{ISSUER}（{STOCK_CODE}）定期报告压缩包",
    "",
    f"核对日期：{CHECKED_AS_OF}",
    "来源：巨潮资讯网（上市公司官方信息披露平台）",
    "",
    "本压缩包包含：",
    "- 2020—2025年度报告全文，共6份；",
    f"- 截至核对日最新季度报告：2026年{quarter_name}季度报告，共1份。",
    "",
    "说明：2022年度报告采用巨潮资讯网披露时间最晚的更新版本（如存在更新/更正版本）。",
    "每份PDF均完成文件头、页数、qpdf结构检查，并渲染首尾页验证可读性。",
    "详细来源链接、页数、文件大小和SHA-256见manifest.csv、manifest.json及SHA256SUMS.txt。",
    "",
    "文件清单：",
]
for row in records:
    readme_lines.append(
        f"- {row['label']}｜{row['relative_path']}｜{row['pages']}页｜披露日{row['published_date']}"
    )
(VERIFY_DIR / "README.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

if ZIP_PATH.exists():
    ZIP_PATH.unlink()
with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, arcname=str(path))

if not ZIP_PATH.exists() or ZIP_PATH.stat().st_size < 500_000:
    raise RuntimeError(f"ZIP creation failed or unexpectedly small: {ZIP_PATH}")

with zipfile.ZipFile(ZIP_PATH, "r") as archive:
    bad = archive.testzip()
    if bad:
        raise RuntimeError(f"ZIP integrity failure at {bad}")

print("FINAL_ZIP", ZIP_PATH, ZIP_PATH.stat().st_size, flush=True)
print("DOCUMENT_COUNT", len(records), flush=True)
