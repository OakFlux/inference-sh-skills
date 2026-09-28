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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from pypdf import PdfReader

CODE = "301301"
COMPANY = "川宁生物"
FULL_COMPANY = "伊犁川宁生物技术股份有限公司"
AS_OF = "2026-09-28"
LISTING_YEAR = 2022
EXPECTED_ANNUAL_YEARS = [2022, 2023, 2024, 2025]

ROOT = Path(f"{COMPANY}_{CODE}_官方披露文件")
ANNUAL_DIR = ROOT / "01_年度报告"
PROSPECTUS_DIR = ROOT / "02_招股说明书"
QUARTER_DIR = ROOT / "03_最新季报"
VERIFY_DIR = Path("_verify_chuanning")
ZIP_NAME = f"{COMPANY}_{CODE}_2022-2025全部年报_招股说明书_2026最新季报.zip"

for d in (ANNUAL_DIR, PROSPECTUS_DIR, QUARTER_DIR, VERIFY_DIR):
    d.mkdir(parents=True, exist_ok=True)

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
    value = html.unescape(value)
    value = value.replace("\u3000", " ")
    return re.sub(r"\s+", "", value).strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def request_with_retry(method: str, url: str, **kwargs: Any) -> requests.Response:
    last: Exception | None = None
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
            last = exc
            if attempt == 5:
                break
            time.sleep(attempt * 2)
    raise RuntimeError(f"Request failed after retries: {method} {url}: {last}")


def find_org_id() -> str:
    # Warm the session and then use the official CNINFO search endpoint.
    try:
        SESSION.get("https://www.cninfo.com.cn/", timeout=(20, 60))
    except Exception:
        pass

    urls = [
        f"https://www.cninfo.com.cn/new/information/topSearch/query?keyWord={CODE}&maxNum=20",
        f"https://www.cninfo.com.cn/new/information/topSearch/query?keyWord={COMPANY}&maxNum=20",
    ]
    for url in urls:
        response = request_with_retry("GET", url)
        data = response.json()
        print("TOP_SEARCH", json.dumps(data, ensure_ascii=False)[:3000], flush=True)

        candidates: list[dict[str, Any]] = []

        def walk(obj: Any) -> None:
            if isinstance(obj, dict):
                if any(k in obj for k in ("orgId", "orgid", "org_id")):
                    candidates.append(obj)
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(data)
        for item in candidates:
            code = str(item.get("code") or item.get("secCode") or item.get("stockCode") or "")
            name = str(item.get("zwjc") or item.get("secName") or item.get("name") or "")
            org_id = str(item.get("orgId") or item.get("orgid") or item.get("org_id") or "")
            if org_id and (code == CODE or COMPANY in name or "川宁" in name):
                print("ORG_ID", org_id, item, flush=True)
                return org_id
    raise RuntimeError("Unable to resolve CNINFO orgId for 301301")


def query_announcements(org_id: str) -> list[dict[str, Any]]:
    endpoint = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    SESSION.headers["Referer"] = (
        f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={CODE}&orgId={org_id}"
    )
    all_rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    # Smaller date windows are more reliable than one broad query and avoid server-side caps.
    windows = [
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
                "pageSize": "100",
                "column": "szse",
                "tabName": "fulltext",
                "plate": "sz",
                "stock": f"{CODE},{org_id}",
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
                ident = str(row.get("announcementId") or row.get("adjunctUrl") or "")
                if ident and ident not in seen_ids:
                    seen_ids.add(ident)
                    row = dict(row)
                    row["cleanTitle"] = clean_title(str(row.get("announcementTitle") or ""))
                    all_rows.append(row)
            if page * 100 >= total:
                break
            page += 1
            if page > 20:
                raise RuntimeError(f"Unexpectedly many CNINFO pages for {start_date}")
            time.sleep(0.25)

    print("ANNOUNCEMENT_COUNT", len(all_rows), flush=True)
    for row in sorted(all_rows, key=lambda x: int(x.get("announcementTime") or 0)):
        title = row["cleanTitle"]
        if any(k in title for k in ("年度报告", "季度报告", "招股说明书")):
            print(
                "CANDIDATE",
                datetime.fromtimestamp(int(row.get("announcementTime") or 0) / 1000, tz=timezone.utc).date(),
                title,
                row.get("adjunctUrl"),
                row.get("adjunctSize"),
                flush=True,
            )
    return all_rows


def ann_time(row: dict[str, Any]) -> int:
    try:
        return int(row.get("announcementTime") or 0)
    except Exception:
        return 0


def is_pdf(row: dict[str, Any]) -> bool:
    return str(row.get("adjunctUrl") or "").lower().endswith(".pdf")


def choose_documents(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []

    annual_excludes = ("摘要", "英文版", "取消", "关于", "提示性公告", "审计报告")
    for year in EXPECTED_ANNUAL_YEARS:
        key = f"{year}年年度报告"
        candidates = [
            r
            for r in rows
            if is_pdf(r)
            and key in r["cleanTitle"]
            and not any(x in r["cleanTitle"] for x in annual_excludes)
        ]
        if not candidates:
            raise RuntimeError(f"Missing annual report candidate for {year}")
        candidates.sort(key=ann_time, reverse=True)
        chosen = candidates[0]
        chosen = dict(chosen)
        chosen["kind"] = "年度报告"
        chosen["report_year"] = year
        selected.append(chosen)
        print("SELECT_ANNUAL", year, chosen["cleanTitle"], chosen.get("adjunctUrl"), flush=True)

    prospectus_excludes = (
        "提示性公告",
        "审核问询",
        "回复",
        "审核中心意见",
        "发行保荐书",
        "上市公告书",
        "法律意见书",
        "募集说明书",
        "摘要",
    )
    prospectuses = [
        r
        for r in rows
        if is_pdf(r)
        and "招股说明书" in r["cleanTitle"]
        and "首次公开发行" in r["cleanTitle"]
        and not any(x in r["cleanTitle"] for x in prospectus_excludes)
    ]
    if not prospectuses:
        # A defensive fallback in case the exchange omits the full boilerplate wording.
        prospectuses = [
            r
            for r in rows
            if is_pdf(r)
            and "招股说明书" in r["cleanTitle"]
            and not any(x in r["cleanTitle"] for x in prospectus_excludes)
        ]
    if not prospectuses:
        raise RuntimeError("Missing IPO prospectus candidate")

    def prospectus_score(r: dict[str, Any]) -> tuple[int, int, int]:
        title = r["cleanTitle"]
        score = 0
        if "首次公开发行股票并在创业板上市招股说明书" in title:
            score += 100
        if "注册稿" in title:
            score -= 20
        if "申报稿" in title:
            score -= 30
        if "正式稿" in title:
            score += 10
        try:
            size = int(r.get("adjunctSize") or 0)
        except Exception:
            size = 0
        return score, ann_time(r), size

    prospectuses.sort(key=prospectus_score, reverse=True)
    prospectus = dict(prospectuses[0])
    prospectus["kind"] = "招股说明书"
    selected.append(prospectus)
    print("SELECT_PROSPECTUS", prospectus["cleanTitle"], prospectus.get("adjunctUrl"), flush=True)

    quarter_excludes = ("提示性公告", "更正公告", "关于", "审阅报告", "英文版")
    quarters = [
        r
        for r in rows
        if is_pdf(r)
        and re.search(r"20\d{2}年(?:第一|第三)季度报告", r["cleanTitle"])
        and not any(x in r["cleanTitle"] for x in quarter_excludes)
    ]
    if not quarters:
        quarters = [
            r
            for r in rows
            if is_pdf(r)
            and "季度报告" in r["cleanTitle"]
            and not any(x in r["cleanTitle"] for x in quarter_excludes)
        ]
    if not quarters:
        raise RuntimeError("Missing quarterly report candidate")
    quarters.sort(key=ann_time, reverse=True)
    quarter = dict(quarters[0])
    quarter["kind"] = "最新季报"
    selected.append(quarter)
    print("SELECT_QUARTER", quarter["cleanTitle"], quarter.get("adjunctUrl"), flush=True)

    return selected


def publication_date(row: dict[str, Any]) -> str:
    value = ann_time(row)
    if value <= 0:
        return ""
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def destination_for(row: dict[str, Any]) -> Path:
    title = row["cleanTitle"]
    kind = row["kind"]
    if kind == "年度报告":
        year = int(row["report_year"])
        suffix = ""
        if "更正后" in title or "修订" in title or "更新后" in title:
            suffix = "_更正或更新版"
        return ANNUAL_DIR / f"{year}_{COMPANY}_年度报告{suffix}_巨潮资讯官方.pdf"
    if kind == "招股说明书":
        year_match = re.search(r"(20\d{2})", publication_date(row))
        year = year_match.group(1) if year_match else "2022"
        return PROSPECTUS_DIR / f"{year}_{COMPANY}_首次公开发行股票并在创业板上市招股说明书_巨潮资讯官方.pdf"
    quarter_match = re.search(r"(20\d{2})年(第一|第三)季度报告", title)
    if quarter_match:
        year, zh_quarter = quarter_match.groups()
        q = "Q1" if zh_quarter == "第一" else "Q3"
        return QUARTER_DIR / f"{year}_{q}_{COMPANY}_{zh_quarter}季度报告_巨潮资讯官方.pdf"
    return QUARTER_DIR / f"{publication_date(row)[:4]}_{COMPANY}_最新季度报告_巨潮资讯官方.pdf"


def download_document(row: dict[str, Any], destination: Path) -> str:
    adjunct = str(row.get("adjunctUrl") or "").lstrip("/")
    url = urljoin("https://static.cninfo.com.cn/", adjunct)
    headers = {
        "Accept": "application/pdf,application/octet-stream,*/*",
        "Referer": "https://www.cninfo.com.cn/",
    }
    response = request_with_retry("GET", url, headers=headers)
    content = response.content
    if not content.startswith(b"%PDF"):
        raise RuntimeError(
            f"Downloaded object is not a PDF: {destination.name}, header={content[:20]!r}, url={url}"
        )
    if len(content) < 50_000:
        raise RuntimeError(f"Downloaded PDF is suspiciously small: {destination.name}: {len(content)}")
    destination.write_bytes(content)
    return url


def validate_pdf(path: Path, expected_kind: str) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    min_pages = 20 if expected_kind == "招股说明书" else 5
    if pages < min_pages:
        raise RuntimeError(f"Too few pages for {path.name}: {pages}")

    text_parts: list[str] = []
    sample_indices = sorted(set([0, 1, 2, max(0, pages - 1)]))
    for idx in sample_indices:
        try:
            text_parts.append(reader.pages[idx].extract_text() or "")
        except Exception:
            pass
    sample_text = "\n".join(text_parts).lower()
    identity_terms = ("川宁", "301301", "yili chuanning", "chuanning")
    identity_ok = any(term.lower() in sample_text for term in identity_terms)
    if len(sample_text.strip()) > 200 and not identity_ok:
        raise RuntimeError(f"Identity terms not found in extractable PDF sample: {path.name}")

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

    render_base_first = VERIFY_DIR / f"{path.stem}_first"
    render_base_last = VERIFY_DIR / f"{path.stem}_last"
    for page_num, output_base in ((1, render_base_first), (pages, render_base_last)):
        result = subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-r",
                "72",
                "-f",
                str(page_num),
                "-l",
                str(page_num),
                "-singlefile",
                str(path),
                str(output_base),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        png_path = Path(str(output_base) + ".png")
        if result.returncode != 0 or not png_path.exists() or png_path.stat().st_size < 1_000:
            raise RuntimeError(
                f"Render failed for {path.name} page {page_num}: {result.stderr}"
            )

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "first_last_page_rendered": True,
        "identity_text_verified_when_extractable": bool(identity_ok or len(sample_text.strip()) <= 200),
    }


def main() -> None:
    org_id = find_org_id()
    rows = query_announcements(org_id)
    selected = choose_documents(rows)

    records: list[dict[str, Any]] = []
    for row in selected:
        destination = destination_for(row)
        source_url = download_document(row, destination)
        metadata = validate_pdf(destination, row["kind"])
        record = {
            "relative_path": destination.relative_to(ROOT).as_posix(),
            "filename": destination.name,
            "title": row["cleanTitle"],
            "document_type": row["kind"],
            "publication_date": publication_date(row),
            "source": "巨潮资讯网（深圳证券交易所法定信息披露平台）",
            "source_url": source_url,
            "announcement_id": str(row.get("announcementId") or ""),
            **metadata,
        }
        records.append(record)
        print("REGISTERED", json.dumps(record, ensure_ascii=False), flush=True)

    annual_years = sorted(
        int(re.search(r"(20\d{2})", r["filename"]).group(1))
        for r in records
        if r["document_type"] == "年度报告"
    )
    if annual_years != EXPECTED_ANNUAL_YEARS:
        raise RuntimeError(f"Unexpected annual years: {annual_years}")
    if sum(r["document_type"] == "招股说明书" for r in records) != 1:
        raise RuntimeError("Expected exactly one final IPO prospectus")
    if sum(r["document_type"] == "最新季报" for r in records) != 1:
        raise RuntimeError("Expected exactly one latest strict quarterly report")

    readme = f"""{FULL_COMPANY}（证券简称：{COMPANY}；证券代码：{CODE}）官方披露文件包

资料截止日期：{AS_OF}

收录范围：
1. 公司上市后全部完整年度报告：2022、2023、2024、2025年度。
2. 首次公开发行股票并在创业板上市的最终完整招股说明书。
3. 截至资料截止日最新已披露、严格意义上的季度报告。A股2026年第三季度报告尚未到法定披露期，因此本包收录2026年第一季度报告。

排除范围：年度报告摘要、提示性公告、业绩预告、业绩快报、单独审计附件、英文版及重复旧版本。

来源：巨潮资讯网（深圳证券交易所法定信息披露平台）官方原始PDF。
校验：PDF文件头、实际页数、qpdf结构、首末页渲染、公司身份信息（可提取时）和ZIP完整性。
"""
    (ROOT / "00_文件清单与范围说明.txt").write_text(readme, encoding="utf-8")

    csv_path = ROOT / "文件清单.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        fieldnames = [
            "relative_path",
            "title",
            "document_type",
            "publication_date",
            "pages",
            "bytes",
            "sha256",
            "source",
            "source_url",
            "announcement_id",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "company": FULL_COMPANY,
        "short_name": COMPANY,
        "stock_code": CODE,
        "as_of": AS_OF,
        "scope": "2022-2025全部年报、最终IPO招股说明书、截至当前最新严格季度报告",
        "documents": records,
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    checksum_lines = [f"{r['sha256']}  {r['relative_path']}" for r in records]
    (ROOT / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    zip_path = Path(ZIP_NAME)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=f"{ROOT.name}/{path.relative_to(ROOT).as_posix()}")
    with zipfile.ZipFile(zip_path, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC test failed at {bad}")
        names = zf.namelist()
        pdf_count = sum(name.lower().endswith(".pdf") for name in names)
        if pdf_count != len(records):
            raise RuntimeError(f"ZIP PDF count mismatch: {pdf_count} != {len(records)}")

    print(
        "FINAL_ZIP",
        zip_path.name,
        zip_path.stat().st_size,
        sha256_file(zip_path),
        flush=True,
    )
    print("RECORDS", json.dumps(records, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
