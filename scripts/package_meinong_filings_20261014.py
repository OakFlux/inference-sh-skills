#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import shutil
import sys
import time
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable

import fitz  # PyMuPDF
import requests
from pypdf import PdfReader

COMPANY_SHORT = "美农生物"
COMPANY_FULL = "上海美农生物科技股份有限公司"
STOCK_CODE = "301156"
AS_OF = "2026-10-14"
EXPECTED_ANNUAL_YEARS = [2022, 2023, 2024, 2025]

CNINFO_QUERY = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STATIC = "https://static.cninfo.com.cn/"
CNINFO_DETAIL = "https://www.cninfo.com.cn/new/disclosure/detail"

ROOT = Path("dist")
PACKAGE_ROOT = ROOT / f"{COMPANY_SHORT}_{STOCK_CODE}_全部年报_招股说明书_最新季报"
ANNUAL_DIR = PACKAGE_ROOT / "01_年度报告"
PROSPECTUS_DIR = PACKAGE_ROOT / "02_招股说明书"
QUARTER_DIR = PACKAGE_ROOT / "03_最新季报"
VERIFY_DIR = ROOT / "_verification_renders"
ZIP_PATH = ROOT / f"{COMPANY_SHORT}_{STOCK_CODE}_全部年报_招股说明书_最新季报_20261014.zip"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://www.cninfo.com.cn",
    "Referer": f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={STOCK_CODE}",
    "X-Requested-With": "XMLHttpRequest",
}

TZ_CN = timezone(timedelta(hours=8))


@dataclass
class Filing:
    document_type: str
    fiscal_year: int | None
    report_period: str | None
    title: str
    publication_date: str
    announcement_id: str
    adjunct_url: str
    pdf_url: str
    detail_url: str
    local_filename: str
    relative_path: str
    pages: int = 0
    bytes: int = 0
    sha256: str = ""
    company_identity_verified: bool = False
    first_last_page_rendered: bool = False


def clean_title(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace(" ", "").replace("　", "")
    return value.strip()


def publication_date(record: dict[str, Any]) -> str:
    raw = record.get("announcementTime")
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw / 1000, TZ_CN).strftime("%Y-%m-%d")
    if isinstance(raw, str) and raw.isdigit():
        return datetime.fromtimestamp(int(raw) / 1000, TZ_CN).strftime("%Y-%m-%d")
    # Rare fallback fields.
    for key in ("announcementDate", "publishDate"):
        val = record.get(key)
        if val:
            return str(val)[:10]
    return ""


def request_json(session: requests.Session, payload: dict[str, str]) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = session.post(CNINFO_QUERY, data=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError(f"Unexpected CNINFO payload type: {type(data)!r}")
            return data
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == 5:
                break
            time.sleep(attempt * 1.5)
    raise RuntimeError(f"CNINFO query failed after retries: {last_error}")


def query_announcements(
    session: requests.Session,
    *,
    start: str,
    end: str,
    category: str = "",
    searchkey: str = "",
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for page in range(1, 31):
        payload = {
            "pageNum": str(page),
            "pageSize": "30",
            "column": "szse",
            "tabName": "fulltext",
            "plate": "sz",
            "stock": STOCK_CODE,
            "searchkey": searchkey,
            "secid": "",
            "category": category,
            "trade": "",
            "seDate": f"{start}~{end}",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        data = request_json(session, payload)
        batch = data.get("announcements") or []
        if not batch:
            break
        for record in batch:
            rid = str(record.get("announcementId") or record.get("adjunctUrl") or "")
            if rid and rid not in seen:
                records.append(record)
                seen.add(rid)
        total_pages = data.get("totalpages") or data.get("totalPages")
        if isinstance(total_pages, int) and page >= total_pages:
            break
        if len(batch) < 30:
            break
        time.sleep(0.35)

    return records


def report_score(record: dict[str, Any], year: int) -> tuple[int, str]:
    title = clean_title(str(record.get("announcementTitle") or ""))
    score = 0
    exact = f"{year}年年度报告"
    if title == exact:
        score += 100
    if exact in title:
        score += 40
    if "更正后" in title or "修订版" in title or "更新后" in title:
        score += 20
    if any(bad in title for bad in ["摘要", "英文版", "审计报告", "取消", "提示性公告", "关于"]):
        score -= 200
    return score, publication_date(record)


def choose_annual_reports(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for year in EXPECTED_ANNUAL_YEARS:
        candidates = []
        for record in records:
            title = clean_title(str(record.get("announcementTitle") or ""))
            if f"{year}年年度报告" not in title:
                continue
            score = report_score(record, year)
            if score[0] > 0:
                candidates.append((score, record))
        if not candidates:
            raise RuntimeError(f"No complete annual report found for {year}. Candidate titles: " + ", ".join(
                clean_title(str(r.get('announcementTitle') or '')) for r in records if str(year) in clean_title(str(r.get('announcementTitle') or ''))
            ))
        candidates.sort(key=lambda item: item[0], reverse=True)
        selected.append(candidates[0][1])
    return selected


def choose_prospectus(records: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[tuple[tuple[int, str], dict[str, Any]]] = []
    for record in records:
        title = clean_title(str(record.get("announcementTitle") or ""))
        if "招股说明书" not in title:
            continue
        score = 0
        if "首次公开发行股票并在创业板上市招股说明书" in title:
            score += 100
        if title.endswith("招股说明书"):
            score += 40
        if "注册稿" in title:
            score -= 20
        if "申报稿" in title or "上会稿" in title:
            score -= 30
        if any(bad in title for bad in ["摘要", "附录", "声明", "提示性公告", "关于"]):
            score -= 200
        if score > 0:
            candidates.append(((score, publication_date(record)), record))
    if not candidates:
        raise RuntimeError("No final IPO prospectus found. Titles: " + ", ".join(
            clean_title(str(r.get('announcementTitle') or '')) for r in records
        ))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def quarter_rank(title: str) -> tuple[int, int]:
    year_match = re.search(r"(20\d{2})年", title)
    year = int(year_match.group(1)) if year_match else 0
    if "第三季度报告" in title:
        quarter = 3
    elif "第一季度报告" in title or "一季度报告" in title:
        quarter = 1
    else:
        quarter = 0
    return year, quarter


def choose_latest_quarter(records: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[tuple[tuple[int, int, str], dict[str, Any]]] = []
    for record in records:
        title = clean_title(str(record.get("announcementTitle") or ""))
        if "季度报告" not in title and "一季度报告" not in title:
            continue
        if any(bad in title for bad in ["摘要", "提示性公告", "关于", "英文版"]):
            continue
        year, q = quarter_rank(title)
        if year <= 0 or q <= 0:
            continue
        candidates.append(((year, q, publication_date(record)), record))
    if not candidates:
        raise RuntimeError("No quarterly report found. Titles: " + ", ".join(
            clean_title(str(r.get('announcementTitle') or '')) for r in records
        ))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def make_filing(record: dict[str, Any], document_type: str, fiscal_year: int | None = None) -> Filing:
    title = clean_title(str(record.get("announcementTitle") or ""))
    pub_date = publication_date(record)
    announcement_id = str(record.get("announcementId") or "")
    adjunct = str(record.get("adjunctUrl") or "").lstrip("/")
    if not adjunct:
        raise RuntimeError(f"Missing adjunctUrl for {title}")
    pdf_url = CNINFO_STATIC + adjunct
    detail_url = f"{CNINFO_DETAIL}?stockCode={STOCK_CODE}&announcementId={announcement_id}&orgId={record.get('orgId','')}"

    if document_type == "年度报告":
        assert fiscal_year is not None
        filename = f"{fiscal_year}_{COMPANY_SHORT}_年度报告_巨潮资讯官方.pdf"
        rel = f"01_年度报告/{filename}"
        report_period = str(fiscal_year)
    elif document_type == "招股说明书":
        filename = f"2022_{COMPANY_SHORT}_首次公开发行股票并在创业板上市招股说明书_巨潮资讯官方.pdf"
        rel = f"02_招股说明书/{filename}"
        report_period = "IPO"
    elif document_type == "季度报告":
        year, q = quarter_rank(title)
        label = f"{year}_Q{q}"
        filename = f"{label}_{COMPANY_SHORT}_{'第三季度报告' if q == 3 else '第一季度报告'}_巨潮资讯官方.pdf"
        rel = f"03_最新季报/{filename}"
        report_period = label
        fiscal_year = year
    else:
        raise ValueError(document_type)

    return Filing(
        document_type=document_type,
        fiscal_year=fiscal_year,
        report_period=report_period,
        title=title,
        publication_date=pub_date,
        announcement_id=announcement_id,
        adjunct_url=adjunct,
        pdf_url=pdf_url,
        detail_url=detail_url,
        local_filename=filename,
        relative_path=rel,
    )


def download_pdf(session: requests.Session, filing: Filing) -> Path:
    destination = PACKAGE_ROOT / filing.relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    headers = {
        **HEADERS,
        "Accept": "application/pdf,application/octet-stream,*/*",
        "Referer": filing.detail_url,
    }
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            with session.get(filing.pdf_url, headers=headers, timeout=120, stream=True) as response:
                response.raise_for_status()
                with destination.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            raw = destination.read_bytes()
            if not raw.startswith(b"%PDF"):
                raise RuntimeError(f"Not a PDF: {filing.pdf_url}, head={raw[:20]!r}")
            if len(raw) < 50_000:
                raise RuntimeError(f"Suspiciously small PDF ({len(raw)} bytes): {filing.pdf_url}")
            return destination
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            destination.unlink(missing_ok=True)
            if attempt == 5:
                break
            time.sleep(attempt * 2)
    raise RuntimeError(f"Download failed for {filing.title}: {last_error}")


def validate_pdf(path: Path, filing: Filing) -> None:
    raw = path.read_bytes()
    filing.bytes = len(raw)
    filing.sha256 = hashlib.sha256(raw).hexdigest()

    reader = PdfReader(str(path), strict=False)
    filing.pages = len(reader.pages)
    if filing.pages < 8:
        raise RuntimeError(f"Unexpectedly short PDF ({filing.pages} pages): {path.name}")

    doc = fitz.open(path)
    sample_indices = sorted(set([0, min(1, filing.pages - 1), min(2, filing.pages - 1), filing.pages - 1]))
    sample_text = "\n".join(doc.load_page(i).get_text("text") for i in sample_indices)
    identity_tokens = [COMPANY_SHORT, COMPANY_FULL, STOCK_CODE]
    filing.company_identity_verified = any(token in sample_text.replace(" ", "") for token in identity_tokens)
    if not filing.company_identity_verified:
        # Some cover pages use spaced characters or scanned seals. Search up to first 10 pages.
        extended = "\n".join(doc.load_page(i).get_text("text") for i in range(min(10, filing.pages)))
        filing.company_identity_verified = any(token in extended.replace(" ", "") for token in identity_tokens)
    if not filing.company_identity_verified:
        raise RuntimeError(f"Company identity could not be verified in {path.name}")

    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    for label, index in (("first", 0), ("last", filing.pages - 1)):
        page = doc.load_page(index)
        pix = page.get_pixmap(matrix=fitz.Matrix(0.75, 0.75), alpha=False)
        render_path = VERIFY_DIR / f"{Path(filing.local_filename).stem}_{label}.png"
        pix.save(render_path)
        if render_path.stat().st_size < 5_000:
            raise RuntimeError(f"Rendered page is suspiciously small: {render_path}")
    filing.first_last_page_rendered = True
    doc.close()


def write_support_files(filings: list[Filing], annual_records: list[dict[str, Any]], quarter: Filing) -> None:
    report_years = ", ".join(str(year) for year in EXPECTED_ANNUAL_YEARS)
    quarterly_note = (
        f"截至{AS_OF}，在巨潮资讯法定披露记录中检索到的最新严格季度报告为"
        f"《{quarter.title}》（披露日期：{quarter.publication_date}）。"
        "半年度报告不属于季度报告，因此未用于替代季报。"
    )
    scope_text = f"""{COMPANY_SHORT}（证券代码：{STOCK_CODE}）官方披露文件包

范围口径：
1. 年度报告：收录公司上市后的全部完整年度报告，报告年度为{report_years}；排除年度报告摘要、英文版、审计附件、提示性公告及重复版本。
2. 招股说明书：收录首次公开发行股票并在创业板上市的最终版招股说明书；不以注册稿、申报稿或网页摘要替代。
3. 最新季报：{quarterly_note}
4. 来源：巨潮资讯网公开披露PDF端点。
5. 校验：所有PDF均完成文件头、实际页数、公司身份、首末页渲染及SHA-256校验；ZIP完成CRC测试。

文件数量：{len(filings)}份PDF。
生成日期：{AS_OF}
"""
    (PACKAGE_ROOT / "00_文件清单与范围说明.txt").write_text(scope_text, encoding="utf-8")

    csv_path = PACKAGE_ROOT / "文件清单.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "类别", "报告期", "报告标题", "披露日期", "页数", "文件大小（字节）",
            "SHA-256", "本地文件", "官方PDF地址", "公告详情地址",
        ])
        for f in filings:
            writer.writerow([
                f.document_type, f.report_period or "", f.title, f.publication_date,
                f.pages, f.bytes, f.sha256, f.relative_path, f.pdf_url, f.detail_url,
            ])

    manifest = {
        "company": COMPANY_SHORT,
        "company_full_name": COMPANY_FULL,
        "stock_code": STOCK_CODE,
        "as_of": AS_OF,
        "source": "巨潮资讯网（CNINFO）官方公开披露",
        "scope": {
            "annual_report_years": EXPECTED_ANNUAL_YEARS,
            "prospectus": "首次公开发行股票并在创业板上市最终版招股说明书",
            "latest_quarterly_report": quarter.title,
            "latest_quarterly_report_date": quarter.publication_date,
        },
        "documents": [asdict(f) for f in filings],
    }
    (PACKAGE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    sums = [f"{f.sha256}  {f.relative_path}" for f in filings]
    (PACKAGE_ROOT / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")


def create_zip() -> None:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(PACKAGE_ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(ROOT))
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    for directory in (ANNUAL_DIR, PROSPECTUS_DIR, QUARTER_DIR, VERIFY_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(HEADERS)

    annual_pool = query_announcements(
        session,
        start="2021-01-01",
        end=AS_OF,
        category="category_ndbg_szsh",
    )
    if not annual_pool:
        annual_pool = query_announcements(session, start="2021-01-01", end=AS_OF, searchkey="年度报告")
    annual_records = choose_annual_reports(annual_pool)

    prospectus_pool = query_announcements(
        session,
        start="2021-01-01",
        end="2022-12-31",
        searchkey="招股说明书",
    )
    prospectus_record = choose_prospectus(prospectus_pool)

    quarter_pool = query_announcements(
        session,
        start="2026-01-01",
        end=AS_OF,
        searchkey="季度报告",
    )
    if not quarter_pool:
        quarter_pool = query_announcements(session, start="2026-01-01", end=AS_OF)
    quarter_record = choose_latest_quarter(quarter_pool)

    selected: list[Filing] = []
    for year, record in zip(EXPECTED_ANNUAL_YEARS, annual_records, strict=True):
        selected.append(make_filing(record, "年度报告", fiscal_year=year))
    selected.append(make_filing(prospectus_record, "招股说明书", fiscal_year=2022))
    selected.append(make_filing(quarter_record, "季度报告"))

    print("SELECTED DOCUMENTS")
    for f in selected:
        print(json.dumps({
            "type": f.document_type,
            "period": f.report_period,
            "title": f.title,
            "date": f.publication_date,
            "pdf": f.pdf_url,
        }, ensure_ascii=False))

    for filing in selected:
        path = download_pdf(session, filing)
        validate_pdf(path, filing)
        print(f"VALIDATED {filing.local_filename}: {filing.pages} pages, {filing.bytes} bytes")

    quarter_filing = next(f for f in selected if f.document_type == "季度报告")
    write_support_files(selected, annual_pool, quarter_filing)
    create_zip()

    digest = hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest()
    summary = {
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": digest,
        "pdf_count": len(selected),
        "documents": [
            {
                "type": f.document_type,
                "period": f.report_period,
                "title": f.title,
                "publication_date": f.publication_date,
                "pages": f.pages,
                "bytes": f.bytes,
            }
            for f in selected
        ],
    }
    (ROOT / "package_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("PACKAGE_SUMMARY=" + json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
