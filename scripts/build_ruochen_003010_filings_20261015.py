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

CODE = "003010"
COMPANY = "若羽臣"
FULL_COMPANY = "广州若羽臣科技股份有限公司"
AS_OF_DATE = "2026-10-15"
ANNUAL_YEARS = list(range(2020, 2026))

ROOT = Path.cwd()
WORK_ROOT = ROOT / "_build_ruochen_003010"
PACKAGE_NAME = f"{COMPANY}_{CODE}_所有年报_招股说明书及最新季报"
PACKAGE_ROOT = WORK_ROOT / PACKAGE_NAME
ANNUAL_DIR = PACKAGE_ROOT / "01_年度报告"
PROSPECTUS_DIR = PACKAGE_ROOT / "02_招股说明书"
QUARTER_DIR = PACKAGE_ROOT / "03_最新季报"
VERIFY_DIR = WORK_ROOT / "_verify"
ZIP_PATH = ROOT / f"{PACKAGE_NAME}.zip"

CNINFO_BASE = "https://www.cninfo.com.cn"
SEARCH_PAGE = CNINFO_BASE + "/new/commonUrl/pageOfSearch?url=disclosure/list/search"
QUERY_URL = CNINFO_BASE + "/new/hisAnnouncement/query"
STOCK_LIST_URLS = [
    CNINFO_BASE + "/new/data/szse_stock.json",
    CNINFO_BASE + "/new/data/shse_stock.json",
]
TOP_SEARCH_URL = CNINFO_BASE + "/new/information/topSearch/detailOfQuery"
STATIC_BASE = "https://static.cninfo.com.cn/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36"
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
            if attempt < max_attempts:
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
    for url in STOCK_LIST_URLS:
        try:
            response = request_with_retry(session, "GET", url, headers=HEADERS, timeout=60)
            org_id = recursively_find_org_id(response.json())
            if org_id:
                log("ORG_ID_FROM_STOCK_LIST", url, org_id)
                return org_id
        except Exception as exc:  # noqa: BLE001
            log("STOCK_LIST_LOOKUP_FAILED", url, repr(exc))
    for keyword in (CODE, COMPANY, FULL_COMPANY):
        try:
            response = request_with_retry(
                session,
                "POST",
                TOP_SEARCH_URL,
                headers=HEADERS,
                data={"keyWord": keyword},
                timeout=60,
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
    searchkey: str = "",
    start_date: str = "2018-01-01",
    end_date: str = AS_OF_DATE,
) -> list[dict[str, Any]]:
    candidates = [
        (f"{CODE},{org_id}", "szse", "szmb"),
        (f"{CODE},{org_id}", "szse", "szsme"),
        (f"{CODE},{org_id}", "szse", ""),
        (CODE, "szse", "szmb"),
        (CODE, "szse", ""),
    ]
    best: list[dict[str, Any]] = []

    for stock_value, column, plate in candidates:
        rows: list[dict[str, Any]] = []
        page_num = 1
        total_pages = 1
        while page_num <= total_pages and page_num <= 40:
            payload = {
                "pageNum": str(page_num),
                "pageSize": "30",
                "column": column,
                "tabName": "fulltext",
                "plate": plate,
                "stock": stock_value,
                "searchkey": searchkey,
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
                timeout=90,
            )
            data = response.json()
            page_rows = data.get("announcements") or []
            rows.extend(page_rows)
            try:
                total_pages = max(1, int(data.get("totalpages") or 1))
            except Exception:  # noqa: BLE001
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
                        "searchkey": searchkey,
                        "stock": stock_value,
                        "column": column,
                        "plate": plate,
                        "count": len(rows),
                    },
                    ensure_ascii=False,
                ),
            )
            break

    dedup: dict[str, dict[str, Any]] = {}
    for row in best:
        key = str(
            row.get("announcementId")
            or row.get("adjunctUrl")
            or row.get("announcementTitle")
        )
        dedup[key] = row
    result = list(dedup.values())
    for row in result:
        row["cleanTitle"] = clean_title(row.get("announcementTitle"))
    return result


def announcement_time(row: dict[str, Any]) -> int:
    value = row.get("announcementTime") or row.get("announcementDate") or 0
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return 0


def announcement_date(row: dict[str, Any]) -> str:
    value = announcement_time(row)
    if value > 10_000_000_000:
        return datetime.fromtimestamp(value / 1000, tz=BJ).strftime("%Y-%m-%d")
    if value > 0:
        return datetime.fromtimestamp(value, tz=BJ).strftime("%Y-%m-%d")
    match = re.search(r"/(20\d{2}-\d{2}-\d{2})/", str(row.get("adjunctUrl") or ""))
    return match.group(1) if match else ""


def revision_rank(title: str) -> int:
    rank = 0
    if any(word in title for word in ("更新后", "修订版", "修订稿", "更正后")):
        rank += 20
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
        candidates.append(
            ((year, quarter, revision_rank(title), announcement_time(row)), row)
        )
    if not candidates:
        raise RuntimeError(
            f"No quarterly report found. Candidates: {[row['cleanTitle'] for row in rows]}"
        )
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def choose_formal_prospectus(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        title = row["cleanTitle"]
        if "招股说明书" not in title:
            continue
        if not re.search(r"首次公开发行.*招股说明书", title):
            continue
        if any(
            word in title
            for word in (
                "摘要",
                "申报稿",
                "预披露",
                "招股意向书",
                "反馈",
                "问询",
                "回复",
                "审核",
                "上市公告书",
            )
        ):
            continue
        candidates.append(row)

    if not candidates:
        raise RuntimeError(
            "No formal IPO prospectus found. Candidates: "
            + repr([row["cleanTitle"] for row in rows if "招股" in row["cleanTitle"]])
        )
    candidates.sort(
        key=lambda row: (announcement_time(row), len(row["cleanTitle"])),
        reverse=True,
    )
    return candidates[0]


def adjunct_url(row: dict[str, Any]) -> str:
    value = str(row.get("adjunctUrl") or "").strip()
    if not value:
        raise RuntimeError(f"Announcement has no adjunctUrl: {row}")
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return urljoin(STATIC_BASE, value.lstrip("/"))


def extract_opening_text(path: Path, pages: int) -> str:
    result = subprocess.run(
        [
            "pdftotext",
            "-f",
            "1",
            "-l",
            str(min(15, pages)),
            "-enc",
            "UTF-8",
            str(path),
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pdftotext failed for {path}: {result.stderr[-1000:]}")
    return result.stdout


def render_selected_pages(path: Path, page_count: int) -> tuple[list[int], list[str]]:
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    selected = sorted(set([1, (page_count + 1) // 2, page_count]))
    rendered: list[str] = []
    for page_no in selected:
        prefix = VERIFY_DIR / f"{path.stem}_p{page_no}"
        result = subprocess.run(
            [
                "pdftoppm",
                "-f",
                str(page_no),
                "-l",
                str(page_no),
                "-singlefile",
                "-png",
                "-r",
                "110",
                str(path),
                str(prefix),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Render failed for {path}, page {page_no}: {result.stderr[-1000:]}"
            )
        image_path = prefix.with_suffix(".png")
        data = image_path.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 10_000:
            raise RuntimeError(f"Invalid render output: {image_path}")
        rendered.append(str(image_path))
    return selected, rendered


def validate_pdf(
    path: Path,
    row: dict[str, Any],
    *,
    doc_type: str,
    period: str,
) -> dict[str, Any]:
    data = path.read_bytes()
    if not data.startswith(b"%PDF-") or len(data) < 50_000:
        raise RuntimeError(f"Invalid PDF: {path}, bytes={len(data)}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if doc_type == "招股说明书" and pages < 100:
        raise RuntimeError(f"Prospectus unexpectedly short: {path}, pages={pages}")
    if doc_type != "招股说明书" and pages < 5:
        raise RuntimeError(f"Unexpectedly short report: {path}, pages={pages}")

    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)], capture_output=True, text=True, check=False
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(
            f"qpdf validation failed for {path}: {(qpdf.stdout + qpdf.stderr)[-2000:]}"
        )

    text = extract_opening_text(path, pages)
    compact = re.sub(r"\s+", "", text)
    identity_verified = any(token in compact for token in (COMPANY, FULL_COMPANY, CODE))
    source_identity_verified = str(row.get("secCode") or row.get("stockCode") or CODE) in {CODE, ""}

    if doc_type == "招股说明书":
        period_verified = "招股说明书" in compact or "首次公开发行" in compact
    else:
        period_verified = period[:4] in compact

    if not identity_verified and not source_identity_verified:
        raise RuntimeError(f"Company identity check failed for {path}")
    if not period_verified:
        raise RuntimeError(f"Document type/period check failed for {path}: {period}")

    rendered_pages, render_files = render_selected_pages(path, pages)
    return {
        "bytes": len(data),
        "pages": pages,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "identity_text_verified": identity_verified,
        "source_stock_filter_verified": source_identity_verified,
        "period_or_type_text_verified": period_verified,
        "rendered_pages": rendered_pages,
        "render_files": render_files,
    }


def write_support_files(
    records: list[dict[str, Any]],
    prospectus_title: str,
    latest_period: str,
) -> None:
    readme_lines = [
        f"{COMPANY}（{CODE}）全部上市后年度报告、正式招股说明书及最新季报",
        "",
        f"核验截止日期：{AS_OF_DATE}",
        "",
        "收录范围：",
        "- 2020—2025年年度报告全文，共6份。公司于2020年上市，因此2020年度为上市后首份年度报告。",
        f"- 正式发行版招股说明书：{prospectus_title}。",
        f"- 最新已披露季度报告：{latest_period}。",
        "",
        "筛选说明：",
        "- 年度报告已排除摘要、英文版、审计报告、内部控制报告及说明性公告；同年度有修订版时优先采用修订版。",
        "- 招股文件采用正式发行版，排除申报稿、预披露稿、招股意向书和摘要。",
        "- 半年度报告不属于第一季度或第三季度报告，未用其替代“最新季报”。",
        "",
        "校验说明：",
        "- 每份PDF均检查文件头、qpdf结构、实际页数、公司身份和报告年份/文件类型。",
        "- 每份PDF均渲染首页、中间页和末页，确认页面可正常显示。",
        "- 逐文件来源、页数和SHA-256见文件清单.csv、manifest.json与SHA256SUMS.txt。",
        "",
        "版权说明：报告版权归上市公司及相关权利人所有，仅供研究学习。",
    ]
    (PACKAGE_ROOT / "README.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

    fields = [
        "doc_type",
        "period",
        "title",
        "announcement_date",
        "announcement_id",
        "relative_path",
        "pages",
        "bytes",
        "sha256",
        "source_url",
        "qpdf_return_code",
        "identity_text_verified",
        "source_stock_filter_verified",
        "period_or_type_text_verified",
    ]
    with (PACKAGE_ROOT / "文件清单.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "company": FULL_COMPANY,
        "short_name": COMPANY,
        "stock_code": CODE,
        "checked_as_of": AS_OF_DATE,
        "annual_report_years": ANNUAL_YEARS,
        "formal_prospectus_title": prospectus_title,
        "latest_quarterly_report": latest_period,
        "document_count": len(records),
        "generated_at": datetime.now(tz=BJ).isoformat(),
        "records": records,
    }
    (PACKAGE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (PACKAGE_ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{record['sha256']}  {record['relative_path']}" for record in records)
        + "\n",
        encoding="utf-8",
    )


def build_zip() -> None:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(
        ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for path in sorted(PACKAGE_ROOT.rglob("*")):
            if path.is_file():
                archive.write(
                    path,
                    arcname=str(Path(PACKAGE_ROOT.name) / path.relative_to(PACKAGE_ROOT)),
                )
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC validation failed at {bad}")
    log(
        "FINAL_ZIP",
        ZIP_PATH.name,
        "bytes",
        ZIP_PATH.stat().st_size,
        "sha256",
        sha256_file(ZIP_PATH),
    )


def download_and_validate(
    session: requests.Session,
    row: dict[str, Any],
    *,
    doc_type: str,
    period: str,
    path: Path,
) -> dict[str, Any]:
    url = adjunct_url(row)
    response = request_with_retry(
        session,
        "GET",
        url,
        headers={
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "application/pdf,*/*;q=0.8",
            "Referer": SEARCH_PAGE,
        },
        timeout=180,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    validation = validate_pdf(path, row, doc_type=doc_type, period=period)
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


def main() -> None:
    if WORK_ROOT.exists():
        shutil.rmtree(WORK_ROOT)
    for directory in (ANNUAL_DIR, PROSPECTUS_DIR, QUARTER_DIR, VERIFY_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.trust_env = False
    org_id = resolve_org_id(session)

    annual_rows = query_announcements(
        session,
        org_id,
        category="category_ndbg_szsh;",
        start_date="2020-01-01",
    )
    q1_rows = query_announcements(
        session,
        org_id,
        category="category_yjdbg_szsh;",
        start_date="2020-01-01",
    )
    q3_rows = query_announcements(
        session,
        org_id,
        category="category_sjdbg_szsh;",
        start_date="2020-01-01",
    )
    prospectus_rows = query_announcements(
        session,
        org_id,
        category="",
        searchkey="招股说明书",
        start_date="2018-01-01",
        end_date="2021-12-31",
    )
    if not prospectus_rows:
        prospectus_rows = query_announcements(
            session,
            org_id,
            category="",
            searchkey="",
            start_date="2018-01-01",
            end_date="2021-12-31",
        )

    annuals = choose_annual_reports(annual_rows)
    latest_quarter = choose_latest_quarter(q1_rows + q3_rows)
    prospectus = choose_formal_prospectus(prospectus_rows)

    log("SELECTED_ANNUALS", json.dumps([row["cleanTitle"] for row in annuals], ensure_ascii=False))
    log("SELECTED_PROSPECTUS", prospectus["cleanTitle"])
    log("SELECTED_LATEST_QUARTER", latest_quarter["cleanTitle"])

    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    for year, row in zip(ANNUAL_YEARS, annuals, strict=True):
        record = download_and_validate(
            session,
            row,
            doc_type="年度报告",
            period=str(year),
            path=ANNUAL_DIR / f"{year}_若羽臣_年度报告.pdf",
        )
        if record["sha256"] in seen_hashes:
            raise RuntimeError(f"Duplicate PDF detected: {record['relative_path']}")
        seen_hashes.add(record["sha256"])
        records.append(record)

    prospectus_record = download_and_validate(
        session,
        prospectus,
        doc_type="招股说明书",
        period="正式发行版",
        path=PROSPECTUS_DIR / "2020_若羽臣_首次公开发行股票招股说明书_正式版.pdf",
    )
    if prospectus_record["sha256"] in seen_hashes:
        raise RuntimeError("Duplicate prospectus PDF detected")
    seen_hashes.add(prospectus_record["sha256"])
    records.append(prospectus_record)

    q_title = latest_quarter["cleanTitle"]
    q_match = re.search(r"(20\d{2})年(?:第?(一|三))季度报告", q_title)
    if not q_match:
        q_match = re.search(r"(20\d{2})年([一三])季度报告", q_title)
    if not q_match:
        raise RuntimeError(f"Could not parse selected quarter title: {q_title}")
    q_year = int(q_match.group(1))
    q_char = q_match.group(2)
    q_num = 1 if q_char == "一" else 3
    q_cn = "第一季度" if q_num == 1 else "第三季度"
    q_period = f"{q_year}年{q_cn}报告"

    quarter_record = download_and_validate(
        session,
        latest_quarter,
        doc_type="季度报告",
        period=f"{q_year}Q{q_num}",
        path=QUARTER_DIR / f"{q_year}Q{q_num}_若羽臣_{q_cn}报告.pdf",
    )
    if quarter_record["sha256"] in seen_hashes:
        raise RuntimeError("Duplicate quarterly PDF detected")
    seen_hashes.add(quarter_record["sha256"])
    records.append(quarter_record)

    if len(records) != 8:
        raise RuntimeError(f"Expected 8 PDFs, got {len(records)}")

    write_support_files(records, prospectus["cleanTitle"], q_period)
    build_zip()


if __name__ == "__main__":
    main()
