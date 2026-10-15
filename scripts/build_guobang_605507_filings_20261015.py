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

CODE = "605507"
COMPANY = "国邦医药"
FULL_COMPANY = "国邦医药集团股份有限公司"
AS_OF_DATE = "2026-10-15"
START_DATE = "2015-01-01"

ROOT = Path.cwd()
WORK_ROOT = ROOT / "_build_guobang_605507"
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


def safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", "", value)
    return value[:180]


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
) -> list[dict[str, Any]]:
    candidates = [
        (f"{CODE},{org_id}", "sse", "shmb"),
        (f"{CODE},{org_id}", "sse", ""),
        (CODE, "sse", "shmb"),
        (CODE, "sse", ""),
    ]
    best: list[dict[str, Any]] = []

    for stock_value, column, plate in candidates:
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
                "searchkey": searchkey,
                "secid": "",
                "category": category,
                "trade": "",
                "seDate": f"{START_DATE}~{AS_OF_DATE}",
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
        key = str(row.get("announcementId") or row.get("adjunctUrl") or row.get("announcementTitle"))
        dedup[key] = row
    result = list(dedup.values())
    for row in result:
        row["cleanTitle"] = clean_title(row.get("announcementTitle"))
    return result


def announcement_time(row: dict[str, Any]) -> int:
    try:
        return int(row.get("announcementTime") or row.get("announcementDate") or 0)
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


def choose_all_annual_reports(rows: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    by_year: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        title = row["cleanTitle"]
        match = re.search(r"(20\d{2})年?年度报告", title)
        if not match:
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
                "更正公告",
                "补充公告",
            )
        ):
            continue
        year = int(match.group(1))
        by_year.setdefault(year, []).append(row)

    if not by_year:
        raise RuntimeError(f"No annual reports found. Candidates: {[row['cleanTitle'] for row in rows]}")

    selected: list[tuple[int, dict[str, Any]]] = []
    for year in sorted(by_year):
        candidates = by_year[year]
        candidates.sort(
            key=lambda row: (
                revision_rank(row["cleanTitle"]),
                announcement_time(row),
                len(row["cleanTitle"]),
            ),
            reverse=True,
        )
        selected.append((year, candidates[0]))

    if len(selected) < 4:
        raise RuntimeError(f"Unexpectedly few annual reports: {[(y, r['cleanTitle']) for y, r in selected]}")
    return selected


def choose_formal_prospectus(rows: list[dict[str, Any]]) -> dict[str, Any]:
    negative_words = (
        "摘要",
        "招股意向书",
        "申报稿",
        "上会稿",
        "注册稿",
        "预披露",
        "更新稿",
        "附录",
        "提示性公告",
        "关于",
        "问询",
    )
    candidates: list[tuple[tuple[int, int, int], dict[str, Any]]] = []
    for row in rows:
        title = row["cleanTitle"]
        if "招股说明书" not in title:
            continue
        if any(word in title for word in negative_words):
            continue
        score = 0
        if "首次公开发行" in title:
            score += 50
        if "股票" in title or "A股" in title:
            score += 20
        if title.endswith("招股说明书"):
            score += 30
        candidates.append(((score, announcement_time(row), -len(title)), row))

    if not candidates:
        raise RuntimeError(f"No formal prospectus found. Candidates: {[row['cleanTitle'] for row in rows if '招股' in row['cleanTitle']]}")
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def choose_latest_quarter(rows: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    candidates: list[tuple[tuple[int, int, int, int], str, dict[str, Any]]] = []
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
        period = f"{year}Q{quarter}"
        candidates.append(((year, quarter, revision_rank(title), announcement_time(row)), period, row))
    if not candidates:
        raise RuntimeError(f"No quarterly report found. Candidates: {[row['cleanTitle'] for row in rows]}")
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1], candidates[0][2]


def adjunct_url(row: dict[str, Any]) -> str:
    value = str(row.get("adjunctUrl") or "").strip()
    if not value:
        raise RuntimeError(f"Announcement has no adjunctUrl: {row}")
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return urljoin(STATIC_BASE, value.lstrip("/"))


def extract_opening_text(path: Path, pages: int) -> str:
    result = subprocess.run(
        ["pdftotext", "-f", "1", "-l", str(min(15, pages)), "-enc", "UTF-8", str(path), "-"],
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
        prefix = VERIFY_DIR / f"{safe_name(path.stem)}_p{page_no}"
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
            raise RuntimeError(f"Render failed for {path}, page {page_no}: {result.stderr[-1000:]}")
        image_path = prefix.with_suffix(".png")
        data = image_path.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 10_000:
            raise RuntimeError(f"Invalid render output: {image_path}")
        rendered.append(str(image_path))
    return selected, rendered


def validate_pdf(path: Path, *, doc_type: str, period: str) -> dict[str, Any]:
    data = path.read_bytes()
    if not data.startswith(b"%PDF-") or len(data) < 50_000:
        raise RuntimeError(f"Invalid PDF: {path}, bytes={len(data)}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    minimum_pages = 100 if doc_type in {"年度报告", "招股说明书"} else 5
    if pages < minimum_pages:
        raise RuntimeError(f"Unexpectedly short {doc_type}: {path}, pages={pages}")

    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, check=False)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf validation failed for {path}: {(qpdf.stdout + qpdf.stderr)[-2000:]}")

    text = extract_opening_text(path, pages)
    compact = re.sub(r"\s+", "", text)
    identity_verified = any(token in compact for token in (COMPANY, FULL_COMPANY, CODE))
    if not identity_verified:
        raise RuntimeError(f"Company identity check failed for {path}")

    if doc_type == "年度报告":
        type_period_verified = period in compact and "年度报告" in compact
    elif doc_type == "招股说明书":
        type_period_verified = "招股说明书" in compact and "首次公开发行" in compact
    else:
        type_period_verified = period[:4] in compact and "季度报告" in compact
    if not type_period_verified:
        raise RuntimeError(f"Document type/period check failed for {path}: {doc_type} {period}")

    rendered_pages, render_files = render_selected_pages(path, pages)
    return {
        "bytes": len(data),
        "pages": pages,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "identity_text_verified": identity_verified,
        "type_period_text_verified": type_period_verified,
        "source_stock_filter_verified": True,
        "rendered_pages": rendered_pages,
        "render_files": render_files,
    }


def write_support_files(records: list[dict[str, Any]], annual_years: list[int], latest_period: str) -> None:
    lines = [
        f"{COMPANY}（{CODE}）全部年度报告、正式招股说明书及最新季报",
        "",
        f"检索与核验截止日期：{AS_OF_DATE}",
        "",
        "收录说明：",
        f"1. 年度报告按法定信息披露平台实际可取得记录收录：{', '.join(map(str, annual_years))}年度。",
        "2. 招股说明书采用首次公开发行正式发行版，排除招股意向书、摘要、申报稿、上会稿和注册稿。",
        f"3. 最新季报按第一季度/第三季度报告口径选择，为{latest_period}。",
        "4. 年报摘要、英文版、单独审计报告、内部控制报告及说明性公告均未收录。",
        "5. 每份PDF均检查文件结构、实际页数、公司身份和报告期间，并渲染首页、中间页及末页。",
        "6. 文件仅供研究学习，版权归原披露主体及相关权利人所有。",
        "",
        "文件清单：",
    ]
    for index, record in enumerate(records, 1):
        lines.extend(
            [
                f"{index}. {record['doc_type']}｜{record['period']}",
                f"   标题：{record['title']}",
                f"   公告日期：{record['announcement_date']}",
                f"   页数：{record['pages']}；大小：{record['bytes']}字节",
                f"   文件：{record['relative_path']}",
                f"   来源：{record['source_url']}",
                f"   SHA-256：{record['sha256']}",
                "",
            ]
        )
    (PACKAGE_ROOT / "README.txt").write_text("\n".join(lines), encoding="utf-8")

    fields = [
        "doc_type",
        "period",
        "title",
        "announcement_date",
        "announcement_id",
        "source_url",
        "relative_path",
        "pages",
        "bytes",
        "sha256",
        "qpdf_return_code",
        "identity_text_verified",
        "type_period_text_verified",
        "source_stock_filter_verified",
    ]
    with (PACKAGE_ROOT / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "company": COMPANY,
        "full_company_name": FULL_COMPANY,
        "stock_code": CODE,
        "as_of_date": AS_OF_DATE,
        "annual_years": annual_years,
        "latest_quarter_period": latest_period,
        "generated_at": datetime.now(tz=BJ).isoformat(),
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


def download_and_validate(
    session: requests.Session,
    row: dict[str, Any],
    path: Path,
    *,
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
            "Accept": "application/pdf,*/*;q=0.8",
            "Referer": SEARCH_PAGE,
        },
        timeout=180,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    validation = validate_pdf(path, doc_type=doc_type, period=period)
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
    for directory in (ANNUAL_DIR, PROSPECTUS_DIR, QUARTER_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.trust_env = False
    org_id = resolve_org_id(session)

    annual_rows = query_announcements(
        session,
        org_id,
        category="category_ndbg_szsh;",
    )
    q1_rows = query_announcements(
        session,
        org_id,
        category="category_yjdbg_szsh;",
    )
    q3_rows = query_announcements(
        session,
        org_id,
        category="category_sjdbg_szsh;",
    )
    prospectus_rows = query_announcements(
        session,
        org_id,
        category="",
        searchkey="招股说明书",
    )
    if not prospectus_rows:
        all_rows = query_announcements(session, org_id, category="", searchkey="")
        prospectus_rows = [row for row in all_rows if "招股说明书" in row["cleanTitle"]]

    selected_annuals = choose_all_annual_reports(annual_rows)
    selected_prospectus = choose_formal_prospectus(prospectus_rows)
    latest_period, selected_quarter = choose_latest_quarter(q1_rows + q3_rows)

    log("SELECTED_ANNUALS", [row["cleanTitle"] for _, row in selected_annuals])
    log("SELECTED_PROSPECTUS", selected_prospectus["cleanTitle"])
    log("SELECTED_LATEST_QUARTER", selected_quarter["cleanTitle"])

    records: list[dict[str, Any]] = []
    annual_years: list[int] = []
    for year, row in selected_annuals:
        annual_years.append(year)
        path = ANNUAL_DIR / f"{year}_{COMPANY}_年度报告.pdf"
        records.append(
            download_and_validate(
                session,
                row,
                path,
                doc_type="年度报告",
                period=str(year),
            )
        )
        time.sleep(0.3)

    prospectus_path = PROSPECTUS_DIR / f"{announcement_date(selected_prospectus)[:4]}_{COMPANY}_首次公开发行股票招股说明书_正式版.pdf"
    records.append(
        download_and_validate(
            session,
            selected_prospectus,
            prospectus_path,
            doc_type="招股说明书",
            period="正式发行版",
        )
    )

    quarter_label = "第三季度报告" if latest_period.endswith("Q3") else "第一季度报告"
    quarter_path = QUARTER_DIR / f"{latest_period}_{COMPANY}_{quarter_label}.pdf"
    records.append(
        download_and_validate(
            session,
            selected_quarter,
            quarter_path,
            doc_type="季度报告",
            period=latest_period,
        )
    )

    if len({record["sha256"] for record in records}) != len(records):
        raise RuntimeError("Duplicate PDF content detected")

    write_support_files(records, annual_years, latest_period)
    build_zip()


if __name__ == "__main__":
    main()
