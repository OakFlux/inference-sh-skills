from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from pypdf import PdfReader

CODE = "605011"
COMPANY = "杭州热电"
FULL_COMPANY = "杭州热电集团股份有限公司"
AS_OF = "2026-10-04"
EXPECTED_ANNUAL_YEARS = [2021, 2022, 2023, 2024, 2025]
ORG_ID = "gssh0605011"

ROOT = Path(f"{COMPANY}_{CODE}_官方披露文件")
ANNUAL_DIR = ROOT / "01_年度报告"
PROSPECTUS_DIR = ROOT / "02_招股说明书"
QUARTER_DIR = ROOT / "03_最新季报"
VERIFY_DIR = Path("_verify_hangzhou_thermal")
ZIP_NAME = f"{COMPANY}_{CODE}_全部年报_招股说明书_2026最新季报.zip"

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
    value = html.unescape(value).replace("\u3000", " ")
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
            if attempt < 5:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Request failed after retries: {method} {url}: {last}")


def query_announcements() -> list[dict[str, Any]]:
    endpoint = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    SESSION.headers["Referer"] = (
        f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={CODE}&orgId={ORG_ID}"
    )
    try:
        SESSION.get("https://www.cninfo.com.cn/", timeout=(20, 60))
    except Exception:
        pass

    windows = [
        ("2020-01-01", "2020-12-31"),
        ("2021-01-01", "2021-12-31"),
        ("2022-01-01", "2022-12-31"),
        ("2023-01-01", "2023-12-31"),
        ("2024-01-01", "2024-12-31"),
        ("2025-01-01", "2025-12-31"),
        ("2026-01-01", AS_OF),
    ]
    rows: list[dict[str, Any]] = []
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
            batch = data.get("announcements") or []
            total = int(data.get("totalAnnouncement") or 0)
            print("QUERY", start_date, end_date, page, len(batch), total, flush=True)
            if not batch:
                break
            for raw in batch:
                ident = str(raw.get("announcementId") or raw.get("adjunctUrl") or "")
                if not ident or ident in seen:
                    continue
                seen.add(ident)
                item = dict(raw)
                item["cleanTitle"] = clean_title(str(item.get("announcementTitle") or ""))
                rows.append(item)
            if page * 30 >= total:
                break
            page += 1
            if page > 30:
                raise RuntimeError(f"Unexpected CNINFO pagination for {start_date}")
            time.sleep(0.2)

    print("ANNOUNCEMENT_COUNT", len(rows), flush=True)
    for row in sorted(rows, key=lambda x: int(x.get("announcementTime") or 0)):
        title = row["cleanTitle"]
        if any(term in title for term in ("年度报告", "季度报告", "招股说明书")):
            print(
                "CANDIDATE",
                publication_date(row),
                title,
                row.get("adjunctUrl"),
                row.get("adjunctSize"),
                flush=True,
            )
    return rows


def ann_time(row: dict[str, Any]) -> int:
    try:
        return int(row.get("announcementTime") or 0)
    except Exception:
        return 0


def publication_date(row: dict[str, Any]) -> str:
    value = ann_time(row)
    if value <= 0:
        return ""
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def is_pdf(row: dict[str, Any]) -> bool:
    return str(row.get("adjunctUrl") or "").lower().endswith(".pdf")


def choose_documents(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []

    annual_excludes = ("摘要", "英文版", "提示性公告", "关于", "问询", "审计报告")
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
        candidates.sort(
            key=lambda r: (
                1 if any(x in r["cleanTitle"] for x in ("更正后", "修订版", "更新后")) else 0,
                ann_time(r),
                int(r.get("adjunctSize") or 0),
            ),
            reverse=True,
        )
        chosen = dict(candidates[0])
        chosen["kind"] = "年度报告"
        chosen["report_year"] = year
        selected.append(chosen)
        print("SELECT_ANNUAL", year, chosen["cleanTitle"], chosen.get("adjunctUrl"), flush=True)

    prospectus_excludes = (
        "摘要",
        "上市公告书",
        "问询",
        "回复",
        "审核",
        "保荐书",
        "法律意见书",
        "募集说明书",
        "提示性公告",
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
        prospectuses = [
            r
            for r in rows
            if is_pdf(r)
            and "招股说明书" in r["cleanTitle"]
            and not any(x in r["cleanTitle"] for x in prospectus_excludes)
        ]
    if not prospectuses:
        raise RuntimeError("Missing final IPO prospectus candidate")
    prospectuses.sort(
        key=lambda r: (
            1 if "首次公开发行股票招股说明书" in r["cleanTitle"] else 0,
            int(r.get("adjunctSize") or 0),
            ann_time(r),
        ),
        reverse=True,
    )
    prospectus = dict(prospectuses[0])
    prospectus["kind"] = "招股说明书"
    selected.append(prospectus)
    print("SELECT_PROSPECTUS", prospectus["cleanTitle"], prospectus.get("adjunctUrl"), flush=True)

    quarter_excludes = ("提示性公告", "更正公告", "关于", "审阅报告", "英文版", "正文")
    quarters = [
        r
        for r in rows
        if is_pdf(r)
        and re.search(r"20\d{2}年(?:第一|第三|一|三)季度报告", r["cleanTitle"])
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


def destination_for(row: dict[str, Any]) -> Path:
    title = row["cleanTitle"]
    kind = row["kind"]
    if kind == "年度报告":
        year = int(row["report_year"])
        suffix = "_更正或更新版" if any(x in title for x in ("更正后", "修订版", "更新后")) else ""
        return ANNUAL_DIR / f"{year}_{COMPANY}_年度报告{suffix}_巨潮资讯官方.pdf"
    if kind == "招股说明书":
        return PROSPECTUS_DIR / f"2021_{COMPANY}_首次公开发行股票招股说明书_巨潮资讯官方.pdf"
    m = re.search(r"(20\d{2})年(第一|第三|一|三)季度报告", title)
    if m:
        year, zh_q = m.groups()
        q = "Q1" if zh_q in ("第一", "一") else "Q3"
        long_q = "第一" if q == "Q1" else "第三"
        return QUARTER_DIR / f"{year}_{q}_{COMPANY}_{long_q}季度报告_巨潮资讯官方.pdf"
    return QUARTER_DIR / f"{publication_date(row)[:4]}_{COMPANY}_最新季度报告_巨潮资讯官方.pdf"


def download_document(row: dict[str, Any], destination: Path) -> str:
    adjunct = str(row.get("adjunctUrl") or "").lstrip("/")
    url = urljoin("https://static.cninfo.com.cn/", adjunct)
    response = request_with_retry(
        "GET",
        url,
        headers={"Accept": "application/pdf,application/octet-stream,*/*", "Referer": "https://www.cninfo.com.cn/"},
    )
    content = response.content
    if not content.startswith(b"%PDF"):
        raise RuntimeError(f"Not a PDF: {destination.name}; header={content[:20]!r}; url={url}")
    minimum = 500_000 if row["kind"] == "招股说明书" else 20_000
    if len(content) < minimum:
        raise RuntimeError(f"Suspiciously small PDF: {destination.name}: {len(content)} bytes")
    destination.write_bytes(content)
    return url


def validate_pdf(path: Path, kind: str) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    min_pages = 80 if kind == "招股说明书" else (30 if kind == "年度报告" else 5)
    if pages < min_pages:
        raise RuntimeError(f"Too few pages for {path.name}: {pages}")

    sample_text_parts: list[str] = []
    for idx in sorted(set([0, 1, 2, max(0, pages - 1)])):
        try:
            sample_text_parts.append(reader.pages[idx].extract_text() or "")
        except Exception:
            pass
    sample_text = "\n".join(sample_text_parts).lower()
    terms = ("杭州热电", "605011", "hangzhou cogeneration", "hangzhou thermal")
    identity_ok = any(term.lower() in sample_text for term in terms)
    if len(sample_text.strip()) > 300 and not identity_ok:
        raise RuntimeError(f"Issuer identity terms not found in extractable sample: {path.name}")

    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=120
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(
            f"qpdf failed for {path.name}: rc={qpdf.returncode}\n{qpdf.stdout}\n{qpdf.stderr}"
        )

    for label, page_num in (("first", 1), ("last", pages)):
        base = VERIFY_DIR / f"{path.stem}_{label}"
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
                str(base),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        png = Path(str(base) + ".png")
        if result.returncode != 0 or not png.exists() or png.stat().st_size < 1000:
            raise RuntimeError(f"Render failed for {path.name}, page {page_num}: {result.stderr}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "first_last_page_rendered": True,
        "identity_text_verified_when_extractable": bool(identity_ok or len(sample_text.strip()) <= 300),
    }


def main() -> None:
    rows = query_announcements()
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
            "report_year": row.get("report_year"),
            "publication_date": publication_date(row),
            "source": "巨潮资讯网（中国证监会指定上市公司信息披露平台）",
            "source_url": source_url,
            "announcement_id": str(row.get("announcementId") or ""),
            **metadata,
        }
        records.append(record)
        print("REGISTERED", json.dumps(record, ensure_ascii=False), flush=True)

    annual_years = sorted(
        int(r["report_year"])
        for r in records
        if r["document_type"] == "年度报告"
    )
    if annual_years != EXPECTED_ANNUAL_YEARS:
        raise RuntimeError(f"Unexpected annual years: {annual_years}")
    if sum(r["document_type"] == "招股说明书" for r in records) != 1:
        raise RuntimeError("Expected exactly one prospectus")
    if sum(r["document_type"] == "最新季报" for r in records) != 1:
        raise RuntimeError("Expected exactly one latest quarterly report")
    hashes = [r["sha256"] for r in records]
    if len(hashes) != len(set(hashes)):
        raise RuntimeError("Duplicate PDF hashes detected")

    readme = f"""{FULL_COMPANY}（证券简称：{COMPANY}；证券代码：{CODE}）官方披露文件包

资料截止日期：{AS_OF}

收录范围：
1. 公司上市后全部完整年度报告：2021、2022、2023、2024、2025年度。
2. 2021年首次公开发行股票并上市的正式完整招股说明书。
3. 截至资料截止日最新已披露、严格意义上的季度报告。2026年第三季度尚未完成且季度报告尚未披露，因此收录2026年第一季度报告。

排除范围：年度报告摘要、提示性公告、业绩预告、业绩快报、问询回复、单独审计附件、英文版和重复版本。

来源：巨潮资讯网公开披露的官方原始PDF。
校验：PDF文件头、实际页数、qpdf结构、首末页渲染、公司身份信息（可提取时）、重复哈希及ZIP完整性。
"""
    (ROOT / "00_文件清单与范围说明.txt").write_text(readme, encoding="utf-8")

    with (ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = [
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
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "company": FULL_COMPANY,
        "short_name": COMPANY,
        "stock_code": CODE,
        "as_of": AS_OF,
        "scope": "上市后全部年报、正式IPO招股说明书、最新严格季度报告",
        "documents": records,
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{r['sha256']}  {r['relative_path']}" for r in records) + "\n",
        encoding="utf-8",
    )

    zip_path = Path(ZIP_NAME)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=f"{ROOT.name}/{path.relative_to(ROOT).as_posix()}")

    with zipfile.ZipFile(zip_path, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")
        pdf_count = sum(n.lower().endswith(".pdf") for n in zf.namelist())
        if pdf_count != len(records):
            raise RuntimeError(f"ZIP PDF count mismatch: {pdf_count} != {len(records)}")

    print(
        "FINAL_ZIP",
        zip_path.name,
        zip_path.stat().st_size,
        sha256_file(zip_path),
        flush=True,
    )
    print("FINAL_RECORDS", json.dumps(records, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
