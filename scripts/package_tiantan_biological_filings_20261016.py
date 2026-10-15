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
from typing import Any

import pymupdf
import requests
from pypdf import PdfReader

COMPANY_SHORT = "天坛生物"
COMPANY_FULL = "北京天坛生物制品股份有限公司"
STOCK_CODE = "600161"
AS_OF = "2026-10-16"
ANNUAL_YEARS = list(range(2020, 2026))

CNINFO_QUERY = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STATIC = "https://static.cninfo.com.cn/"
CNINFO_DETAIL = "https://www.cninfo.com.cn/new/disclosure/detail"

ROOT = Path("dist_tiantan")
PACKAGE_ROOT = ROOT / f"{COMPANY_SHORT}_{STOCK_CODE}_2020-2025年报_最新季报"
ANNUAL_DIR = PACKAGE_ROOT / "01_年度报告"
QUARTER_DIR = PACKAGE_ROOT / "02_最新季报"
VERIFY_DIR = ROOT / "_verification_renders"
ZIP_PATH = ROOT / f"{COMPANY_SHORT}_{STOCK_CODE}_2020-2025年报_最新季报_20261016.zip"
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
    period: str
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
            response = session.post(CNINFO_QUERY, data=payload, timeout=90)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError(f"Unexpected CNINFO response type: {type(data)!r}")
            return data
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < 5:
                time.sleep(attempt * 1.5)
    raise RuntimeError(f"CNINFO query failed: {last_error}")


def iter_dicts(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from iter_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from iter_dicts(value)


def discover_org_id(session: requests.Session) -> str:
    urls = [
        "https://www.cninfo.com.cn/new/data/sse_stock.json",
        "https://www.cninfo.com.cn/new/data/shse_stock.json",
        "https://www.cninfo.com.cn/new/data/sh_stock.json",
        "https://www.cninfo.com.cn/new/data/szse_stock.json",
    ]
    errors: list[str] = []
    for url in urls:
        try:
            response = session.get(url, timeout=60)
            response.raise_for_status()
            data = response.json()
            for item in iter_dicts(data):
                if str(item.get("code", "")) == STOCK_CODE and item.get("orgId"):
                    org_id = str(item["orgId"])
                    print(f"Discovered orgId={org_id} from {url}")
                    return org_id
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
    raise RuntimeError("Unable to discover CNINFO orgId. " + " | ".join(errors))


def query_announcements(
    session: requests.Session,
    org_id: str,
    *,
    searchkey: str = "",
    category: str = "",
    start: str = "2019-01-01",
    end: str = AS_OF,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    stock_value = f"{STOCK_CODE},{org_id}"

    for page_num in range(1, 15):
        payload = {
            "pageNum": str(page_num),
            "pageSize": "30",
            "column": "sse",
            "tabName": "fulltext",
            "plate": "sh",
            "stock": stock_value,
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
            if str(record.get("secCode", "")) != STOCK_CODE:
                continue
            announcement_id = str(record.get("announcementId") or "")
            adjunct_url = str(record.get("adjunctUrl") or "")
            unique_id = announcement_id or adjunct_url
            if not unique_id or unique_id in seen:
                continue
            seen.add(unique_id)
            results.append(record)
            added += 1

        if added == 0 or len(announcements) < 30 or not data.get("hasMore"):
            break
        time.sleep(0.25)

    return results


def annual_candidate_score(title: str, date: str, year: int) -> tuple[int, str]:
    exact = f"{year}年年度报告"
    score = 0
    if title == exact:
        score += 100
    if title.startswith(exact):
        score += 60
    if any(word in title for word in ("修订版", "修订后", "更新后", "更正后")):
        score += 30
    if any(word in title for word in ("摘要", "英文", "取消", "提示性公告", "关于", "审计报告")):
        score -= 200
    return score, date


def choose_annual_reports(session: requests.Session, org_id: str) -> list[Filing]:
    chosen: list[Filing] = []
    for year in ANNUAL_YEARS:
        records = query_announcements(
            session,
            org_id,
            searchkey=f"{year}年年度报告",
            category="",
            start=f"{year}-01-01",
            end=f"{year + 2}-12-31" if year < 2025 else AS_OF,
        )
        candidates: list[tuple[tuple[int, str], dict[str, Any], str]] = []
        pattern = re.compile(rf"^(?:公司)?{year}年年度报告")
        for record in records:
            title = clean_title(str(record.get("announcementTitle") or ""))
            if not pattern.search(title):
                continue
            if any(word in title for word in ("摘要", "英文", "取消", "提示性公告")):
                continue
            date = publication_date(record)
            candidates.append((annual_candidate_score(title, date, year), record, title))

        if not candidates:
            # Category fallback, useful if the exact search endpoint is inconsistent.
            records = query_announcements(
                session,
                org_id,
                category="category_ndbg_szsh",
                start=f"{year}-01-01",
                end=f"{year + 2}-12-31" if year < 2025 else AS_OF,
            )
            for record in records:
                title = clean_title(str(record.get("announcementTitle") or ""))
                if pattern.search(title) and "摘要" not in title:
                    date = publication_date(record)
                    candidates.append((annual_candidate_score(title, date, year), record, title))

        if not candidates:
            raise RuntimeError(f"No complete annual report found for {year}")

        candidates.sort(key=lambda item: item[0], reverse=True)
        _, record, title = candidates[0]
        adjunct_url = str(record.get("adjunctUrl") or "")
        announcement_id = str(record.get("announcementId") or "")
        local_filename = f"{year}_{COMPANY_SHORT}_年度报告_巨潮资讯官方.pdf"
        chosen.append(
            Filing(
                document_type="年度报告",
                period=str(year),
                title=title,
                publication_date=publication_date(record),
                announcement_id=announcement_id,
                adjunct_url=adjunct_url,
                pdf_url=CNINFO_STATIC + adjunct_url.lstrip("/"),
                detail_url=(
                    f"{CNINFO_DETAIL}?stockCode={STOCK_CODE}&announcementId={announcement_id}"
                ),
                local_filename=local_filename,
                relative_path=f"01_年度报告/{local_filename}",
            )
        )
    return chosen


def parse_quarter(title: str) -> tuple[int, int] | None:
    match = re.match(r"^(20\d{2})年(第一季度|一季度|第三季度|三季度)报告", title)
    if not match:
        return None
    year = int(match.group(1))
    quarter = 1 if match.group(2) in ("第一季度", "一季度") else 3
    return year, quarter


def choose_latest_quarter(session: requests.Session, org_id: str) -> Filing:
    records = query_announcements(
        session,
        org_id,
        searchkey="季度报告",
        start="2024-01-01",
        end=AS_OF,
    )
    candidates: list[tuple[tuple[int, int, str], dict[str, Any], str]] = []
    for record in records:
        title = clean_title(str(record.get("announcementTitle") or ""))
        if any(word in title for word in ("摘要", "英文", "取消", "提示性公告", "关于")):
            continue
        parsed = parse_quarter(title)
        if parsed is None:
            continue
        year, quarter = parsed
        candidates.append(((year, quarter, publication_date(record)), record, title))

    if not candidates:
        # Fallback to individual likely search keys.
        for key in ("第一季度报告", "一季度报告", "第三季度报告", "三季度报告"):
            for record in query_announcements(
                session,
                org_id,
                searchkey=key,
                start="2024-01-01",
                end=AS_OF,
            ):
                title = clean_title(str(record.get("announcementTitle") or ""))
                parsed = parse_quarter(title)
                if parsed and "摘要" not in title:
                    year, quarter = parsed
                    candidates.append(((year, quarter, publication_date(record)), record, title))

    if not candidates:
        raise RuntimeError("No strict quarterly report found")

    candidates.sort(key=lambda item: item[0], reverse=True)
    (_, quarter, _), record, title = candidates[0]
    year = parse_quarter(title)[0]  # type: ignore[index]
    period = f"{year}_Q{quarter}"
    announcement_id = str(record.get("announcementId") or "")
    adjunct_url = str(record.get("adjunctUrl") or "")
    local_filename = f"{period}_{COMPANY_SHORT}_季度报告_巨潮资讯官方.pdf"
    return Filing(
        document_type="季度报告",
        period=period,
        title=title,
        publication_date=publication_date(record),
        announcement_id=announcement_id,
        adjunct_url=adjunct_url,
        pdf_url=CNINFO_STATIC + adjunct_url.lstrip("/"),
        detail_url=f"{CNINFO_DETAIL}?stockCode={STOCK_CODE}&announcementId={announcement_id}",
        local_filename=local_filename,
        relative_path=f"02_最新季报/{local_filename}",
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download_pdf(session: requests.Session, filing: Filing, target: Path) -> None:
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            headers = {
                "User-Agent": HEADERS["User-Agent"],
                "Accept": "application/pdf,*/*;q=0.8",
                "Referer": filing.detail_url,
            }
            response = session.get(filing.pdf_url, headers=headers, timeout=180)
            response.raise_for_status()
            payload = response.content
            if not payload.startswith(b"%PDF"):
                raise RuntimeError(
                    f"Non-PDF response: {response.status_code}, "
                    f"{response.headers.get('content-type')}, {len(payload)} bytes"
                )
            if len(payload) < 30_000:
                raise RuntimeError(f"Suspiciously small PDF: {len(payload)} bytes")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            filing.pdf_url = response.url
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < 5:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to download {filing.title}: {last_error}")


def collect_text(reader: PdfReader, limit: int = 12) -> str:
    chunks: list[str] = []
    for page in reader.pages[: min(limit, len(reader.pages))]:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            pass
    return "\n".join(chunks)


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
    minimum = 50 if filing.document_type == "年度报告" else 5
    if page_count < minimum:
        raise RuntimeError(f"Unexpected page count for {filing.title}: {page_count}")

    text = collect_text(reader)
    normalized = "".join(text.split())
    company_ok = COMPANY_SHORT in normalized or COMPANY_FULL in normalized
    code_ok = STOCK_CODE in normalized
    if not company_ok and not code_ok:
        raise RuntimeError(f"Company identity not found in {filing.local_filename}")

    render_page(pdf_path, 0, VERIFY_DIR / f"{sequence:02d}_first.png")
    render_page(pdf_path, page_count - 1, VERIFY_DIR / f"{sequence:02d}_last.png")

    payload = pdf_path.read_bytes()
    filing.pages = page_count
    filing.bytes = len(payload)
    filing.sha256 = sha256_bytes(payload)
    filing.company_identity_verified = True
    filing.first_last_page_rendered = True


def write_metadata(filings: list[Filing]) -> None:
    PACKAGE_ROOT.mkdir(parents=True, exist_ok=True)
    latest = next(item for item in filings if item.document_type == "季度报告")

    note_lines = [
        f"{COMPANY_SHORT}（{STOCK_CODE}）2020—2025年年度报告及最新季度报告",
        f"整理日期：{AS_OF}",
        "",
        "收录范围",
        "========",
        "1. 2020—2025年度报告全文，排除摘要、英文版、提示性公告和重复版本。",
        f"2. 最新严格季度报告：{latest.title}，披露日期{latest.publication_date}。",
        "3. 季报口径仅包括第一季度报告和第三季度报告；半年报不替代季报。",
        "",
        "文件清单",
        "========",
    ]
    for index, filing in enumerate(filings, 1):
        note_lines.append(
            f"{index}. {filing.title}｜{filing.publication_date}｜{filing.pages}页｜{filing.relative_path}"
        )
    note_lines.extend([
        "",
        "校验范围",
        "========",
        "PDF文件头、实际页数、公司或证券代码身份、首页与末页渲染、单文件SHA-256、ZIP CRC。",
        "",
        "资料来源：巨潮资讯网公开法定披露文件。资料仅供个人研究参考。",
    ])
    (PACKAGE_ROOT / "00_文件清单与范围说明.txt").write_text(
        "\n".join(note_lines) + "\n", encoding="utf-8"
    )

    with (PACKAGE_ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "序号", "类型", "期间", "标题", "披露日期", "页数", "字节数", "SHA256",
                "公告编号", "来源详情页", "PDF地址", "包内路径",
            ],
        )
        writer.writeheader()
        for index, filing in enumerate(filings, 1):
            writer.writerow({
                "序号": index,
                "类型": filing.document_type,
                "期间": filing.period,
                "标题": filing.title,
                "披露日期": filing.publication_date,
                "页数": filing.pages,
                "字节数": filing.bytes,
                "SHA256": filing.sha256,
                "公告编号": filing.announcement_id,
                "来源详情页": filing.detail_url,
                "PDF地址": filing.pdf_url,
                "包内路径": filing.relative_path,
            })

    manifest = {
        "company": COMPANY_SHORT,
        "company_full_name": COMPANY_FULL,
        "stock_code": STOCK_CODE,
        "as_of": AS_OF,
        "scope": "2020-2025年度报告全文 + 截至整理日的最新严格季度报告",
        "strict_quarter_rule": "仅第一季度报告和第三季度报告参与最新季报判断；半年报不替代季报",
        "documents": [asdict(filing) for filing in filings],
    }
    (PACKAGE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (PACKAGE_ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{filing.sha256}  {filing.relative_path}" for filing in filings) + "\n",
        encoding="utf-8",
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
        pdf_count = sum(name.lower().endswith(".pdf") for name in archive.namelist())
        if pdf_count != 7:
            raise RuntimeError(f"Expected 7 PDFs in ZIP, found {pdf_count}")


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    ANNUAL_DIR.mkdir(parents=True, exist_ok=True)
    QUARTER_DIR.mkdir(parents=True, exist_ok=True)
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(HEADERS)
    org_id = discover_org_id(session)

    filings = choose_annual_reports(session, org_id)
    filings.append(choose_latest_quarter(session, org_id))

    for index, filing in enumerate(filings, 1):
        target = PACKAGE_ROOT / filing.relative_path
        print(f"Downloading {index}/{len(filings)}: {filing.title}")
        download_pdf(session, filing, target)
        print(f"Validating {target}")
        validate_pdf(filing, target, index)

    write_metadata(filings)
    build_zip()

    summary = {
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest(),
        "pdf_count": len(filings),
        "documents": [
            {
                "type": filing.document_type,
                "period": filing.period,
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
