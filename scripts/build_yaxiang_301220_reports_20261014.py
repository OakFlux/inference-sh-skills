from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from pypdf import PdfReader


CODE = "301220"
COMPANY = "亚香股份"
FULL_COMPANY = "昆山亚香香料股份有限公司"
AS_OF_DATE = "2026-10-14"
START_DATE = "2019-01-01"
REPO_ROOT = Path.cwd()
WORK_ROOT = REPO_ROOT / "_build_yaxiang_301220"
PACKAGE_ROOT = WORK_ROOT / "亚香股份_301220_年报_招股说明书_最新季报"
ZIP_PATH = REPO_ROOT / "亚香股份_301220_所有年报_招股说明书及最新季报.zip"

CNINFO_BASE = "https://www.cninfo.com.cn"
SEARCH_PAGE = CNINFO_BASE + "/new/commonUrl/pageOfSearch?url=disclosure/list/search"
QUERY_URL = CNINFO_BASE + "/new/hisAnnouncement/query"
STOCK_LIST_URL = CNINFO_BASE + "/new/data/szse_stock.json"
TOP_SEARCH_URL = CNINFO_BASE + "/new/information/topSearch/detailOfQuery"
STATIC_BASE = "https://static.cninfo.com.cn/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
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
    text = re.sub(r"\s+", " ", text).strip()
    return text


def safe_name(value: str) -> str:
    value = clean_title(value)
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", "", value)
    return value[:180]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    max_attempts: int = 5,
    timeout: int = 60,
    **kwargs: Any,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = session.request(method, url, timeout=timeout, **kwargs)
            log("HTTP", attempt, response.status_code, response.headers.get("content-type"), len(response.content), response.url)
            if response.status_code in {429, 500, 502, 503, 504}:
                raise RuntimeError(f"retryable HTTP {response.status_code}")
            response.raise_for_status()
            return response
        except Exception as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            time.sleep(min(2 ** attempt, 12))
    raise RuntimeError(f"Failed request: {method} {url}: {last_error}")


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
    # Establish cookies before using the AJAX endpoints.
    request_with_retry(session, "GET", SEARCH_PAGE, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=40)

    try:
        response = request_with_retry(session, "GET", STOCK_LIST_URL, headers=HEADERS, timeout=60)
        data = response.json()
        org_id = recursively_find_org_id(data)
        if org_id:
            log("ORG_ID_FROM_STOCK_LIST", org_id)
            return org_id
    except Exception as exc:
        log("STOCK_LIST_LOOKUP_FAILED", repr(exc))

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
            data = response.json()
            org_id = recursively_find_org_id(data)
            if org_id:
                log("ORG_ID_FROM_TOP_SEARCH", keyword, org_id)
                return org_id
        except Exception as exc:
            log("TOP_SEARCH_LOOKUP_FAILED", keyword, repr(exc))

    raise RuntimeError(f"Could not resolve CNINFO orgId for {CODE} {COMPANY}")


def query_announcements(
    session: requests.Session,
    org_id: str,
    *,
    category: str = "",
    searchkey: str = "",
    start_date: str = START_DATE,
    end_date: str = AS_OF_DATE,
) -> list[dict[str, Any]]:
    stock_values = [f"{CODE},{org_id}", CODE]
    plate_values = ["szcy", ""]
    best: list[dict[str, Any]] = []

    for stock_value in stock_values:
        for plate in plate_values:
            rows: list[dict[str, Any]] = []
            page_num = 1
            total_pages = 1
            while page_num <= total_pages and page_num <= 30:
                payload = {
                    "pageNum": str(page_num),
                    "pageSize": "30",
                    "column": "szse",
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
                except Exception:
                    total_pages = 1
                if not page_rows:
                    break
                page_num += 1
                time.sleep(0.25)

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
                            "plate": plate,
                            "count": len(rows),
                        },
                        ensure_ascii=False,
                    ),
                )
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
    match = re.search(r"finalpage/(\d{4}-\d{2}-\d{2})/", url)
    return match.group(1) if match else ""


def rank_revision(title: str) -> int:
    rank = 0
    if any(k in title for k in ("更新后", "修订后", "更正后", "修订版", "更新版")):
        rank += 100
    if any(k in title for k in ("取消", "关于", "摘要", "英文版")):
        rank -= 1000
    return rank


def choose_annual_reports(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    exclude = (
        "摘要",
        "关于",
        "审计报告",
        "内部控制",
        "非经营性资金占用",
        "董事会",
        "监事会",
        "独立董事",
        "社会责任",
        "问询",
        "回复",
        "取消",
        "英文版",
        "业绩",
    )
    by_year: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        title = row["cleanTitle"]
        match = re.search(r"(20\d{2})年年度报告", title)
        if not match or any(word in title for word in exclude):
            continue
        year = int(match.group(1))
        by_year.setdefault(year, []).append(row)

    selected: list[dict[str, Any]] = []
    for year in sorted(by_year):
        candidates = by_year[year]
        candidates.sort(
            key=lambda r: (
                rank_revision(r["cleanTitle"]),
                -len(r["cleanTitle"]),
                announcement_time(r),
            ),
            reverse=True,
        )
        selected.append(candidates[0])

    expected_years = list(range(2022, 2026))
    found_years = []
    for row in selected:
        m = re.search(r"(20\d{2})年年度报告", row["cleanTitle"])
        if m:
            found_years.append(int(m.group(1)))
    missing = [year for year in expected_years if year not in found_years]
    if missing:
        all_titles = [row["cleanTitle"] for row in rows]
        raise RuntimeError(f"Missing annual reports for years {missing}. Candidates: {all_titles}")

    return [
        row
        for row in selected
        if int(re.search(r"(20\d{2})年年度报告", row["cleanTitle"]).group(1)) in expected_years
    ]


def choose_prospectus(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        title = row["cleanTitle"]
        if "招股说明书" not in title:
            continue
        if any(word in title for word in ("摘要", "提示性公告", "法律意见", "发行保荐", "问询", "回复")):
            continue
        candidates.append(row)

    if not candidates:
        raise RuntimeError(f"No prospectus found. Candidates: {[r['cleanTitle'] for r in rows]}")

    def score(row: dict[str, Any]) -> tuple[int, int, int]:
        title = row["cleanTitle"]
        value = 0
        if "首次公开发行股票并在创业板上市招股说明书" in title:
            value += 300
        elif "首次公开发行股票" in title:
            value += 200
        if not any(word in title for word in ("申报稿", "上会稿", "注册稿")):
            value += 100
        if "注册稿" in title:
            value += 30
        if "上会稿" in title:
            value += 20
        if "申报稿" in title:
            value += 10
        return value, announcement_time(row), -len(title)

    candidates.sort(key=score, reverse=True)
    return candidates[0]


def choose_latest_quarter(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[tuple[tuple[int, int, int, int], dict[str, Any]]] = []
    for row in rows:
        title = row["cleanTitle"]
        if any(word in title for word in ("关于", "取消", "英文版", "更正公告")):
            continue
        q1 = re.search(r"(20\d{2})年第一季度报告", title)
        q3 = re.search(r"(20\d{2})年第三季度报告", title)
        if not q1 and not q3:
            continue
        year = int((q1 or q3).group(1))
        quarter = 1 if q1 else 3
        candidates.append(((year, quarter, rank_revision(title), announcement_time(row)), row))

    if not candidates:
        raise RuntimeError(f"No quarterly report found. Candidates: {[r['cleanTitle'] for r in rows]}")
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def adjunct_url(row: dict[str, Any]) -> str:
    value = str(row.get("adjunctUrl") or "").strip()
    if not value:
        raise RuntimeError(f"Announcement has no adjunctUrl: {row}")
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return urljoin(STATIC_BASE, value.lstrip("/"))


def validate_pdf(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if not data.startswith(b"%PDF-"):
        raise RuntimeError(f"Not a PDF: {path} first bytes={data[:50]!r}")
    if len(data) < 10_000:
        raise RuntimeError(f"PDF too small: {path} bytes={len(data)}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 1:
        raise RuntimeError(f"PDF has no pages: {path}")
    qpdf = shutil.which("qpdf")
    qpdf_rc = None
    qpdf_tail = ""
    if qpdf:
        proc = subprocess.run([qpdf, "--check", str(path)], capture_output=True, text=True)
        qpdf_rc = proc.returncode
        qpdf_tail = (proc.stdout + "\n" + proc.stderr)[-1000:]
        if proc.returncode not in (0, 3):
            raise RuntimeError(f"qpdf validation failed for {path}: {qpdf_tail}")
    return {
        "bytes": len(data),
        "pages": pages,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf_rc,
        "qpdf_output_tail": qpdf_tail,
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
        timeout=120,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    validation = validate_pdf(path)
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
    readme_lines = [
        f"{FULL_COMPANY}（{COMPANY}，{CODE}）",
        "年报、招股说明书及最新季报资料包",
        "",
        f"资料检索截止日期：{AS_OF_DATE}",
        "来源：巨潮资讯网（深圳证券交易所法定信息披露平台）",
        f"CNINFO orgId：{org_id}",
        "",
        "收录原则：",
        "1. 年报收录公司上市后全部完整年度报告，不收录年度报告摘要、审计报告等配套文件。",
        "2. 招股说明书优先收录首次公开发行并在创业板上市的最终版，不以申报稿替代最终版。",
        "3. 最新季报仅在第一季度报告和第三季度报告中按报告期及公告日期选取最新一期；半年报不作为季报。",
        "4. 每份PDF均校验PDF文件头、页数、SHA-256，并使用qpdf检查文件结构。",
        "",
        "文件清单：",
    ]
    for index, record in enumerate(records, 1):
        readme_lines.extend(
            [
                f"{index}. {record['title']}",
                f"   类型/期间：{record['doc_type']} / {record['period']}",
                f"   公告日期：{record['announcement_date']}",
                f"   页数：{record['pages']}；大小：{record['bytes']} 字节",
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
    ]
    with (PACKAGE_ROOT / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "company": FULL_COMPANY,
        "short_name": COMPANY,
        "stock_code": CODE,
        "cninfo_org_id": org_id,
        "as_of_date": AS_OF_DATE,
        "generated_at": datetime.now(tz=BJ).isoformat(),
        "records": records,
    }
    (PACKAGE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    checksum_lines = [f"{record['sha256']}  {record['relative_path']}" for record in records]
    (PACKAGE_ROOT / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")


def build_zip() -> None:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(PACKAGE_ROOT.rglob("*")):
            if path.is_file():
                arcname = Path(PACKAGE_ROOT.name) / path.relative_to(PACKAGE_ROOT)
                zf.write(path, arcname=str(arcname))
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC validation failed at {bad}")
    log("FINAL_ZIP", ZIP_PATH.name, "bytes", ZIP_PATH.stat().st_size, "sha256", sha256_file(ZIP_PATH))


def main() -> None:
    if WORK_ROOT.exists():
        shutil.rmtree(WORK_ROOT)
    PACKAGE_ROOT.mkdir(parents=True)

    session = requests.Session()
    session.trust_env = False
    org_id = resolve_org_id(session)

    annual_rows = query_announcements(
        session,
        org_id,
        category="category_ndbg_szsh;",
        start_date="2022-01-01",
        end_date=AS_OF_DATE,
    )
    prospectus_rows = query_announcements(
        session,
        org_id,
        searchkey="招股说明书",
        start_date=START_DATE,
        end_date="2022-12-31",
    )
    q1_rows = query_announcements(
        session,
        org_id,
        category="category_yjdbg_szsh;",
        start_date="2022-01-01",
        end_date=AS_OF_DATE,
    )
    q3_rows = query_announcements(
        session,
        org_id,
        category="category_sjdbg_szsh;",
        start_date="2022-01-01",
        end_date=AS_OF_DATE,
    )

    annuals = choose_annual_reports(annual_rows)
    prospectus = choose_prospectus(prospectus_rows)
    latest_quarter = choose_latest_quarter(q1_rows + q3_rows)

    log("SELECTED_ANNUALS", json.dumps([r["cleanTitle"] for r in annuals], ensure_ascii=False))
    log("SELECTED_PROSPECTUS", prospectus["cleanTitle"])
    log("SELECTED_LATEST_QUARTER", latest_quarter["cleanTitle"])

    records: list[dict[str, Any]] = []
    for row in annuals:
        year = re.search(r"(20\d{2})年年度报告", row["cleanTitle"]).group(1)
        filename = f"{year}_{COMPANY}_年度报告.pdf"
        records.append(
            download_pdf(
                session,
                row,
                PACKAGE_ROOT / "01_年报" / filename,
                "年度报告",
                year,
            )
        )
        time.sleep(0.5)

    prospectus_date = announcement_date(prospectus)
    prospectus_year = prospectus_date[:4] if prospectus_date else "2022"
    records.append(
        download_pdf(
            session,
            prospectus,
            PACKAGE_ROOT / "02_招股说明书" / f"{prospectus_year}_{COMPANY}_首次公开发行股票并在创业板上市招股说明书.pdf",
            "招股说明书",
            prospectus_year,
        )
    )

    title = latest_quarter["cleanTitle"]
    if "第一季度" in title:
        quarter_label = "Q1"
        quarter_cn = "第一季度报告"
    else:
        quarter_label = "Q3"
        quarter_cn = "第三季度报告"
    quarter_year = re.search(r"(20\d{2})年", title).group(1)
    records.append(
        download_pdf(
            session,
            latest_quarter,
            PACKAGE_ROOT / "03_最新季报" / f"{quarter_year}{quarter_label}_{COMPANY}_{quarter_cn}.pdf",
            "季度报告",
            f"{quarter_year}{quarter_label}",
        )
    )

    if len(records) != 6:
        raise RuntimeError(f"Expected 6 PDFs (4 annual + 1 prospectus + 1 latest quarter), got {len(records)}")

    write_metadata(records, org_id)
    build_zip()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log("FATAL", repr(exc))
        raise
