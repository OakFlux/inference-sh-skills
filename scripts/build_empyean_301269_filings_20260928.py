from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-09-28"
ISSUER = "北京华大九天科技股份有限公司"
SHORT_NAME = "华大九天"
STOCK_CODE = "301269"
PACKAGE = "华大九天_301269_全部年报_招股说明书_2026最新季报"
ROOT = Path(PACKAGE)
ANNUAL_DIR = ROOT / "01_年度报告"
IPO_DIR = ROOT / "02_招股说明书"
LATEST_DIR = ROOT / "03_最新季报及补充定期报告"
VERIFY_DIR = ROOT / "04_来源与校验"
WORK_DIR = Path("_empyean_301269_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (ANNUAL_DIR, IPO_DIR, LATEST_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

CNINFO_QUERY = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STOCK_LIST = "https://www.cninfo.com.cn/new/data/szse_stock.json"
SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/json,text/html,application/pdf,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_title(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value or "")
    return re.sub(r"\s+", "", value).replace("：", ":")


def http(
    method: str,
    url: str,
    *,
    data: dict[str, Any] | None = None,
    stream: bool = False,
    timeout: tuple[int, int] = (20, 360),
) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        headers = dict(HEADERS)
        if method.upper() == "POST":
            headers.update(
                {
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Origin": "https://www.cninfo.com.cn",
                    "Referer": f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={STOCK_CODE}",
                    "X-Requested-With": "XMLHttpRequest",
                }
            )
        else:
            headers["Referer"] = "https://www.cninfo.com.cn/"
        try:
            response = SESSION.request(
                method.upper(),
                url,
                data=data,
                headers=headers,
                stream=stream,
                timeout=timeout,
                allow_redirects=True,
            )
            print(
                "HTTP",
                method.upper(),
                url,
                "attempt",
                attempt,
                "status",
                response.status_code,
                "type",
                response.headers.get("content-type"),
                "length",
                response.headers.get("content-length"),
                "final",
                response.url,
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"request failed for {url}: {errors[-6:]}")


def get_org_id() -> str:
    response = http("GET", CNINFO_STOCK_LIST, timeout=(20, 120))
    try:
        payload = response.json()
    finally:
        response.close()
    for row in payload.get("stockList", []):
        if str(row.get("code")) == STOCK_CODE:
            org_id = row.get("orgId") or row.get("orgid")
            if org_id:
                print("CNINFO_ORG_ID", org_id, row.get("zwjc"), flush=True)
                return str(org_id)
    raise RuntimeError(f"CNINFO orgId not found for {STOCK_CODE}")


ORG_ID = get_org_id()


def query_announcements(
    search_key: str,
    category: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page_num in range(1, 20):
        form = {
            "pageNum": str(page_num),
            "pageSize": "30",
            "column": "szse",
            "tabName": "fulltext",
            "plate": "sz",
            "stock": f"{STOCK_CODE},{ORG_ID}",
            "searchkey": search_key,
            "secid": "",
            "category": category,
            "trade": "",
            "seDate": f"{start_date}~{end_date}",
            "sortName": "time",
            "sortType": "desc",
            "isHLtitle": "false",
        }
        response = http("POST", CNINFO_QUERY, data=form, timeout=(20, 120))
        try:
            payload = response.json()
        finally:
            response.close()
        announcements = payload.get("announcements") or []
        for raw in announcements:
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
                datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                if timestamp
                else ""
            )
            item = {
                "title": title,
                "url": url,
                "announcement_time": timestamp,
                "published_date": published,
                "announcement_id": raw.get("announcementId"),
            }
            results.append(item)
            print("ANNOUNCEMENT", json.dumps(item, ensure_ascii=False), flush=True)
        total_pages = int(payload.get("totalpages") or payload.get("totalPages") or 0)
        if not announcements or (total_pages and page_num >= total_pages) or len(announcements) < 30:
            break
    return results


def choose_latest(
    items: list[dict[str, Any]],
    predicate: Callable[[str], bool],
    label: str,
) -> dict[str, Any]:
    matches = [item for item in items if predicate(item["title"])]
    if not matches:
        raise RuntimeError(f"No matching CNINFO document found for {label}")
    matches.sort(key=lambda item: (item["announcement_time"], item["title"]), reverse=True)
    chosen = matches[0]
    print("CHOSEN", label, json.dumps(chosen, ensure_ascii=False), flush=True)
    return chosen


def download_pdf(url: str, destination: Path) -> str:
    response = http("GET", url, stream=True, timeout=(25, 900))
    temp = destination.with_suffix(destination.suffix + ".part")
    temp.unlink(missing_ok=True)
    try:
        with temp.open("wb") as handle:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    handle.write(chunk)
        final_url = str(response.url)
    finally:
        response.close()
    size = temp.stat().st_size
    head = temp.read_bytes()[:8]
    if size < 40_000 or not head.startswith(b"%PDF-"):
        raise RuntimeError(f"invalid PDF for {destination.name}: bytes={size}, head={head!r}")
    temp.replace(destination)
    print("DOWNLOADED", destination, size, final_url, flush=True)
    return final_url


def render_page(path: Path, page_number: int, tag: str) -> None:
    prefix = RENDER_DIR / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{tag}"
    process = subprocess.run(
        [
            "pdftoppm",
            "-f",
            str(page_number),
            "-l",
            str(page_number),
            "-r",
            "84",
            "-png",
            "-singlefile",
            str(path),
            str(prefix),
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
            f"render validation failed for {path.name} page {page_number}: {process.stderr[-1500:]}"
        )
    image.unlink()


def validate_pdf(
    path: Path,
    *,
    doc_type: str,
    year: int | None,
    min_pages: int,
) -> dict[str, Any]:
    check = subprocess.run(
        ["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=600
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

    sample_indices = list(range(min(12, pages)))
    if pages > 12:
        sample_indices.append(pages - 1)
    sample = "\n".join((reader.pages[index].extract_text() or "") for index in sample_indices)
    normalized = re.sub(r"\s+", "", sample)
    identity_ok = SHORT_NAME in normalized or ISSUER in normalized
    if sample.strip() and not identity_ok:
        raise RuntimeError(f"issuer identity not found in sampled text for {path.name}")
    if year is not None and sample.strip() and str(year) not in normalized:
        raise RuntimeError(f"year {year} not found in sampled text for {path.name}")

    first_text = "\n".join((reader.pages[index].extract_text() or "") for index in range(min(10, pages)))
    first_normalized = re.sub(r"\s+", "", first_text)
    if doc_type == "年度报告":
        if "年度报告摘要" in first_normalized:
            raise RuntimeError(f"annual report summary detected: {path.name}")
        if first_text.strip() and "年度报告" not in first_normalized:
            raise RuntimeError(f"annual report title not found: {path.name}")
    elif doc_type == "招股说明书" and first_text.strip():
        if "招股说明书" not in first_normalized and "招股意向书" not in first_normalized:
            raise RuntimeError(f"prospectus title not found: {path.name}")
    elif doc_type == "季度报告" and first_text.strip() and "季度报告" not in first_normalized:
        raise RuntimeError(f"quarterly report title not found: {path.name}")
    elif doc_type == "半年度报告" and first_text.strip() and "半年度报告" not in first_normalized:
        raise RuntimeError(f"half-year report title not found: {path.name}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "render_verified_first_and_last_page": True,
        "issuer_identity_verified_when_text_extractable": identity_ok,
        "sample_text_extractable": bool(sample.strip()),
    }


annual_announcements = query_announcements(
    "年度报告", "category_ndbg_szsh;", "2022-01-01", CHECKED_AS_OF
)
annual_by_year: dict[int, dict[str, Any]] = {}
for item in annual_announcements:
    title = item["title"]
    match = re.search(r"(20\d{2})年年度报告", title)
    if not match or any(term in title for term in ("摘要", "英文", "取消", "提示性公告")):
        continue
    year = int(match.group(1))
    current = annual_by_year.get(year)
    if current is None or item["announcement_time"] > current["announcement_time"]:
        annual_by_year[year] = item

required_years = {2022, 2023, 2024, 2025}
missing_years = sorted(required_years - set(annual_by_year))
if missing_years:
    raise RuntimeError(
        f"missing expected annual reports: {missing_years}; found={sorted(annual_by_year)}"
    )

prospectus_announcements = query_announcements(
    "招股说明书", "", "2021-01-01", "2022-12-31"
)
prospectus = choose_latest(
    prospectus_announcements,
    lambda title: "招股说明书" in title
    and not any(
        term in title
        for term in (
            "提示性公告",
            "摘要",
            "附录",
            "注册稿",
            "申报稿",
            "上会稿",
            "问询",
            "回复",
            "保荐书",
            "法律意见",
        )
    ),
    "首次公开发行最终招股说明书",
)

quarter_announcements = query_announcements(
    "", "category_yjdbg_szsh;", "2026-01-01", CHECKED_AS_OF
)
quarter = choose_latest(
    quarter_announcements,
    lambda title: bool(re.search(r"2026年(?:第一|第三)季度报告", title))
    and "摘要" not in title,
    "截至核对日最新季度报告",
)
quarter_match = re.search(r"(2026年(?:第一|第三)季度报告)", quarter["title"])
quarter_label = quarter_match.group(1) if quarter_match else "2026年最新季度报告"

half_announcements = query_announcements(
    "半年度报告", "category_bndbg_szsh;", "2026-01-01", CHECKED_AS_OF
)
half = choose_latest(
    half_announcements,
    lambda title: "2026年半年度报告" in title
    and not any(term in title for term in ("摘要", "英文")),
    "2026年半年度报告",
)

records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()

for year in sorted(required_years):
    item = annual_by_year[year]
    destination = ANNUAL_DIR / f"{year}_华大九天_年度报告全文.pdf"
    final_url = download_pdf(item["url"], destination)
    metadata = validate_pdf(destination, doc_type="年度报告", year=year, min_pages=100)
    if metadata["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate document detected: {destination.name}")
    seen_hashes.add(metadata["sha256"])
    records.append(
        {
            "label": f"{year}年年度报告",
            "document_type": "年度报告",
            "fiscal_year": year,
            "relative_path": str(destination.relative_to(ROOT)),
            "title_on_cninfo": item["title"],
            "published_date": item["published_date"],
            "source": "巨潮资讯网（官方信息披露平台）",
            "source_url": final_url,
            **metadata,
        }
    )

prospectus_destination = IPO_DIR / "华大九天_首次公开发行股票并在创业板上市_招股说明书.pdf"
prospectus_url = download_pdf(prospectus["url"], prospectus_destination)
prospectus_metadata = validate_pdf(
    prospectus_destination, doc_type="招股说明书", year=None, min_pages=250
)
if prospectus_metadata["sha256"] in seen_hashes:
    raise RuntimeError(f"duplicate document detected: {prospectus_destination.name}")
seen_hashes.add(prospectus_metadata["sha256"])
records.append(
    {
        "label": "首次公开发行股票并在创业板上市招股说明书",
        "document_type": "招股说明书",
        "relative_path": str(prospectus_destination.relative_to(ROOT)),
        "title_on_cninfo": prospectus["title"],
        "published_date": prospectus["published_date"],
        "source": "巨潮资讯网（官方信息披露平台）",
        "source_url": prospectus_url,
        **prospectus_metadata,
    }
)

quarter_destination = LATEST_DIR / f"华大九天_{quarter_label}.pdf"
quarter_url = download_pdf(quarter["url"], quarter_destination)
quarter_metadata = validate_pdf(
    quarter_destination, doc_type="季度报告", year=2026, min_pages=8
)
if quarter_metadata["sha256"] in seen_hashes:
    raise RuntimeError(f"duplicate document detected: {quarter_destination.name}")
seen_hashes.add(quarter_metadata["sha256"])
records.append(
    {
        "label": quarter_label,
        "document_type": "季度报告",
        "relative_path": str(quarter_destination.relative_to(ROOT)),
        "title_on_cninfo": quarter["title"],
        "published_date": quarter["published_date"],
        "source": "巨潮资讯网（官方信息披露平台）",
        "source_url": quarter_url,
        **quarter_metadata,
    }
)

half_destination = LATEST_DIR / "补充_华大九天_2026年半年度报告.pdf"
half_url = download_pdf(half["url"], half_destination)
half_metadata = validate_pdf(
    half_destination, doc_type="半年度报告", year=2026, min_pages=80
)
if half_metadata["sha256"] in seen_hashes:
    raise RuntimeError(f"duplicate document detected: {half_destination.name}")
seen_hashes.add(half_metadata["sha256"])
records.append(
    {
        "label": "2026年半年度报告（补充：比一季报更新的完整定期报告）",
        "document_type": "半年度报告",
        "relative_path": str(half_destination.relative_to(ROOT)),
        "title_on_cninfo": half["title"],
        "published_date": half["published_date"],
        "source": "巨潮资讯网（官方信息披露平台）",
        "source_url": half_url,
        **half_metadata,
    }
)

readme_lines = [
    f"{ISSUER}（{STOCK_CODE}.SZ）公开披露文件资料包",
    f"核对日期：{CHECKED_AS_OF}",
    "",
    "收录口径：",
    "1. 公司2022年上市后全部年度报告：2022、2023、2024、2025年。",
    "2. 首次公开发行股票并在创业板上市招股说明书。",
    f"3. 截至核对日最新季度报告：{quarter_label}。",
    "4. 另附2026年半年度报告；它比一季报更新，但属于半年度报告，不属于法定季度报告。",
    "",
    "所有PDF均从巨潮资讯网公开披露地址下载，仅统一目录和文件名，不改写PDF正文、页面顺序或内容。",
    "",
    "文件清单：",
]
for index, record in enumerate(records, start=1):
    readme_lines.extend(
        [
            f"{index}. {record['label']}",
            f"   文件：{record['relative_path']}",
            f"   巨潮标题：{record['title_on_cninfo']}",
            f"   披露日期：{record['published_date']}",
            f"   页数：{record['pages']}",
            f"   大小：{record['bytes']} bytes",
            f"   SHA-256：{record['sha256']}",
            f"   来源：{record['source_url']}",
            "",
        ]
    )

(VERIFY_DIR / "README_文件清单与来源说明.txt").write_text(
    "\n".join(readme_lines), encoding="utf-8"
)
(VERIFY_DIR / "manifest.json").write_text(
    json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
)
checksum_lines = [f"{record['sha256']}  {record['relative_path']}" for record in records]
(VERIFY_DIR / "SHA256SUMS.txt").write_text(
    "\n".join(checksum_lines) + "\n", encoding="utf-8"
)

final_zip = Path(PACKAGE + ".zip")
final_zip.unlink(missing_ok=True)
with zipfile.ZipFile(final_zip, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, path.as_posix())
with zipfile.ZipFile(final_zip, "r") as archive:
    bad = archive.testzip()
    if bad is not None:
        raise RuntimeError(f"ZIP integrity test failed at {bad}")

print("FINAL_ZIP", final_zip, final_zip.stat().st_size, flush=True)
print("MANIFEST", json.dumps(records, ensure_ascii=False, indent=2), flush=True)
