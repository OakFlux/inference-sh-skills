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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pymupdf
import requests
from pypdf import PdfReader

COMPANY_SHORT = "双象股份"
COMPANY_FULL = "无锡双象超纤材料股份有限公司"
STOCK_CODE = "002395"
AS_OF = "2026-10-14"
ANNUAL_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]

CNINFO_QUERY = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STOCKS = "https://www.cninfo.com.cn/new/data/szse_stock.json"
CNINFO_STATIC = "https://static.cninfo.com.cn/"

ROOT = Path("dist_shuangxiang")
PACKAGE_ROOT = ROOT / f"{COMPANY_SHORT}_{STOCK_CODE}_2020-2025年报_最新季报"
ANNUAL_DIR = PACKAGE_ROOT / "01_年度报告"
QUARTER_DIR = PACKAGE_ROOT / "02_最新季报"
VERIFY_DIR = ROOT / "_verification_renders"
ZIP_PATH = ROOT / f"{COMPANY_SHORT}_{STOCK_CODE}_2020-2025年报_最新季报_20261014.zip"

TZ_CN = timezone(timedelta(hours=8))
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
    identity_verified: bool = False
    first_last_page_rendered: bool = False


def clean_title(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", "", value)
    return value.replace(" ", "").replace("　", "").strip()


def pub_date(record: dict[str, Any]) -> str:
    raw = record.get("announcementTime")
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw / 1000, TZ_CN).strftime("%Y-%m-%d")
    if isinstance(raw, str) and raw.isdigit():
        return datetime.fromtimestamp(int(raw) / 1000, TZ_CN).strftime("%Y-%m-%d")
    return str(record.get("announcementDate") or record.get("publishDate") or "")[:10]


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def request_json(session: requests.Session, payload: dict[str, str]) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = session.post(CNINFO_QUERY, data=payload, timeout=75)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError(f"Unexpected CNINFO response type: {type(data)!r}")
            return data
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < 5:
                time.sleep(attempt * 1.5)
    raise RuntimeError(f"CNINFO query failed after retries: {last_error}")


def find_org_id(session: requests.Session) -> str:
    response = session.get(CNINFO_STOCKS, timeout=75)
    response.raise_for_status()
    data = response.json()
    for item in data.get("stockList", []):
        if str(item.get("code")) == STOCK_CODE:
            name = str(item.get("zwjc") or "")
            org_id = str(item.get("orgId") or "")
            if COMPANY_SHORT not in name and name not in {"双象股份", "双象"}:
                raise RuntimeError(f"Stock identity mismatch: {item}")
            if not org_id:
                raise RuntimeError(f"Missing orgId: {item}")
            return org_id
    raise RuntimeError(f"Unable to locate {STOCK_CODE} in CNINFO stock list")


def query_announcements(
    session: requests.Session,
    stock_token: str,
    *,
    category: str = "",
    searchkey: str = "",
) -> list[dict[str, Any]]:
    payload = {
        "pageNum": "1",
        "pageSize": "100",
        "column": "szse",
        "tabName": "fulltext",
        "plate": "sz",
        "stock": stock_token,
        "searchkey": searchkey,
        "secid": "",
        "category": category,
        "trade": "",
        "seDate": f"2020-01-01~{AS_OF}",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    data = request_json(session, payload)
    rows = data.get("announcements") or []
    if not isinstance(rows, list):
        raise RuntimeError("CNINFO announcements field is not a list")
    return rows


def annual_score(record: dict[str, Any], year: int) -> tuple[int, str]:
    title = clean_title(record.get("announcementTitle", ""))
    score = 0
    if title.startswith(f"{year}年"):
        score += 20
    if "年度报告全文" in title:
        score += 6
    elif "年度报告" in title:
        score += 4
    if any(tag in title for tag in ("更新后", "修订后", "更正后", "修订版", "更正版")):
        score += 10
    return score, pub_date(record)


def choose_annual_reports(rows: list[dict[str, Any]]) -> list[Filing]:
    selected: list[Filing] = []
    all_titles = [clean_title(row.get("announcementTitle", "")) for row in rows]
    for year in ANNUAL_YEARS:
        candidates = []
        for row in rows:
            title = clean_title(row.get("announcementTitle", ""))
            if f"{year}年年度报告" not in title:
                continue
            if any(flag in title for flag in ("摘要", "英文", "取消")):
                continue
            if title.startswith("关于"):
                continue
            if not row.get("adjunctUrl"):
                continue
            candidates.append(row)
        if not candidates:
            raise RuntimeError(
                f"No complete annual report found for {year}. Candidate titles: "
                + " | ".join(t for t in all_titles if str(year) in t)
            )
        chosen = max(candidates, key=lambda row: annual_score(row, year))
        title = clean_title(chosen.get("announcementTitle", ""))
        adjunct_url = str(chosen["adjunctUrl"])
        announcement_id = str(chosen.get("announcementId") or "")
        filename = f"{year}_{COMPANY_SHORT}_年度报告_巨潮资讯官方.pdf"
        selected.append(
            Filing(
                document_type="年度报告",
                period=str(year),
                title=title,
                publication_date=pub_date(chosen),
                announcement_id=announcement_id,
                adjunct_url=adjunct_url,
                pdf_url=CNINFO_STATIC + adjunct_url,
                detail_url=(
                    "https://www.cninfo.com.cn/new/disclosure/detail"
                    f"?stockCode={STOCK_CODE}&announcementId={announcement_id}"
                ),
                local_filename=filename,
                relative_path=f"01_年度报告/{filename}",
            )
        )
    return selected


def quarter_rank(title: str) -> int:
    if "第三季度报告" in title or "三季度报告" in title:
        return 3
    if "第一季度报告" in title or "一季度报告" in title:
        return 1
    return 0


def choose_latest_quarter(rows: list[dict[str, Any]]) -> Filing:
    candidates = []
    for row in rows:
        title = clean_title(row.get("announcementTitle", ""))
        if "季度报告" not in title:
            continue
        if any(flag in title for flag in ("摘要", "财务报表", "审阅报告")):
            continue
        if not re.match(r"^20\d{2}年", title):
            continue
        rank = quarter_rank(title)
        if rank == 0 or not row.get("adjunctUrl"):
            continue
        candidates.append((pub_date(row), rank, row))
    if not candidates:
        raise RuntimeError("No strict quarterly report found")
    _, rank, chosen = max(candidates, key=lambda item: (item[0], item[1]))
    title = clean_title(chosen.get("announcementTitle", ""))
    year_match = re.match(r"^(20\d{2})年", title)
    year = year_match.group(1) if year_match else pub_date(chosen)[:4]
    period = f"{year}_Q3" if rank == 3 else f"{year}_Q1"
    adjunct_url = str(chosen["adjunctUrl"])
    announcement_id = str(chosen.get("announcementId") or "")
    filename = f"{period}_{COMPANY_SHORT}_季度报告_巨潮资讯官方.pdf"
    return Filing(
        document_type="季度报告",
        period=period,
        title=title,
        publication_date=pub_date(chosen),
        announcement_id=announcement_id,
        adjunct_url=adjunct_url,
        pdf_url=CNINFO_STATIC + adjunct_url,
        detail_url=(
            "https://www.cninfo.com.cn/new/disclosure/detail"
            f"?stockCode={STOCK_CODE}&announcementId={announcement_id}"
        ),
        local_filename=filename,
        relative_path=f"02_最新季报/{filename}",
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
                timeout=150,
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
                time.sleep(attempt * 1.7)
    raise RuntimeError(f"Unable to download {filing.title}: {last_error}")


def collect_text(reader: PdfReader, page_limit: int = 20) -> str:
    chunks: list[str] = []
    for page in reader.pages[: min(page_limit, len(reader.pages))]:
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
            raise RuntimeError(f"Rendered page too small: {output_path}")


def validate_pdf(filing: Filing, pdf_path: Path, sequence: int) -> None:
    reader = PdfReader(str(pdf_path), strict=False)
    page_count = len(reader.pages)
    minimum = 50 if filing.document_type == "年度报告" else 5
    if page_count < minimum:
        raise RuntimeError(f"Unexpected page count for {filing.title}: {page_count}")

    normalized = "".join(collect_text(reader).split())
    identity_ok = (
        COMPANY_SHORT in normalized
        or COMPANY_FULL in normalized
        or STOCK_CODE in normalized
        or "双象超纤" in normalized
    )
    if not identity_ok:
        raise RuntimeError(f"Company identity not found in {filing.local_filename}")

    render_page(pdf_path, 0, VERIFY_DIR / f"{sequence:02d}_first.png")
    render_page(pdf_path, page_count - 1, VERIFY_DIR / f"{sequence:02d}_last.png")

    payload = pdf_path.read_bytes()
    filing.pages = page_count
    filing.bytes = len(payload)
    filing.sha256 = sha256_bytes(payload)
    filing.identity_verified = True
    filing.first_last_page_rendered = True


def write_metadata(filings: list[Filing]) -> None:
    PACKAGE_ROOT.mkdir(parents=True, exist_ok=True)
    latest = next(item for item in filings if item.document_type == "季度报告")
    note = f"""双象股份（002395）2020—2025年年度报告及最新季度报告资料包
整理日期：{AS_OF}
公司全称：{COMPANY_FULL}

收录范围
========
1. 2020—2025年度报告全文，共6份。
2. 截至{AS_OF}已公开披露的最新严格季度报告：{latest.title}，披露日期{latest.publication_date}。
3. 半年度报告不属于季度报告，因此未用于替代最新季报。
4. 已排除年度报告摘要、英文版、提示性公告及重复版本；如同一年度存在更新或修订版本，优先保留较新的完整版本。

校验范围
========
- PDF文件头与结构解析
- 实际页数
- 公司简称、全称或证券代码身份核验
- 首页和末页渲染
- 单文件SHA-256
- ZIP CRC完整性

文件均来自巨潮资讯网公开披露端点，仅供研究使用。
"""
    (PACKAGE_ROOT / "00_文件清单与范围说明.txt").write_text(note, encoding="utf-8")

    with (PACKAGE_ROOT / "文件清单.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "类别", "报告期", "标题", "披露日期", "页数", "字节数",
                "SHA256", "公告编号", "公告详情页", "PDF地址", "包内路径",
            ],
        )
        writer.writeheader()
        for filing in filings:
            writer.writerow({
                "类别": filing.document_type,
                "报告期": filing.period,
                "标题": filing.title,
                "披露日期": filing.publication_date,
                "页数": filing.pages,
                "字节数": filing.bytes,
                "SHA256": filing.sha256,
                "公告编号": filing.announcement_id,
                "公告详情页": filing.detail_url,
                "PDF地址": filing.pdf_url,
                "包内路径": filing.relative_path,
            })

    manifest = {
        "company": COMPANY_SHORT,
        "company_full_name": COMPANY_FULL,
        "stock_code": STOCK_CODE,
        "as_of": AS_OF,
        "scope": "2020-2025年度报告全文 + 截至整理日的最新严格季度报告",
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
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(
        ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
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
    ANNUAL_DIR.mkdir(parents=True)
    QUARTER_DIR.mkdir(parents=True)
    VERIFY_DIR.mkdir(parents=True)

    session = requests.Session()
    session.headers.update(HEADERS)
    org_id = find_org_id(session)
    stock_token = f"{STOCK_CODE},{org_id}"

    annual_rows = query_announcements(
        session, stock_token, category="category_ndbg_szsh"
    )
    quarter_rows = query_announcements(
        session, stock_token, searchkey="季度报告"
    )

    filings = choose_annual_reports(annual_rows)
    filings.append(choose_latest_quarter(quarter_rows))

    for sequence, filing in enumerate(filings, 1):
        target = PACKAGE_ROOT / filing.relative_path
        print(f"Downloading {sequence}/{len(filings)}: {filing.title}", flush=True)
        download_pdf(session, filing, target)
        validate_pdf(filing, target, sequence)
        print(
            f"Validated: {filing.local_filename} | {filing.pages} pages | "
            f"{filing.bytes} bytes",
            flush=True,
        )

    write_metadata(filings)
    build_zip()

    summary = {
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256_bytes(ZIP_PATH.read_bytes()),
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
    (ROOT / "package_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
