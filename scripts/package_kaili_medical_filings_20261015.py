#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import shutil
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable

import pymupdf
import requests
from pypdf import PdfReader

COMPANY_SHORT = "开立医疗"
COMPANY_FULL = "深圳开立生物医疗科技股份有限公司"
STOCK_CODE = "300633"
AS_OF = "2026-10-15"
EXPECTED_ANNUAL_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]

CNINFO_QUERY = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STATIC = "https://static.cninfo.com.cn/"
CNINFO_STOCK_LIST = "https://www.cninfo.com.cn/new/data/szse_stock.json"

ROOT = Path("dist_kaili_medical_filings")
PACKAGE_ROOT = ROOT / f"{COMPANY_SHORT}_{STOCK_CODE}_2020-2025年报_最新季报"
ANNUAL_DIR = PACKAGE_ROOT / "01_年度报告"
QUARTER_DIR = PACKAGE_ROOT / "02_最新季报"
VERIFY_DIR = ROOT / "_verification_renders"
ZIP_PATH = ROOT / f"{COMPANY_SHORT}_{STOCK_CODE}_2020-2025年报_最新季报_20261015.zip"
SUMMARY_PATH = ROOT / "package_summary.json"

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
    report_period: str
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
    for key in ("announcementDate", "publishDate"):
        value = record.get(key)
        if value:
            return str(value)[:10]
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
            if attempt < 5:
                time.sleep(attempt * 1.5)
    raise RuntimeError(f"CNINFO query failed after retries: {last_error}")


def resolve_org_id(session: requests.Session) -> str:
    response = session.get(CNINFO_STOCK_LIST, timeout=60)
    response.raise_for_status()
    data = response.json()
    for record in data.get("stockList", []):
        if str(record.get("code")) == STOCK_CODE:
            org_id = str(record.get("orgId") or "")
            short_name = str(record.get("zwjc") or "")
            if not org_id:
                raise RuntimeError(f"Missing orgId for {STOCK_CODE}")
            if COMPANY_SHORT not in short_name and short_name not in COMPANY_SHORT:
                raise RuntimeError(
                    f"Stock identity mismatch for {STOCK_CODE}: {short_name!r}, orgId={org_id!r}"
                )
            return org_id
    raise RuntimeError(f"Unable to resolve CNINFO orgId for {STOCK_CODE}")


def query_announcements(
    session: requests.Session,
    org_id: str,
    *,
    category: str = "",
    searchkey: str = "",
    start: str = "2020-01-01",
    end: str = AS_OF,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    page = 1

    while page <= 20:
        payload = {
            "pageNum": str(page),
            "pageSize": "100",
            "column": "szse",
            "tabName": "fulltext",
            "plate": "sz",
            "stock": f"{STOCK_CODE},{org_id}",
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
        announcements = data.get("announcements") or []
        if not announcements:
            break

        added = 0
        for record in announcements:
            announcement_id = str(record.get("announcementId") or "")
            if not announcement_id or announcement_id in seen:
                continue
            seen.add(announcement_id)
            records.append(record)
            added += 1

        total_pages_raw = data.get("totalpages")
        try:
            total_pages = int(total_pages_raw or 0)
        except (TypeError, ValueError):
            total_pages = 0

        if added == 0 or page >= max(1, total_pages) or not data.get("hasMore"):
            break
        page += 1

    return records


def merge_records(*groups: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for record in group:
            announcement_id = str(record.get("announcementId") or "")
            if announcement_id:
                merged[announcement_id] = record
    return list(merged.values())


def make_filing(
    record: dict[str, Any],
    *,
    document_type: str,
    fiscal_year: int | None,
    report_period: str,
    directory_name: str,
    filename_prefix: str,
) -> Filing:
    title = clean_title(str(record.get("announcementTitle") or ""))
    announcement_id = str(record.get("announcementId") or "")
    adjunct_url = str(record.get("adjunctUrl") or "").lstrip("/")
    if not adjunct_url.lower().endswith(".pdf"):
        raise RuntimeError(f"Invalid PDF adjunct URL for {title}: {adjunct_url}")
    pdf_url = CNINFO_STATIC + adjunct_url
    detail_url = (
        "https://www.cninfo.com.cn/new/disclosure/detail?"
        f"stockCode={STOCK_CODE}&announcementId={announcement_id}"
    )
    local_filename = f"{filename_prefix}_{COMPANY_SHORT}_{document_type}_巨潮资讯官方.pdf"
    relative_path = f"{directory_name}/{local_filename}"
    return Filing(
        document_type=document_type,
        fiscal_year=fiscal_year,
        report_period=report_period,
        title=title,
        publication_date=publication_date(record),
        announcement_id=announcement_id,
        adjunct_url=adjunct_url,
        pdf_url=pdf_url,
        detail_url=detail_url,
        local_filename=local_filename,
        relative_path=relative_path,
    )


def choose_annual_reports(records: list[dict[str, Any]]) -> list[Filing]:
    selected: list[Filing] = []
    exclusion_terms = (
        "摘要",
        "英文",
        "取消",
        "提示性公告",
        "审计报告",
        "内部控制",
        "社会责任",
        "问询",
        "回复",
    )

    for year in EXPECTED_ANNUAL_YEARS:
        candidates: list[dict[str, Any]] = []
        target = f"{year}年年度报告"
        for record in records:
            title = clean_title(str(record.get("announcementTitle") or ""))
            if target not in title:
                continue
            if any(term in title for term in exclusion_terms):
                continue
            candidates.append(record)

        if not candidates:
            available = sorted(
                {
                    clean_title(str(record.get("announcementTitle") or ""))
                    for record in records
                    if str(year) in clean_title(str(record.get("announcementTitle") or ""))
                }
            )
            raise RuntimeError(
                f"No complete annual report found for {year}. Candidate titles: {available}"
            )

        candidates.sort(
            key=lambda record: (
                publication_date(record),
                "更新" in clean_title(str(record.get("announcementTitle") or "")),
                "修订" in clean_title(str(record.get("announcementTitle") or "")),
                str(record.get("announcementId") or ""),
            ),
            reverse=True,
        )
        selected.append(
            make_filing(
                candidates[0],
                document_type="年度报告",
                fiscal_year=year,
                report_period=str(year),
                directory_name="01_年度报告",
                filename_prefix=str(year),
            )
        )

    return selected


def strict_quarter_key(record: dict[str, Any]) -> tuple[int, int, str] | None:
    title = clean_title(str(record.get("announcementTitle") or ""))
    if any(term in title for term in ("财务报表", "审阅报告", "摘要", "业绩预告")):
        return None
    match = re.search(r"(20\d{2})年(第一季度|一季度|第三季度|三季度)报告", title)
    if not match:
        return None
    year = int(match.group(1))
    quarter = 1 if match.group(2) in ("第一季度", "一季度") else 3
    return year, quarter, publication_date(record)


def choose_latest_quarter(records: list[dict[str, Any]]) -> Filing:
    candidates: list[tuple[tuple[int, int, str], dict[str, Any]]] = []
    for record in records:
        key = strict_quarter_key(record)
        if key is not None:
            candidates.append((key, record))
    if not candidates:
        raise RuntimeError("No strict first- or third-quarter report found")

    candidates.sort(key=lambda item: (item[0], str(item[1].get("announcementId") or "")), reverse=True)
    key, record = candidates[0]
    year, quarter, _ = key
    period = f"{year}_Q{quarter}"
    return make_filing(
        record,
        document_type="季度报告",
        fiscal_year=year,
        report_period=period,
        directory_name="02_最新季报",
        filename_prefix=period,
    )


def download_pdf(session: requests.Session, filing: Filing, target: Path) -> None:
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = session.get(
                filing.pdf_url,
                headers={
                    "User-Agent": HEADERS["User-Agent"],
                    "Accept": "application/pdf,*/*;q=0.8",
                    "Referer": filing.detail_url,
                },
                timeout=120,
                allow_redirects=True,
            )
            response.raise_for_status()
            payload = response.content
            if not payload.startswith(b"%PDF"):
                raise RuntimeError(
                    f"Non-PDF response: {response.status_code}, "
                    f"{response.headers.get('content-type')}, {len(payload)} bytes"
                )
            if len(payload) < 50_000:
                raise RuntimeError(f"Suspiciously small PDF: {len(payload)} bytes")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            filing.pdf_url = response.url
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < 5:
                time.sleep(attempt * 1.5)
    raise RuntimeError(f"Unable to download {filing.title}: {last_error}")


def extract_identity_text(reader: PdfReader) -> str:
    indexes = list(range(min(18, len(reader.pages))))
    if len(reader.pages) > 18:
        indexes.append(len(reader.pages) - 1)
    chunks: list[str] = []
    for index in indexes:
        try:
            chunks.append(reader.pages[index].extract_text() or "")
        except Exception:  # noqa: BLE001
            pass
    return "".join("\n".join(chunks).split())


def render_page(pdf_path: Path, page_index: int, output_path: Path) -> None:
    with pymupdf.open(pdf_path) as document:
        page = document[page_index]
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pixmap.save(output_path)
        if output_path.stat().st_size < 5_000:
            raise RuntimeError(f"Rendered image is unexpectedly small: {output_path}")


def validate_pdf(filing: Filing, pdf_path: Path, sequence: int) -> None:
    reader = PdfReader(str(pdf_path), strict=False)
    page_count = len(reader.pages)
    if page_count < 8:
        raise RuntimeError(f"Unexpectedly short filing {filing.title}: {page_count} pages")

    identity_text = extract_identity_text(reader)
    company_ok = (
        COMPANY_SHORT in identity_text
        or COMPANY_FULL in identity_text
        or STOCK_CODE in identity_text
    )
    if not company_ok:
        raise RuntimeError(f"Company identity not found in {filing.local_filename}")

    render_page(pdf_path, 0, VERIFY_DIR / f"{sequence:02d}_first.png")
    render_page(pdf_path, page_count - 1, VERIFY_DIR / f"{sequence:02d}_last.png")

    payload = pdf_path.read_bytes()
    filing.pages = page_count
    filing.bytes = len(payload)
    filing.sha256 = hashlib.sha256(payload).hexdigest()
    filing.company_identity_verified = True
    filing.first_last_page_rendered = True


def write_metadata(filings: list[Filing]) -> None:
    PACKAGE_ROOT.mkdir(parents=True, exist_ok=True)
    latest_quarter = filings[-1]

    lines = [
        f"{COMPANY_SHORT}（{STOCK_CODE}）2020—2025年报及最新季报",
        f"整理日期：{AS_OF}",
        "",
        "范围说明",
        "========",
        "1. 收录2020—2025年完整年度报告全文。",
        "2. 排除年度报告摘要、英文版、提示性公告、单独审计附件及重复旧版本。",
        "3. 最新季报按严格法定季度报告口径，仅比较一季度报告和三季度报告；半年报不用于替代季报。",
        f"4. 本包最新季度报告为：{latest_quarter.title}（披露日期：{latest_quarter.publication_date}）。",
        "5. PDF均来自巨潮资讯公开披露端点。",
        "",
        "文件清单",
        "========",
    ]
    for index, filing in enumerate(filings, 1):
        lines.extend(
            [
                f"{index}. {filing.title}",
                f"   - 类型：{filing.document_type}",
                f"   - 报告期：{filing.report_period}",
                f"   - 披露日期：{filing.publication_date}",
                f"   - 实际页数：{filing.pages}",
                f"   - 包内路径：{filing.relative_path}",
                f"   - 来源页面：{filing.detail_url}",
                "",
            ]
        )
    lines.extend(
        [
            "校验范围",
            "========",
            "- PDF文件头和结构解析",
            "- 实际页数",
            "- 公司名称或证券代码身份",
            "- 首页与末页渲染",
            "- 单文件SHA-256",
            "- ZIP CRC完整性",
            "",
            "资料仅供个人研究参考，文件版权归上市公司及相关权利人所有。",
        ]
    )
    (PACKAGE_ROOT / "00_文件清单与范围说明.txt").write_text("\n".join(lines), encoding="utf-8")

    with (PACKAGE_ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "序号",
                "文件类型",
                "报告期",
                "标题",
                "披露日期",
                "实际页数",
                "字节数",
                "SHA256",
                "来源页面",
                "PDF地址",
                "包内路径",
            ],
        )
        writer.writeheader()
        for index, filing in enumerate(filings, 1):
            writer.writerow(
                {
                    "序号": index,
                    "文件类型": filing.document_type,
                    "报告期": filing.report_period,
                    "标题": filing.title,
                    "披露日期": filing.publication_date,
                    "实际页数": filing.pages,
                    "字节数": filing.bytes,
                    "SHA256": filing.sha256,
                    "来源页面": filing.detail_url,
                    "PDF地址": filing.pdf_url,
                    "包内路径": filing.relative_path,
                }
            )

    manifest = {
        "company": COMPANY_SHORT,
        "company_full_name": COMPANY_FULL,
        "stock_code": STOCK_CODE,
        "as_of": AS_OF,
        "scope": "2020-2025年度报告全文 + 截至整理日的最新严格季度报告",
        "strict_quarter_rule": "仅一季度报告和三季度报告参与最新季报判断；半年报不替代季报",
        "documents": [asdict(filing) for filing in filings],
    }
    (PACKAGE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    checksum_lines = [f"{filing.sha256}  {filing.relative_path}" for filing in filings]
    (PACKAGE_ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8"
    )


def build_zip() -> None:
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
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
    ANNUAL_DIR.mkdir(parents=True, exist_ok=True)
    QUARTER_DIR.mkdir(parents=True, exist_ok=True)
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(HEADERS)
    org_id = resolve_org_id(session)
    print(f"Resolved {STOCK_CODE} orgId={org_id}")

    annual_records = merge_records(
        query_announcements(session, org_id, category="category_ndbg_szsh"),
        query_announcements(session, org_id, searchkey="年度报告"),
    )
    annual_filings = choose_annual_reports(annual_records)

    quarter_records = merge_records(
        query_announcements(session, org_id, category="category_yjdbg_szsh"),
        query_announcements(session, org_id, searchkey="季度报告"),
    )
    latest_quarter = choose_latest_quarter(quarter_records)
    filings = annual_filings + [latest_quarter]

    for sequence, filing in enumerate(filings, 1):
        target = ROOT / filing.relative_path
        print(f"Downloading {sequence}/{len(filings)}: {filing.title}")
        download_pdf(session, filing, target)
        print(f"Validating {target}")
        validate_pdf(filing, target, sequence)

    write_metadata(filings)
    build_zip()

    zip_bytes = ZIP_PATH.stat().st_size
    zip_sha256 = hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest()
    summary = {
        "zip": str(ZIP_PATH),
        "zip_bytes": zip_bytes,
        "zip_sha256": zip_sha256,
        "pdf_count": len(filings),
        "documents": [
            {
                "type": filing.document_type,
                "period": filing.report_period,
                "title": filing.title,
                "publication_date": filing.publication_date,
                "pages": filing.pages,
                "bytes": filing.bytes,
            }
            for filing in filings
        ],
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
