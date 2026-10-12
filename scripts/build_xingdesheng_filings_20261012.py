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

COMPANY = "星德胜"
FULL_COMPANY = "星德胜科技（苏州）股份有限公司"
CODE = "603344"
AS_OF = "2026-10-12"
EXPECTED_ANNUAL_YEARS = [2023, 2024, 2025]

ROOT = Path(f"{COMPANY}_{CODE}_官方披露文件")
ANNUAL_DIR = ROOT / "01_年度报告"
PROSPECTUS_DIR = ROOT / "02_招股说明书"
QUARTER_DIR = ROOT / "03_最新季报"
VERIFY_DIR = Path("_verify_xingdesheng_filings")
ZIP_PATH = Path(f"{COMPANY}_{CODE}_全部年报_招股说明书_最新季报_截至20261012.zip")

for directory in (ANNUAL_DIR, PROSPECTUS_DIR, QUARTER_DIR, VERIFY_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "application/json,text/plain,*/*",
        "Origin": "https://www.cninfo.com.cn",
        "Referer": "https://www.cninfo.com.cn/",
        "X-Requested-With": "XMLHttpRequest",
    }
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_title(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value or "")
    value = html.unescape(value).replace("\u3000", " ")
    return re.sub(r"\s+", "", value).strip()


def request(method: str, url: str, **kwargs: Any) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = SESSION.request(method, url, timeout=(20, 180), allow_redirects=True, **kwargs)
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


def find_org_id() -> str:
    for warm_url in ("https://www.cninfo.com.cn/new/disclosure", "https://www.cninfo.com.cn/"):
        try:
            warm = SESSION.get(warm_url, timeout=(20, 60))
            print("WARM", warm.status_code, warm.url, len(warm.content), flush=True)
        except Exception as exc:
            print("WARM_FAILED", warm_url, repr(exc), flush=True)

    endpoints = (
        "https://www.cninfo.com.cn/new/information/topSearch/detailOfQuery",
        "https://www.cninfo.com.cn/new/information/topSearch/query",
    )
    payloads = (
        {"keyWord": CODE, "maxSecNum": "20", "maxListNum": "10"},
        {"keyWord": CODE, "maxNum": "20"},
        {"keyWord": COMPANY, "maxSecNum": "20", "maxListNum": "10"},
    )

    def walk(value: Any) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        if isinstance(value, dict):
            if any(key in value for key in ("orgId", "orgid", "org_id")):
                found.append(value)
            for child in value.values():
                found.extend(walk(child))
        elif isinstance(value, list):
            for child in value:
                found.extend(walk(child))
        return found

    for endpoint in endpoints:
        for payload in payloads:
            try:
                response = request(
                    "POST",
                    endpoint,
                    data=payload,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "Accept": "application/json,text/plain,*/*",
                        "Referer": "https://www.cninfo.com.cn/new/disclosure",
                    },
                )
                data = response.json()
                print("ORG_RESOLVER", endpoint, json.dumps(data, ensure_ascii=False)[:3000], flush=True)
                for item in walk(data):
                    code = str(item.get("code") or item.get("secCode") or item.get("stockCode") or "")
                    name = str(item.get("zwjc") or item.get("secName") or item.get("name") or "")
                    org_id = str(item.get("orgId") or item.get("orgid") or item.get("org_id") or "")
                    if org_id and (code == CODE or COMPANY in name or "星德胜" in name):
                        print("ORG_ID", org_id, item, flush=True)
                        return org_id
            except Exception as exc:
                print("ORG_RESOLVER_FAILED", endpoint, payload, repr(exc), flush=True)
    raise RuntimeError(f"Unable to resolve CNINFO orgId for {CODE}")


def query_announcements(org_id: str) -> list[dict[str, Any]]:
    endpoint = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    SESSION.headers["Referer"] = (
        f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={CODE}&orgId={org_id}"
    )
    windows = [
        ("2022-01-01", "2022-12-31"),
        ("2023-01-01", "2023-12-31"),
        ("2024-01-01", "2024-12-31"),
        ("2025-01-01", "2025-12-31"),
        ("2026-01-01", AS_OF),
    ]
    all_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for start_date, end_date in windows:
        page = 1
        while True:
            payload = {
                "pageNum": str(page),
                "pageSize": "30",
                "column": "sse",
                "tabName": "fulltext",
                "plate": "sh",
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
            response = request("POST", endpoint, data=payload)
            data = response.json()
            rows = data.get("announcements") or []
            total = int(data.get("totalAnnouncement") or 0)
            print("QUERY", start_date, end_date, page, len(rows), total, flush=True)
            if not rows:
                break
            for row in rows:
                ident = str(row.get("announcementId") or row.get("adjunctUrl") or "")
                if ident and ident not in seen:
                    seen.add(ident)
                    item = dict(row)
                    item["cleanTitle"] = clean_title(str(row.get("announcementTitle") or ""))
                    all_rows.append(item)
            if page * 30 >= total:
                break
            page += 1
            if page > 60:
                raise RuntimeError(f"Unexpectedly many announcement pages in {start_date[:4]}")
            time.sleep(0.25)

    print("ANNOUNCEMENT_COUNT", len(all_rows), flush=True)
    for row in sorted(all_rows, key=lambda item: int(item.get("announcementTime") or 0)):
        title = row["cleanTitle"]
        if any(keyword in title for keyword in ("年度报告", "季度报告", "招股说明书")):
            print("CANDIDATE", title, row.get("adjunctUrl"), row.get("adjunctSize"), flush=True)
    return all_rows


def ann_time(row: dict[str, Any]) -> int:
    try:
        return int(row.get("announcementTime") or 0)
    except Exception:
        return 0


def is_pdf(row: dict[str, Any]) -> bool:
    return str(row.get("adjunctUrl") or "").lower().endswith(".pdf")


def publication_date(row: dict[str, Any]) -> str:
    adjunct = str(row.get("adjunctUrl") or "")
    match = re.search(r"finalpage/(20\d{2}-\d{2}-\d{2})/", adjunct)
    if match:
        return match.group(1)
    value = ann_time(row)
    if value <= 0:
        return ""
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def replacement_score(title: str) -> int:
    return 100 if any(word in title for word in ("更正后", "更新后", "修订后", "修订版", "更新版")) else 0


def select_documents(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    annual_excludes = (
        "摘要", "英文版", "提示性公告", "更正公告", "补充公告", "关于",
        "审计报告", "持续督导", "问询函", "回复",
    )
    for year in EXPECTED_ANNUAL_YEARS:
        key = f"{year}年年度报告"
        candidates = [
            row for row in rows
            if is_pdf(row)
            and key in row["cleanTitle"]
            and not any(excluded in row["cleanTitle"] for excluded in annual_excludes)
        ]
        if not candidates:
            raise RuntimeError(f"Missing annual report for {year}")
        candidates.sort(
            key=lambda row: (replacement_score(row["cleanTitle"]), ann_time(row)),
            reverse=True,
        )
        chosen = dict(candidates[0])
        chosen["kind"] = "年度报告"
        chosen["report_year"] = year
        selected.append(chosen)
        print("SELECT_ANNUAL", year, chosen["cleanTitle"], chosen.get("adjunctUrl"), flush=True)

    prospectus_excludes = (
        "摘要", "提示性公告", "上市公告书", "发行公告", "保荐书", "法律意见书",
        "审核问询", "回复", "审核中心意见", "招股意向书", "募集说明书",
    )
    prospectuses = [
        row for row in rows
        if is_pdf(row)
        and "招股说明书" in row["cleanTitle"]
        and "首次公开发行" in row["cleanTitle"]
        and not any(excluded in row["cleanTitle"] for excluded in prospectus_excludes)
    ]
    if not prospectuses:
        raise RuntimeError("Missing IPO prospectus")

    def prospectus_score(row: dict[str, Any]) -> tuple[int, int, int]:
        title = row["cleanTitle"]
        score = 0
        if "主板上市招股说明书" in title:
            score += 200
        if "首次公开发行股票并在主板上市招股说明书" in title:
            score += 200
        if any(marker in title for marker in ("申报稿", "上会稿", "注册稿", "预披露")):
            score -= 200
        try:
            size = int(row.get("adjunctSize") or 0)
        except Exception:
            size = 0
        return score, ann_time(row), size

    prospectuses.sort(key=prospectus_score, reverse=True)
    prospectus = dict(prospectuses[0])
    prospectus["kind"] = "招股说明书"
    selected.append(prospectus)
    print("SELECT_PROSPECTUS", prospectus["cleanTitle"], prospectus.get("adjunctUrl"), flush=True)

    quarter_excludes = ("提示性公告", "更正公告", "补充公告", "关于", "审阅报告", "英文版")
    quarter_pattern = re.compile(r"20\d{2}年(?:第一|第三|一|三)季度报告")
    quarters = [
        row for row in rows
        if is_pdf(row)
        and quarter_pattern.search(row["cleanTitle"])
        and not any(excluded in row["cleanTitle"] for excluded in quarter_excludes)
    ]
    if not quarters:
        raise RuntimeError("Missing strict quarterly report")
    quarters.sort(key=lambda row: (ann_time(row), replacement_score(row["cleanTitle"])), reverse=True)
    quarter = dict(quarters[0])
    quarter["kind"] = "最新季报"
    selected.append(quarter)
    print("SELECT_QUARTER", quarter["cleanTitle"], quarter.get("adjunctUrl"), flush=True)
    return selected


def destination_for(row: dict[str, Any]) -> Path:
    title = row["cleanTitle"]
    if row["kind"] == "年度报告":
        year = int(row["report_year"])
        suffix = "_更正或更新版" if replacement_score(title) else ""
        return ANNUAL_DIR / f"{year}_{COMPANY}_年度报告{suffix}_巨潮资讯官方.pdf"
    if row["kind"] == "招股说明书":
        return PROSPECTUS_DIR / f"2024_{COMPANY}_首次公开发行股票并在主板上市招股说明书_巨潮资讯官方.pdf"
    match = re.search(r"(20\d{2})年(第一|第三|一|三)季度报告", title)
    if match:
        year, quarter_zh = match.groups()
        q = "Q1" if quarter_zh in ("第一", "一") else "Q3"
        return QUARTER_DIR / f"{year}_{q}_{COMPANY}_{quarter_zh}季度报告_巨潮资讯官方.pdf"
    return QUARTER_DIR / f"{publication_date(row)[:4]}_{COMPANY}_最新季度报告_巨潮资讯官方.pdf"


def download_pdf(row: dict[str, Any], destination: Path) -> str:
    adjunct = str(row.get("adjunctUrl") or "").lstrip("/")
    url = urljoin("https://static.cninfo.com.cn/", adjunct)
    response = request(
        "GET",
        url,
        headers={"Accept": "application/pdf,application/octet-stream,*/*", "Referer": "https://www.cninfo.com.cn/"},
    )
    content = response.content
    if not content.startswith(b"%PDF"):
        raise RuntimeError(f"Not a PDF: {destination.name}: {content[:20]!r}")
    if len(content) < 50_000:
        raise RuntimeError(f"Suspiciously small PDF: {destination.name}: {len(content)}")
    destination.write_bytes(content)
    return url


def validate_pdf(path: Path, kind: str) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    minimum = 100 if kind == "招股说明书" else 50 if kind == "年度报告" else 5
    if pages < minimum:
        raise RuntimeError(f"Too few pages for {kind}: {path.name}: {pages}")

    text_parts: list[str] = []
    for index in sorted(set([0, 1, min(2, pages - 1), pages - 1])):
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception:
            pass
    sample = "\n".join(text_parts).lower()
    identity_ok = any(term.lower() in sample for term in ("星德胜", "603344", "star electric", "xingdesheng"))
    if len(sample.strip()) > 300 and not identity_ok:
        raise RuntimeError(f"Company identity not found in extractable sample: {path.name}")

    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=180)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {qpdf.stderr}")

    for page_number, label in ((1, "first"), (pages, "last")):
        output_base = VERIFY_DIR / f"{path.stem}_{label}"
        result = subprocess.run(
            [
                "pdftoppm", "-png", "-r", "72", "-f", str(page_number), "-l", str(page_number),
                "-singlefile", str(path), str(output_base),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        png = Path(str(output_base) + ".png")
        if result.returncode != 0 or not png.exists() or png.stat().st_size < 1000:
            raise RuntimeError(f"Render failed for {path.name} page {page_number}: {result.stderr}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "first_last_page_rendered": True,
        "identity_text_verified_when_extractable": bool(identity_ok or len(sample.strip()) <= 300),
    }


def main() -> None:
    org_id = find_org_id()
    rows = query_announcements(org_id)
    selected = select_documents(rows)

    records: list[dict[str, Any]] = []
    for row in selected:
        destination = destination_for(row)
        source_url = download_pdf(row, destination)
        metadata = validate_pdf(destination, row["kind"])
        record = {
            "relative_path": destination.relative_to(ROOT).as_posix(),
            "filename": destination.name,
            "title": row["cleanTitle"],
            "document_type": row["kind"],
            "publication_date": publication_date(row),
            "source": "巨潮资讯网（法定信息披露平台）",
            "source_url": source_url,
            "announcement_id": str(row.get("announcementId") or ""),
            **metadata,
        }
        records.append(record)
        print("REGISTERED", json.dumps(record, ensure_ascii=False), flush=True)

    annual_years = sorted(
        int(re.search(r"(20\d{2})", record["filename"]).group(1))
        for record in records
        if record["document_type"] == "年度报告"
    )
    if annual_years != EXPECTED_ANNUAL_YEARS:
        raise RuntimeError(f"Unexpected annual-report years: {annual_years}")
    if sum(record["document_type"] == "招股说明书" for record in records) != 1:
        raise RuntimeError("Expected exactly one final IPO prospectus")
    if sum(record["document_type"] == "最新季报" for record in records) != 1:
        raise RuntimeError("Expected exactly one latest strict quarterly report")

    latest_quarter = next(record for record in records if record["document_type"] == "最新季报")
    readme = f"""{FULL_COMPANY}（证券简称：{COMPANY}；证券代码：{CODE}）官方披露文件包

资料截止日期：{AS_OF}
上市日期：2024-03-20

收录范围：
1. 上市后已披露的全部完整年度报告：2023、2024、2025年度。
2. 首次公开发行股票并在上海证券交易所主板上市的最终完整招股说明书。
3. 截至资料截止日最新已披露、严格意义上的季度报告：{latest_quarter['title']}。

排除范围：年度报告摘要、提示性公告、业绩预告、业绩快报、单独审计附件、英文版及被后续版本替代的旧文件。

来源：巨潮资讯网官方原始PDF。
校验：PDF文件头、实际页数、qpdf结构、首末页渲染、公司身份信息（可提取时）和ZIP完整性。
"""
    (ROOT / "00_文件清单与范围说明.txt").write_text(readme, encoding="utf-8")

    with (ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = [
            "relative_path", "title", "document_type", "publication_date", "pages", "bytes",
            "sha256", "source", "source_url", "announcement_id",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "company": FULL_COMPANY,
        "short_name": COMPANY,
        "stock_code": CODE,
        "as_of": AS_OF,
        "listing_date": "2024-03-20",
        "scope": "上市后全部年报、最终IPO招股说明书、截至当前最新严格季度报告",
        "documents": records,
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{record['sha256']}  {record['relative_path']}" for record in records) + "\n",
        encoding="utf-8",
    )

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=f"{ROOT.name}/{path.relative_to(ROOT).as_posix()}")

    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failed at {bad}")
        pdf_count = sum(name.lower().endswith(".pdf") for name in archive.namelist())
        if pdf_count != len(records):
            raise RuntimeError(f"ZIP PDF count mismatch: {pdf_count} != {len(records)}")

    print("FINAL_ZIP", ZIP_PATH.name, ZIP_PATH.stat().st_size, sha256_file(ZIP_PATH), flush=True)
    print("RECORDS", json.dumps(records, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
