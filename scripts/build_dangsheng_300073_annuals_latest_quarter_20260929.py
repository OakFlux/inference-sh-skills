from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-09-29"
ISSUER = "北京当升材料科技股份有限公司"
SHORT_NAME = "当升科技"
STOCK_CODE = "300073"
PACKAGE = "当升科技_300073_2020-2025年报及2026年第一季度报告"
ROOT = Path(PACKAGE)
ANNUAL_DIR = ROOT / "01_年度报告"
QUARTER_DIR = ROOT / "02_最新季度报告"
VERIFY_DIR = ROOT / "03_来源与校验"
WORK_DIR = Path("_dangsheng_300073_annuals_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (ANNUAL_DIR, QUARTER_DIR, VERIFY_DIR, RENDER_DIR):
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
CHINA_TZ = timezone(timedelta(hours=8))


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
                datetime.fromtimestamp(timestamp / 1000, tz=CHINA_TZ).strftime("%Y-%m-%d")
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
    year: int,
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
    identity_ok = SHORT_NAME in normalized or ISSUER in normalized or STOCK_CODE in normalized
    if sample.strip() and not identity_ok:
        raise RuntimeError(f"issuer identity not found in sampled text for {path.name}")
    if sample.strip() and str(year) not in normalized:
        raise RuntimeError(f"year {year} not found in sampled text for {path.name}")

    first_text = "\n".join((reader.pages[index].extract_text() or "") for index in range(min(10, pages)))
    first_normalized = re.sub(r"\s+", "", first_text)
    if doc_type == "年度报告":
        if "年度报告摘要" in first_normalized:
            raise RuntimeError(f"annual report summary detected: {path.name}")
        if first_text.strip() and "年度报告" not in first_normalized:
            raise RuntimeError(f"annual report title not found: {path.name}")
    elif doc_type == "季度报告":
        if first_text.strip() and not any(
            token in first_normalized for token in ("第一季度报告", "一季度报告", "第三季度报告", "三季度报告")
        ):
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


def main() -> None:
    annual_announcements = query_announcements(
        "年度报告", "category_ndbg_szsh;", "2020-01-01", CHECKED_AS_OF
    )
    annual_by_year: dict[int, dict[str, Any]] = {}
    for item in annual_announcements:
        title = item["title"]
        match = re.search(r"(20\d{2})年年度报告", title)
        if not match or any(term in title for term in ("摘要", "英文", "取消", "提示性公告")):
            continue
        year = int(match.group(1))
        if year not in range(2020, 2026):
            continue
        current = annual_by_year.get(year)
        if current is None or item["announcement_time"] > current["announcement_time"]:
            annual_by_year[year] = item

    required_years = set(range(2020, 2026))
    missing_years = sorted(required_years - set(annual_by_year))
    if missing_years:
        raise RuntimeError(
            f"missing expected annual reports: {missing_years}; found={sorted(annual_by_year)}"
        )

    quarter_announcements = query_announcements(
        "", "category_yjdbg_szsh;", "2026-01-01", CHECKED_AS_OF
    )
    quarter = choose_latest(
        quarter_announcements,
        lambda title: bool(
            re.search(r"2026年(?:第一季度|一季度|第三季度|三季度)报告", title)
        )
        and "摘要" not in title,
        "截至核对日最新季度报告",
    )
    quarter_match = re.search(
        r"2026年(?:第一季度|一季度|第三季度|三季度)报告", quarter["title"]
    )
    quarter_label = quarter_match.group(0) if quarter_match else "2026年最新季度报告"

    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    for year in sorted(required_years):
        item = annual_by_year[year]
        suffix = "_修订版" if any(token in item["title"] for token in ("修订", "更新", "更正")) else ""
        destination = ANNUAL_DIR / f"{year}_当升科技_年度报告全文{suffix}.pdf"
        final_url = download_pdf(item["url"], destination)
        metadata = validate_pdf(destination, doc_type="年度报告", year=year, min_pages=80)
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

    quarter_destination = QUARTER_DIR / f"{quarter_label}_当升科技.pdf"
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
            "fiscal_year": 2026,
            "relative_path": str(quarter_destination.relative_to(ROOT)),
            "title_on_cninfo": quarter["title"],
            "published_date": quarter["published_date"],
            "source": "巨潮资讯网（官方信息披露平台）",
            "source_url": quarter_url,
            **quarter_metadata,
        }
    )

    readme_lines = [
        f"{ISSUER}（{STOCK_CODE}）公开披露文件资料包",
        f"核对日期：{CHECKED_AS_OF}",
        "",
        "收录范围：",
        "1. 2020年至2025年完整年度报告，共6份。",
        f"2. 截至核对日最新法定季度报告：{quarter_label}。",
        "",
        "口径说明：2026年半年度报告虽披露时间晚于一季报，但属于半年度报告，不属于季度报告，故未收入本包。",
        "文件均来自巨潮资讯网公开披露PDF，仅统一文件名与目录，不改写PDF正文或页面顺序。",
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
    readme_lines.extend(
        [
            "校验情况：",
            "- 所有PDF均通过文件头与QPDF结构检查。",
            "- 核对公司名称、证券代码、年度或季度标题。",
            "- 所有PDF均完成首页和末页渲染检查。",
            "- ZIP生成后已执行完整性测试。",
        ]
    )

    (VERIFY_DIR / "README_文件清单与来源说明.txt").write_text(
        "\n".join(readme_lines), encoding="utf-8"
    )
    (VERIFY_DIR / "manifest.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    checksum_lines = [
        f"{record['sha256']}  {record['relative_path']}" for record in records
    ]
    (VERIFY_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8"
    )

    final_zip = Path(PACKAGE + ".zip")
    final_zip.unlink(missing_ok=True)
    with zipfile.ZipFile(
        final_zip, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
    ) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.as_posix())
    with zipfile.ZipFile(final_zip, "r") as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP integrity test failed at {bad}")
    print("FINAL_ZIP", final_zip, final_zip.stat().st_size, flush=True)
    print("MANIFEST", json.dumps(records, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
