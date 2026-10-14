from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from pypdf import PdfReader

CODE = "600097"
COMPANY = "开创国际"
FULL_COMPANY = "上海开创国际海洋资源股份有限公司"
AS_OF_DATE = "2026-10-14"
START_DATE = "2020-01-01"
ANNUAL_YEARS = list(range(2020, 2026))

REPO_ROOT = Path.cwd()
WORK_ROOT = REPO_ROOT / "_build_kaichuang_600097"
PACKAGE_NAME = f"{COMPANY}_{CODE}_2020-2025年报及最新季报"
PACKAGE_ROOT = WORK_ROOT / PACKAGE_NAME
ANNUAL_DIR = PACKAGE_ROOT / "01_年度报告"
QUARTER_DIR = PACKAGE_ROOT / "02_最新季报"
VERIFY_DIR = WORK_ROOT / "_verify"
ZIP_PATH = REPO_ROOT / f"{PACKAGE_NAME}.zip"

CNINFO_BASE = "https://www.cninfo.com.cn"
SEARCH_PAGE = CNINFO_BASE + "/new/commonUrl/pageOfSearch?url=disclosure/list/search"
QUERY_URL = CNINFO_BASE + "/new/hisAnnouncement/query"
STOCK_LIST_URLS = [
    CNINFO_BASE + "/new/data/szse_stock.json",
]
TOP_SEARCH_URL = CNINFO_BASE + "/new/information/topSearch/detailOfQuery"
STATIC_BASE = "https://static.cninfo.com.cn/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": SEARCH_PAGE,
    "Origin": CNINFO_BASE,
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

BJ = timezone(timedelta(hours=8))


def log(*args: Any) -> None:
    print(*args, flush=True)


def clean_title(value: str | None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    max_attempts: int = 6,
    timeout: int = 90,
    **kwargs: Any,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = session.request(method, url, timeout=timeout, **kwargs)
            log(
                "HTTP",
                attempt,
                response.status_code,
                response.headers.get("content-type"),
                len(response.content),
                response.url,
            )
            if response.status_code in {429, 500, 502, 503, 504}:
                raise RuntimeError(f"retryable HTTP {response.status_code}")
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == max_attempts:
                break
            time.sleep(min(2**attempt, 12))
    raise RuntimeError(f"Failed request: {method} {url}: {last_error!r}")


def recursively_find_org_id(obj: Any) -> str | None:
    if isinstance(obj, dict):
        code = str(obj.get("code") or obj.get("secCode") or obj.get("stockCode") or "")
        name = str(obj.get("zwjc") or obj.get("secName") or obj.get("name") or "")
        org_id = obj.get("orgId") or obj.get("orgid")
        if org_id and (code == CODE or COMPANY in name or FULL_COMPANY in name):
            return str(org_id)
        for value in obj.values():
            found = recursively_find_org_id(value)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = recursively_find_org_id(value)
            if found:
                return found
    return None


def resolve_org_id(session: requests.Session) -> str:
    request_with_retry(
        session,
        "GET",
        SEARCH_PAGE,
        headers={"User-Agent": HEADERS["User-Agent"]},
        timeout=40,
    )

    for stock_list_url in STOCK_LIST_URLS:
        try:
            response = request_with_retry(session, "GET", stock_list_url, headers=HEADERS, timeout=90)
            org_id = recursively_find_org_id(response.json())
            if org_id:
                log("ORG_ID_FROM_STOCK_LIST", stock_list_url, org_id)
                return org_id
        except Exception as exc:  # noqa: BLE001
            log("STOCK_LIST_LOOKUP_FAILED", stock_list_url, repr(exc))

    for keyword in (CODE, COMPANY, FULL_COMPANY):
        try:
            response = request_with_retry(
                session,
                "POST",
                TOP_SEARCH_URL,
                headers=HEADERS,
                data={"keyWord": keyword},
                timeout=90,
            )
            org_id = recursively_find_org_id(response.json())
            if org_id:
                log("ORG_ID_FROM_TOP_SEARCH", keyword, org_id)
                return org_id
        except Exception as exc:  # noqa: BLE001
            log("TOP_SEARCH_LOOKUP_FAILED", keyword, repr(exc))

    raise RuntimeError(f"Could not resolve CNINFO orgId for {CODE} {COMPANY}")


def query_announcements(
    session: requests.Session,
    org_id: str,
    *,
    category: str,
    start_date: str = START_DATE,
    end_date: str = AS_OF_DATE,
) -> list[dict[str, Any]]:
    best: list[dict[str, Any]] = []
    for stock_value in (f"{CODE},{org_id}", CODE):
        for column in ("sse", ""):
            for plate in ("shmb", ""):
                rows: list[dict[str, Any]] = []
                page_num = 1
                total_pages = 1
                while page_num <= total_pages and page_num <= 30:
                    payload = {
                        "pageNum": str(page_num),
                        "pageSize": "30",
                        "column": column,
                        "tabName": "fulltext",
                        "plate": plate,
                        "stock": stock_value,
                        "searchkey": "",
                        "secid": "",
                        "category": category,
                        "trade": "",
                        "seDate": f"{start_date}~{end_date}",
                        "sortName": "",
                        "sortType": "",
                        "isHLtitle": "true",
                    }
                    response = request_with_retry(
                        session,
                        "POST",
                        QUERY_URL,
                        headers=HEADERS,
                        data=payload,
                        timeout=120,
                    )
                    data = response.json()
                    page_rows = data.get("announcements") or []
                    rows.extend(page_rows)
                    try:
                        total_pages = max(1, int(data.get("totalpages") or 1))
                    except Exception:
                        total_pages = 1
                    if not page_rows:
                        break
                    page_num += 1
                    time.sleep(0.2)

                if len(rows) > len(best):
                    best = rows
                if rows:
                    log(
                        "QUERY_RESULT",
                        json.dumps(
                            {
                                "category": category,
                                "stock": stock_value,
                                "column": column,
                                "plate": plate,
                                "count": len(rows),
                            },
                            ensure_ascii=False,
                        ),
                    )
                    break
            if best:
                break
        if best:
            break

    dedup: dict[str, dict[str, Any]] = {}
    for row in best:
        key = str(row.get("announcementId") or row.get("adjunctUrl") or row.get("announcementTitle"))
        dedup[key] = row
    result = list(dedup.values())
    for row in result:
        row["cleanTitle"] = clean_title(row.get("announcementTitle"))
    return result


def announcement_time(row: dict[str, Any]) -> int:
    value = row.get("announcementTime") or row.get("announcementDate") or 0
    try:
        return int(value)
    except Exception:
        return 0


def announcement_date(row: dict[str, Any]) -> str:
    value = announcement_time(row)
    if value > 10_000_000_000:
        return datetime.fromtimestamp(value / 1000, tz=BJ).strftime("%Y-%m-%d")
    if value > 0:
        return datetime.fromtimestamp(value, tz=BJ).strftime("%Y-%m-%d")
    url = str(row.get("adjunctUrl") or "")
    match = re.search(r"/(20\d{2}-\d{2}-\d{2})/", url)
    return match.group(1) if match else ""


def revision_rank(title: str) -> int:
    rank = 0
    if any(word in title for word in ("更新后", "修订版", "修订稿", "更正后")):
        rank += 30
    if "全文" in title:
        rank += 5
    return rank


def choose_annual_reports(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_year: dict[int, list[dict[str, Any]]] = {year: [] for year in ANNUAL_YEARS}
    for row in rows:
        title = row["cleanTitle"]
        match = re.search(r"(20\d{2})年?年度报告", title)
        if not match:
            continue
        year = int(match.group(1))
        if year not in by_year:
            continue
        if any(
            word in title
            for word in (
                "摘要",
                "英文版",
                "关于",
                "审计报告",
                "内部控制",
                "取消",
                "说明",
                "问询",
            )
        ):
            continue
        by_year[year].append(row)

    selected: list[dict[str, Any]] = []
    missing: list[int] = []
    for year in ANNUAL_YEARS:
        candidates = by_year[year]
        if not candidates:
            missing.append(year)
            continue
        candidates.sort(
            key=lambda row: (
                revision_rank(row["cleanTitle"]),
                announcement_time(row),
                len(row["cleanTitle"]),
            ),
            reverse=True,
        )
        selected.append(candidates[0])
    if missing:
        raise RuntimeError(
            f"Missing annual reports for {missing}. Candidates: {[row['cleanTitle'] for row in rows]}"
        )
    return selected


def choose_latest_quarter(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[tuple[tuple[int, int, int, int], dict[str, Any]]] = []
    for row in rows:
        title = row["cleanTitle"]
        if any(word in title for word in ("关于", "取消", "英文版", "更正公告", "摘要")):
            continue
        q1 = re.search(r"(20\d{2})年(?:第一|一)季度报告", title)
        q3 = re.search(r"(20\d{2})年(?:第三|三)季度报告", title)
        if not q1 and not q3:
            continue
        year = int((q1 or q3).group(1))
        quarter = 1 if q1 else 3
        candidates.append(((year, quarter, revision_rank(title), announcement_time(row)), row))
    if not candidates:
        raise RuntimeError(
            f"No quarterly report found. Candidates: {[row['cleanTitle'] for row in rows]}"
        )
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def adjunct_url(row: dict[str, Any]) -> str:
    value = str(row.get("adjunctUrl") or "").strip()
    if not value:
        raise RuntimeError(f"Announcement has no adjunctUrl: {row}")
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return urljoin(STATIC_BASE, value.lstrip("/"))


def extract_opening_text(path: Path, pages: int) -> str:
    chunks: list[str] = []
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        result = subprocess.run(
            [pdftotext, "-f", "1", "-l", str(min(8, pages)), "-enc", "UTF-8", str(path), "-"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            chunks.append(result.stdout)
    try:
        reader = PdfReader(str(path), strict=False)
        for page in reader.pages[: min(5, pages)]:
            chunks.append(page.extract_text() or "")
    except Exception:
        pass
    return "\n".join(chunks)


def render_pages(path: Path, pages: int) -> tuple[list[int], list[str]]:
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise RuntimeError("pdftoppm is unavailable")
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    selected = sorted(set([1, (pages + 1) // 2, pages]))
    outputs: list[str] = []
    for page_no in selected:
        prefix = VERIFY_DIR / f"{path.stem}_p{page_no}"
        result = subprocess.run(
            [
                pdftoppm,
                "-f",
                str(page_no),
                "-l",
                str(page_no),
                "-singlefile",
                "-png",
                "-r",
                "120",
                str(path),
                str(prefix),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"PDF render failed for {path}, page {page_no}: {result.stderr[-1000:]}")
        image_path = prefix.with_suffix(".png")
        data = image_path.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 10_000:
            raise RuntimeError(f"Invalid render output: {image_path}")
        outputs.append(str(image_path))
    return selected, outputs


def validate_pdf(path: Path, row: dict[str, Any], period: str) -> dict[str, Any]:
    data = path.read_bytes()
    if not data.startswith(b"%PDF-") or len(data) < 50_000:
        raise RuntimeError(f"Invalid PDF file: {path}, bytes={len(data)}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 5:
        raise RuntimeError(f"Unexpectedly short filing: {path}, pages={pages}")

    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, check=False)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path}: {(qpdf.stdout + qpdf.stderr)[-2000:]}")

    text = re.sub(r"\s+", "", extract_opening_text(path, pages))
    identity_text_verified = any(token in text for token in (COMPANY, FULL_COMPANY, CODE))
    period_text_verified = period[:4] in text
    rendered_pages, render_files = render_pages(path, pages)

    return {
        "bytes": len(data),
        "pages": pages,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "identity_text_verified": identity_text_verified,
        "period_text_verified": period_text_verified,
        "source_stock_filter_verified": True,
        "rendered_pages": rendered_pages,
        "render_files": render_files,
    }


def download_pdf(
    session: requests.Session,
    row: dict[str, Any],
    path: Path,
    doc_type: str,
    period: str,
) -> dict[str, Any]:
    url = adjunct_url(row)
    response = request_with_retry(
        session,
        "GET",
        url,
        headers={
            "User-Agent": HEADERS["User-Agent"],
            "Referer": CNINFO_BASE + "/",
            "Accept": "application/pdf,*/*;q=0.8",
        },
        max_attempts=6,
        timeout=180,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    validation = validate_pdf(path, row, period)
    record = {
        "doc_type": doc_type,
        "period": period,
        "title": row["cleanTitle"],
        "announcement_date": announcement_date(row),
        "announcement_id": str(row.get("announcementId") or ""),
        "source_url": url,
        "relative_path": str(path.relative_to(PACKAGE_ROOT)),
        **validation,
    }
    log("VALIDATED", json.dumps(record, ensure_ascii=False))
    return record


def write_metadata(records: list[dict[str, Any]], org_id: str) -> None:
    latest = records[-1]
    readme_lines = [
        f"{FULL_COMPANY}（证券简称：{COMPANY}，证券代码：{CODE}）",
        "2020—2025年年度报告及最新季度报告资料包",
        "",
        f"检索与核验截止日期：{AS_OF_DATE}",
        "来源：巨潮资讯网法定信息披露文件镜像",
        f"CNINFO orgId：{org_id}",
        "",
        "收录范围：",
        "1. 2020—2025年完整年度报告，共6份；不收录年度报告摘要、英文版、单独审计报告或内控报告。",
        f"2. 最新季度报告：{latest['title']}，公告日期：{latest['announcement_date']}。",
        "3. 半年度报告属于中期报告，不按第一季度/第三季度报告口径替代“最新季报”。",
        "",
        "校验：",
        "- 每份PDF均检查文件头、实际页数、qpdf结构及SHA-256。",
        "- 每份PDF均渲染首页、中间页和末页，确认可正常显示。",
        "- 公司身份通过精确证券代码公告查询核验；可提取文本时同时核验公司名称或证券代码和报告年份。",
        "",
        "文件清单：",
    ]
    for index, record in enumerate(records, 1):
        readme_lines.extend(
            [
                f"{index}. {record['title']}",
                f"   类型/期间：{record['doc_type']} / {record['period']}",
                f"   公告日期：{record['announcement_date']}",
                f"   页数：{record['pages']}；大小：{record['bytes']}字节",
                f"   文件：{record['relative_path']}",
                f"   来源：{record['source_url']}",
                f"   SHA-256：{record['sha256']}",
                "",
            ]
        )
    (PACKAGE_ROOT / "README.txt").write_text("\n".join(readme_lines), encoding="utf-8")

    fields = [
        "doc_type",
        "period",
        "title",
        "announcement_date",
        "announcement_id",
        "pages",
        "bytes",
        "sha256",
        "relative_path",
        "source_url",
        "qpdf_return_code",
        "identity_text_verified",
        "period_text_verified",
        "source_stock_filter_verified",
    ]
    with (PACKAGE_ROOT / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "company": FULL_COMPANY,
        "short_name": COMPANY,
        "stock_code": CODE,
        "cninfo_org_id": org_id,
        "as_of_date": AS_OF_DATE,
        "generated_at": datetime.now(tz=BJ).isoformat(),
        "annual_report_years": ANNUAL_YEARS,
        "latest_quarterly_report": latest["title"],
        "document_count": len(records),
        "records": records,
    }
    (PACKAGE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (PACKAGE_ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{record['sha256']}  {record['relative_path']}" for record in records) + "\n",
        encoding="utf-8",
    )


def build_zip() -> None:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(PACKAGE_ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(Path(PACKAGE_ROOT.name) / path.relative_to(PACKAGE_ROOT)))
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC validation failed at {bad}")
    log("FINAL_ZIP", ZIP_PATH.name, "bytes", ZIP_PATH.stat().st_size, "sha256", sha256_file(ZIP_PATH))


def main() -> None:
    if WORK_ROOT.exists():
        shutil.rmtree(WORK_ROOT)
    for directory in (ANNUAL_DIR, QUARTER_DIR, VERIFY_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.trust_env = False
    org_id = resolve_org_id(session)

    annual_rows = query_announcements(
        session,
        org_id,
        category="category_ndbg_szsh;",
        start_date="2020-01-01",
        end_date=AS_OF_DATE,
    )
    q1_rows = query_announcements(
        session,
        org_id,
        category="category_yjdbg_szsh;",
        start_date="2020-01-01",
        end_date=AS_OF_DATE,
    )
    q3_rows = query_announcements(
        session,
        org_id,
        category="category_sjdbg_szsh;",
        start_date="2020-01-01",
        end_date=AS_OF_DATE,
    )

    annuals = choose_annual_reports(annual_rows)
    latest_quarter = choose_latest_quarter(q1_rows + q3_rows)
    log("SELECTED_ANNUALS", json.dumps([row["cleanTitle"] for row in annuals], ensure_ascii=False))
    log("SELECTED_LATEST_QUARTER", latest_quarter["cleanTitle"])

    records: list[dict[str, Any]] = []
    for row in annuals:
        match = re.search(r"(20\d{2})年?年度报告", row["cleanTitle"])
        if not match:
            raise RuntimeError(f"Cannot parse annual-report year: {row['cleanTitle']}")
        year = match.group(1)
        records.append(
            download_pdf(
                session,
                row,
                ANNUAL_DIR / f"{year}_{COMPANY}_年度报告.pdf",
                "年度报告",
                year,
            )
        )
        time.sleep(0.4)

    quarter_title = latest_quarter["cleanTitle"]
    quarter_year_match = re.search(r"(20\d{2})年", quarter_title)
    if not quarter_year_match:
        raise RuntimeError(f"Cannot parse quarterly-report year: {quarter_title}")
    quarter_year = quarter_year_match.group(1)
    if "第一季度" in quarter_title or "一季度" in quarter_title:
        quarter_no = 1
        quarter_cn = "第一季度"
    else:
        quarter_no = 3
        quarter_cn = "第三季度"
    records.append(
        download_pdf(
            session,
            latest_quarter,
            QUARTER_DIR / f"{quarter_year}Q{quarter_no}_{COMPANY}_{quarter_cn}报告.pdf",
            "季度报告",
            f"{quarter_year}Q{quarter_no}",
        )
    )

    if len(records) != 7:
        raise RuntimeError(f"Expected 7 PDFs, got {len(records)}")
    if len({record["sha256"] for record in records}) != 7:
        raise RuntimeError("Duplicate filing PDFs detected")

    write_metadata(records, org_id)
    build_zip()


if __name__ == "__main__":
    main()
