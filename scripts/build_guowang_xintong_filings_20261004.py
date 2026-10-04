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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from pypdf import PdfReader

CODE = "600131"
COMPANY = "国网信通"
FULL_COMPANY = "国网信息通信股份有限公司"
AS_OF = "2026-10-04"
EXPECTED_ANNUAL_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
ORG_ID = "gssh0600131"

ROOT = Path(f"{COMPANY}_{CODE}_官方披露文件")
ANNUAL_DIR = ROOT / "01_年度报告"
QUARTER_DIR = ROOT / "02_最新季报"
VERIFY_DIR = Path("_verify_guowang_xintong")
ZIP_NAME = f"{COMPANY}_{CODE}_2020-2025年报_2026最新季报.zip"

for directory in (ANNUAL_DIR, QUARTER_DIR, VERIFY_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/152.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.cninfo.com.cn",
        "Referer": "https://www.cninfo.com.cn/",
    }
)


def clean_title(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value or "")
    value = html.unescape(value).replace("\u3000", " ")
    return re.sub(r"\s+", "", value).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request_with_retry(method: str, url: str, **kwargs: Any) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = SESSION.request(method, url, timeout=(20, 180), **kwargs)
            print(
                "HTTP",
                attempt,
                response.status_code,
                response.headers.get("content-type"),
                len(response.content),
                response.url,
                flush=True,
            )
            if response.status_code in {429, 500, 502, 503, 504}:
                time.sleep(attempt * 2)
                continue
            response.raise_for_status()
            return response
        except Exception as exc:
            last_error = exc
            if attempt < 5:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Request failed after retries: {method} {url}: {last_error}")


def query_announcements() -> list[dict[str, Any]]:
    endpoint = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    SESSION.headers["Referer"] = (
        f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={CODE}&orgId={ORG_ID}"
    )
    rows_all: list[dict[str, Any]] = []
    seen: set[str] = set()
    windows = [
        ("2020-01-01", "2020-12-31"),
        ("2021-01-01", "2021-12-31"),
        ("2022-01-01", "2022-12-31"),
        ("2023-01-01", "2023-12-31"),
        ("2024-01-01", "2024-12-31"),
        ("2025-01-01", "2025-12-31"),
        ("2026-01-01", AS_OF),
    ]
    for start_date, end_date in windows:
        page = 1
        while True:
            payload = {
                "pageNum": str(page),
                "pageSize": "30",
                "column": "sse",
                "tabName": "fulltext",
                "plate": "sh",
                "stock": f"{CODE},{ORG_ID}",
                "searchkey": "",
                "secid": "",
                "category": "",
                "trade": "",
                "seDate": f"{start_date}~{end_date}",
                "sortName": "time",
                "sortType": "desc",
                "isHLtitle": "true",
            }
            response = request_with_retry("POST", endpoint, data=payload)
            data = response.json()
            rows = data.get("announcements") or []
            total = int(data.get("totalAnnouncement") or 0)
            print("QUERY", start_date, end_date, page, len(rows), total, flush=True)
            if not rows:
                break
            for row in rows:
                identity = str(row.get("announcementId") or row.get("adjunctUrl") or "")
                if not identity or identity in seen:
                    continue
                seen.add(identity)
                normalized = dict(row)
                normalized["cleanTitle"] = clean_title(str(row.get("announcementTitle") or ""))
                rows_all.append(normalized)
            if page * 30 >= total:
                break
            page += 1
            if page > 30:
                raise RuntimeError(f"Unexpectedly many pages for {start_date} to {end_date}")
            time.sleep(0.2)

    print("ANNOUNCEMENT_COUNT", len(rows_all), flush=True)
    for row in sorted(rows_all, key=lambda item: int(item.get("announcementTime") or 0)):
        title = row["cleanTitle"]
        if any(keyword in title for keyword in ("年度报告", "季度报告")):
            date = datetime.fromtimestamp(
                int(row.get("announcementTime") or 0) / 1000,
                tz=timezone.utc,
            ).date()
            print("CANDIDATE", date, title, row.get("adjunctUrl"), row.get("adjunctSize"), flush=True)
    return rows_all


def announcement_time(row: dict[str, Any]) -> int:
    try:
        return int(row.get("announcementTime") or 0)
    except Exception:
        return 0


def publication_date(row: dict[str, Any]) -> str:
    value = announcement_time(row)
    if value <= 0:
        return ""
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def is_pdf(row: dict[str, Any]) -> bool:
    return str(row.get("adjunctUrl") or "").lower().endswith(".pdf")


def choose_documents(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    annual_excludes = (
        "摘要",
        "英文版",
        "提示性公告",
        "关于",
        "审计报告",
        "持续督导",
        "问询",
        "回复",
    )
    for year in EXPECTED_ANNUAL_YEARS:
        key = f"{year}年年度报告"
        candidates = [
            row
            for row in rows
            if is_pdf(row)
            and key in row["cleanTitle"]
            and not any(excluded in row["cleanTitle"] for excluded in annual_excludes)
        ]
        if not candidates:
            raise RuntimeError(f"Missing annual report candidate for {year}")
        candidates.sort(key=announcement_time, reverse=True)
        selected = dict(candidates[0])
        selected["document_type"] = "年度报告"
        selected["report_year"] = year
        chosen.append(selected)
        print("SELECT_ANNUAL", year, selected["cleanTitle"], selected.get("adjunctUrl"), flush=True)

    quarter_excludes = ("提示性公告", "更正公告", "关于", "审阅报告", "英文版")
    quarter_candidates = [
        row
        for row in rows
        if is_pdf(row)
        and re.search(r"20\d{2}年(?:第一|第三|一|三)季度报告", row["cleanTitle"])
        and not any(excluded in row["cleanTitle"] for excluded in quarter_excludes)
    ]
    if not quarter_candidates:
        raise RuntimeError("Missing quarterly report candidate")
    quarter_candidates.sort(key=announcement_time, reverse=True)
    latest_quarter = dict(quarter_candidates[0])
    latest_quarter["document_type"] = "最新季报"
    latest_quarter["report_year"] = None
    chosen.append(latest_quarter)
    print("SELECT_QUARTER", latest_quarter["cleanTitle"], latest_quarter.get("adjunctUrl"), flush=True)
    return chosen


def destination_for(row: dict[str, Any]) -> Path:
    if row["document_type"] == "年度报告":
        year = int(row["report_year"])
        return ANNUAL_DIR / f"{year}_{COMPANY}_年度报告_巨潮资讯官方.pdf"
    title = row["cleanTitle"]
    match = re.search(r"(20\d{2})年(第一|第三|一|三)季度报告", title)
    if match:
        year, quarter_cn = match.groups()
        quarter = "Q1" if quarter_cn in ("第一", "一") else "Q3"
        return QUARTER_DIR / f"{year}_{quarter}_{COMPANY}_{quarter_cn}季度报告_巨潮资讯官方.pdf"
    return QUARTER_DIR / f"{publication_date(row)[:4]}_{COMPANY}_最新季度报告_巨潮资讯官方.pdf"


def download_document(row: dict[str, Any], destination: Path) -> str:
    adjunct = str(row.get("adjunctUrl") or "").lstrip("/")
    url = urljoin("https://static.cninfo.com.cn/", adjunct)
    response = request_with_retry(
        "GET",
        url,
        headers={
            "Accept": "application/pdf,application/octet-stream,*/*",
            "Referer": "https://www.cninfo.com.cn/",
        },
    )
    content = response.content
    if not content.startswith(b"%PDF"):
        raise RuntimeError(f"Downloaded object is not PDF: {destination.name}: {content[:20]!r}")
    if len(content) < 50_000:
        raise RuntimeError(f"Suspiciously small PDF: {destination.name}: {len(content)} bytes")
    destination.write_bytes(content)
    return url


def validate_pdf(path: Path) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 5:
        raise RuntimeError(f"Too few pages for {path.name}: {pages}")

    sample_indices = sorted(set([0, 1, 2, max(0, pages - 1)]))
    sample_parts: list[str] = []
    for index in sample_indices:
        try:
            sample_parts.append(reader.pages[index].extract_text() or "")
        except Exception:
            pass
    sample_text = "\n".join(sample_parts).lower()
    identity_terms = (
        "国网信通",
        "国网信息通信",
        "600131",
        "state grid information",
        "state grid information & communication",
    )
    identity_ok = any(term.lower() in sample_text for term in identity_terms)
    if len(sample_text.strip()) > 250 and not identity_ok:
        raise RuntimeError(f"Company identity not found in extractable sample: {path.name}")

    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(
            f"qpdf check failed for {path.name}: rc={qpdf.returncode}\n{qpdf.stdout}\n{qpdf.stderr}"
        )

    for page_number, suffix in ((1, "first"), (pages, "last")):
        output_base = VERIFY_DIR / f"{path.stem}_{suffix}"
        result = subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-r",
                "72",
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-singlefile",
                str(path),
                str(output_base),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        png_path = Path(str(output_base) + ".png")
        if result.returncode != 0 or not png_path.exists() or png_path.stat().st_size < 1000:
            raise RuntimeError(f"Render failed for {path.name} page {page_number}: {result.stderr}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "first_last_page_rendered": True,
        "identity_text_verified_when_extractable": bool(identity_ok or len(sample_text.strip()) <= 250),
    }


def main() -> None:
    rows = query_announcements()
    documents = choose_documents(rows)
    records: list[dict[str, Any]] = []

    for row in documents:
        destination = destination_for(row)
        source_url = download_document(row, destination)
        validation = validate_pdf(destination)
        record = {
            "relative_path": destination.relative_to(ROOT).as_posix(),
            "filename": destination.name,
            "title": row["cleanTitle"],
            "document_type": row["document_type"],
            "report_year": row.get("report_year"),
            "publication_date": publication_date(row),
            "source": "巨潮资讯网（中国证监会指定上市公司信息披露平台）",
            "source_url": source_url,
            "announcement_id": str(row.get("announcementId") or ""),
            **validation,
        }
        records.append(record)
        print("REGISTERED", json.dumps(record, ensure_ascii=False), flush=True)

    annual_years = sorted(
        int(record["report_year"])
        for record in records
        if record["document_type"] == "年度报告"
    )
    if annual_years != EXPECTED_ANNUAL_YEARS:
        raise RuntimeError(f"Unexpected annual-report years: {annual_years}")
    if sum(record["document_type"] == "最新季报" for record in records) != 1:
        raise RuntimeError("Expected exactly one latest quarterly report")

    explanation = f"""{FULL_COMPANY}（证券简称：{COMPANY}；证券代码：{CODE}）官方披露文件包

资料截止日期：{AS_OF}

收录范围：
1. 2020—2025年度完整年度报告，共6份。
2. 截至资料截止日最新已披露、严格意义上的季度报告，共1份。

口径说明：
- 年度报告采用完整报告正文，不收录摘要、英文版、提示性公告或单独审计附件。
- “最新季报”按A股严格季度报告口径选择，不以半年度报告替代季度报告。
- 截至{AS_OF}，2026年第三季度报告尚未披露，因此收录2026年第一季度报告。

来源：巨潮资讯网官方原始PDF。
校验：PDF文件头、实际页数、qpdf结构、首末页渲染、公司身份信息（可提取时）及ZIP CRC完整性。
"""
    (ROOT / "00_文件清单与范围说明.txt").write_text(explanation, encoding="utf-8")

    csv_path = ROOT / "文件清单.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "relative_path",
            "title",
            "document_type",
            "report_year",
            "publication_date",
            "pages",
            "bytes",
            "sha256",
            "source",
            "source_url",
            "announcement_id",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "company": FULL_COMPANY,
        "short_name": COMPANY,
        "stock_code": CODE,
        "as_of": AS_OF,
        "scope": "2020-2025完整年度报告及截至当前最新严格季度报告",
        "documents": records,
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{record['sha256']}  {record['relative_path']}" for record in records) + "\n",
        encoding="utf-8",
    )

    zip_path = Path(ZIP_NAME)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=f"{ROOT.name}/{path.relative_to(ROOT).as_posix()}")

    with zipfile.ZipFile(zip_path, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC test failed at {bad}")
        pdf_count = sum(name.lower().endswith(".pdf") for name in archive.namelist())
        if pdf_count != len(records):
            raise RuntimeError(f"ZIP PDF count mismatch: {pdf_count} != {len(records)}")

    print("FINAL_ZIP", zip_path.name, zip_path.stat().st_size, sha256_file(zip_path), flush=True)
    print("FINAL_RECORDS", json.dumps(records, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
