#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import sys
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pymupdf
import requests
from pypdf import PdfReader

AS_OF = "2026-10-28"
COMPANY_SHORT = "江顺科技"
COMPANY_FULL = "江苏江顺精密科技集团股份有限公司"
STOCK_CODE = "001400"
LISTING_DATE = "2025-04-24"

ROOT = Path("dist")
PACKAGE_NAME = f"{COMPANY_SHORT}_{STOCK_CODE}_全部年报_招股说明书_最新季报_截至{AS_OF.replace('-', '')}"
PACKAGE_ROOT = ROOT / PACKAGE_NAME
ANNUAL_DIR = PACKAGE_ROOT / "01_年度报告"
PROSPECTUS_DIR = PACKAGE_ROOT / "02_招股说明书"
QUARTER_DIR = PACKAGE_ROOT / "03_最新季报"
VERIFY_DIR = ROOT / "_verification_renders"
ZIP_PATH = ROOT / f"{PACKAGE_NAME}.zip"
SUMMARY_PATH = ROOT / "package_summary.json"

NOTICE_API = "https://np-anotice-stock.eastmoney.com/api/security/ann"
SESSION = requests.Session()
SESSION.trust_env = False
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "Chrome/155.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,application/pdf,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
)


@dataclass
class Document:
    document_type: str
    report_period: str
    title: str
    publication_date: str
    announcement_id: str
    source_pdf_url: str
    source_detail_url: str
    relative_path: str
    pages: int = 0
    bytes: int = 0
    sha256: str = ""
    company_identity_verified: bool = False
    first_last_page_rendered: bool = False


def clean_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", "", text).strip()


def title_of(row: dict[str, Any]) -> str:
    return clean_text(row.get("title_ch") or row.get("title") or row.get("notice_title"))


def date_of(row: dict[str, Any]) -> str:
    raw = str(row.get("display_time") or row.get("notice_date") or row.get("sort_date") or "")
    match = re.search(r"\d{4}-\d{2}-\d{2}", raw)
    return match.group(0) if match else ""


def request(method: str, url: str, *, timeout: tuple[int, int] = (20, 300), **kwargs: Any) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 8):
        try:
            response = SESSION.request(method, url, timeout=timeout, allow_redirects=True, **kwargs)
            print(
                "HTTP", method, url, "attempt", attempt, "status", response.status_code,
                "type", response.headers.get("content-type"),
                "length", response.headers.get("content-length"),
                "final", response.url,
                flush=True,
            )
            if response.status_code in {429, 500, 502, 503, 504}:
                response.close()
                time.sleep(min(attempt * 2, 12))
                continue
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            time.sleep(min(attempt * 2, 12))
    raise RuntimeError(f"Request failed for {method} {url}: {errors[-7:]}")


def fetch_notice_rows() -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for page in range(1, 20):
        params = {
            "sr": "-1",
            "page_size": "100",
            "page_index": str(page),
            "ann_type": "A",
            "client_source": "web",
            "stock_list": STOCK_CODE,
            "f_node": "0",
            "s_node": "0",
            "begin_time": "2020-01-01",
            "end_time": AS_OF,
        }
        response = request("GET", NOTICE_API, params=params, timeout=(20, 180))
        try:
            payload = response.json()
        finally:
            response.close()
        data = (payload or {}).get("data") or {}
        rows = data.get("list") or []
        total = int(data.get("total_hits") or data.get("total") or 0)
        print("NOTICE_PAGE", page, "rows", len(rows), "total", total, flush=True)
        collected.extend(row for row in rows if isinstance(row, dict))
        if not rows or len(rows) < 100 or (total and len(collected) >= total):
            break
    if not collected:
        raise RuntimeError(f"No announcement rows returned for stock {STOCK_CODE}")
    for row in collected:
        title = title_of(row)
        if any(token in title for token in ("年度报告", "季度报告", "招股说明书")):
            print("CANDIDATE", date_of(row), title, row.get("art_code"), flush=True)
    return collected


def revision_priority(title: str) -> int:
    if any(token in title for token in ("更新后", "更正后", "修订版", "修订后", "更正版")):
        return 5
    if any(token in title for token in ("更新", "更正", "修订")):
        return 3
    return 1


def valid_full_annual(title: str) -> bool:
    excluded = (
        "摘要", "英文", "取消", "提示性公告", "更正公告", "关于", "审计报告",
        "财务报表", "社会责任报告", "环境报告", "内部控制", "问询函", "回复",
    )
    return "年度报告" in title and not any(token in title for token in excluded)


def select_all_annuals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_year: dict[int, list[dict[str, Any]]] = {}
    pattern = re.compile(r"(20\d{2})年年度报告")
    for row in rows:
        title = title_of(row)
        if not valid_full_annual(title):
            continue
        match = pattern.search(title)
        if not match or not row.get("art_code"):
            continue
        year = int(match.group(1))
        # 江顺科技于2025年4月上市；这里收录上市后披露的完整年度报告。
        if year < 2025:
            continue
        by_year.setdefault(year, []).append(row)

    selected: list[dict[str, Any]] = []
    for year in sorted(by_year):
        candidates = by_year[year]
        candidates.sort(
            key=lambda row: (revision_priority(title_of(row)), date_of(row), str(row.get("art_code") or "")),
            reverse=True,
        )
        chosen = dict(candidates[0])
        chosen["title_norm"] = title_of(chosen)
        chosen["date_norm"] = date_of(chosen)
        chosen["fiscal_year"] = year
        selected.append(chosen)
        print("SELECTED_ANNUAL", year, json.dumps(chosen, ensure_ascii=False), flush=True)

    if not selected:
        raise RuntimeError("No complete post-listing annual report found")
    return selected


def select_formal_prospectus(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for row in rows:
        title = title_of(row)
        if "招股说明书" not in title or not row.get("art_code"):
            continue
        if any(token in title for token in ("申报稿", "提示性公告", "上市公告书", "招股意向书", "发行公告", "摘要")):
            continue
        score = 0
        if "首次公开发行股票并在主板上市招股说明书" in title:
            score += 1000
        if title.endswith("招股说明书"):
            score += 300
        if date_of(row) >= "2025-01-01":
            score += 200
        candidates.append((score, date_of(row), row))
    if not candidates:
        related = [title_of(row) for row in rows if "招股" in title_of(row)]
        raise RuntimeError(f"Formal prospectus not found; related={related[:30]}")
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = dict(candidates[0][2])
    selected["title_norm"] = title_of(selected)
    selected["date_norm"] = date_of(selected)
    print("SELECTED_PROSPECTUS", json.dumps(selected, ensure_ascii=False), flush=True)
    return selected


def quarter_rank(title: str) -> int:
    if any(token in title for token in ("第三季度报告", "三季度报告")):
        return 3
    if any(token in title for token in ("第一季度报告", "一季度报告")):
        return 1
    return 0


def select_latest_quarter(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[tuple[int, int, int, str, dict[str, Any]]] = []
    pattern = re.compile(r"(20\d{2})年(?:第)?(一|三)季度报告")
    for row in rows:
        title = title_of(row)
        if "季度报告" not in title or not row.get("art_code"):
            continue
        if any(token in title for token in ("摘要", "英文", "提示性公告", "更正公告", "关于", "取消")):
            continue
        match = pattern.search(title)
        if not match:
            continue
        year = int(match.group(1))
        rank = quarter_rank(title)
        if not rank:
            continue
        candidates.append((year, rank, revision_priority(title), date_of(row), row))
    if not candidates:
        raise RuntimeError("No first- or third-quarter report found")
    candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)
    year, rank, _, _, row = candidates[0]
    selected = dict(row)
    selected["title_norm"] = title_of(selected)
    selected["date_norm"] = date_of(selected)
    selected["fiscal_year"] = year
    selected["quarter_rank"] = rank
    selected["quarter_label"] = "第三季度报告" if rank == 3 else "第一季度报告"
    print("SELECTED_QUARTER", json.dumps(selected, ensure_ascii=False), flush=True)
    return selected


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detail_url(announcement_id: str) -> str:
    return f"https://data.eastmoney.com/notices/detail/{STOCK_CODE}/{announcement_id}.html"


def download_pdf(announcement_id: str, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for prefix in ("H2", "H3"):
        url = f"https://pdf.dfcfw.com/pdf/{prefix}_{announcement_id}_1.pdf"
        temp = destination.with_suffix(destination.suffix + ".part")
        temp.unlink(missing_ok=True)
        try:
            response = request(
                "GET",
                url,
                timeout=(25, 600),
                stream=True,
                headers={"Referer": "https://data.eastmoney.com/"},
            )
            try:
                with temp.open("wb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            handle.write(chunk)
                final_url = str(response.url)
            finally:
                response.close()
            size = temp.stat().st_size if temp.exists() else 0
            head = temp.read_bytes()[:8] if temp.exists() else b""
            if size < 20_000 or not head.startswith(b"%PDF-"):
                raise RuntimeError(f"Invalid PDF bytes={size}, head={head!r}")
            temp.replace(destination)
            print("DOWNLOADED", destination, destination.stat().st_size, final_url, flush=True)
            return final_url
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc!r}")
            temp.unlink(missing_ok=True)
    raise RuntimeError(f"Could not download PDF for {announcement_id}: {errors}")


def render_verification_pages(path: Path, document: Document) -> None:
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    pdf = pymupdf.open(path)
    try:
        for label, index in (("first", 0), ("last", document.pages - 1)):
            page = pdf.load_page(index)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(0.9, 0.9), alpha=False)
            out = VERIFY_DIR / f"{path.stem}_{label}.png"
            pix.save(out)
            if out.stat().st_size < 4_000:
                raise RuntimeError(f"Rendered verification page is suspiciously small: {out}")
    finally:
        pdf.close()
    document.first_last_page_rendered = True


def validate_pdf(path: Path, document: Document, min_pages: int) -> None:
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF-"):
        raise RuntimeError(f"PDF header invalid: {path}")
    document.bytes = len(raw)
    document.sha256 = hashlib.sha256(raw).hexdigest()

    reader = PdfReader(str(path), strict=False)
    document.pages = len(reader.pages)
    if document.pages < min_pages:
        raise RuntimeError(f"Unexpectedly short PDF {path.name}: {document.pages} pages")

    indices = sorted({0, min(1, document.pages - 1), min(5, document.pages - 1), document.pages // 2, document.pages - 1})
    text_parts: list[str] = []
    for index in indices:
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_WARNING", path.name, index + 1, repr(exc), flush=True)
    normalized = re.sub(r"\s+", "", "\n".join(text_parts))
    document.company_identity_verified = any(
        token in normalized for token in (COMPANY_SHORT, COMPANY_FULL, STOCK_CODE, "江顺精密")
    )
    if normalized and not document.company_identity_verified:
        raise RuntimeError(f"Company identity not found in sampled text: {path.name}")

    first_text = ""
    for index in range(min(10, document.pages)):
        try:
            first_text += reader.pages[index].extract_text() or ""
        except Exception:
            pass
    first_normalized = re.sub(r"\s+", "", first_text)
    if document.document_type == "年度报告":
        if "年度报告摘要" in first_normalized:
            raise RuntimeError(f"Annual-report summary detected: {path.name}")
        if first_normalized and "年度报告" not in first_normalized:
            raise RuntimeError(f"Annual-report marker missing: {path.name}")
    elif document.document_type == "招股说明书":
        if first_normalized and "招股说明书" not in first_normalized:
            raise RuntimeError(f"Prospectus marker missing: {path.name}")
        if "申报稿" in first_normalized:
            raise RuntimeError(f"Draft prospectus detected instead of formal issue version: {path.name}")
    else:
        if first_normalized and "季度报告" not in first_normalized:
            raise RuntimeError(f"Quarterly-report marker missing: {path.name}")

    render_verification_pages(path, document)


def write_metadata(documents: list[Document], annual_years: list[int], latest: Document) -> None:
    PACKAGE_ROOT.mkdir(parents=True, exist_ok=True)
    readme = f"""{COMPANY_SHORT}（{STOCK_CODE}）全部年度报告、正式招股说明书及最新季度报告

核对日期：{AS_OF}
上市日期：{LISTING_DATE}
上市后完整年度报告年份：{', '.join(map(str, annual_years))}
最新严格季度报告：《{latest.title}》
最新季报披露日期：{latest.publication_date}

范围说明：
1. “全部年报”按上市公司法定定期报告口径，收录上市后截至核对日期已经披露的全部年度报告全文。
2. 公司于2025年4月上市，因此当前上市后完整年度报告仅有2025年年度报告；2024年及以前经营与财务历史已在正式发行版招股说明书中披露，但不存在上市公司年度报告全文。
3. 招股说明书收录2025年正式发行版，排除申报稿、招股意向书、提示性公告和上市公告书。
4. 最新季报按第一季度/第三季度报告口径选择，不以半年报替代。

校验：PDF文件头、实际页数、公司身份、首页和末页渲染、SHA-256及ZIP CRC。
PDF数量：{len(documents)}份
"""
    (PACKAGE_ROOT / "00_文件清单与范围说明.txt").write_text(readme, encoding="utf-8")

    with (PACKAGE_ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "类别", "报告期", "标题", "披露日期", "实际页数", "字节数", "SHA-256",
            "本地路径", "PDF来源", "公告详情页",
        ])
        for document in documents:
            writer.writerow([
                document.document_type,
                document.report_period,
                document.title,
                document.publication_date,
                document.pages,
                document.bytes,
                document.sha256,
                document.relative_path,
                document.source_pdf_url,
                document.source_detail_url,
            ])

    manifest = {
        "company": COMPANY_SHORT,
        "company_full_name": COMPANY_FULL,
        "stock_code": STOCK_CODE,
        "listing_date": LISTING_DATE,
        "as_of": AS_OF,
        "annual_report_years": annual_years,
        "latest_quarterly_report": latest.title,
        "latest_quarterly_report_date": latest.publication_date,
        "scope": "上市后全部年度报告全文 + 正式发行版招股说明书 + 截至核对日期最新严格季度报告",
        "documents": [asdict(document) for document in documents],
    }
    (PACKAGE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (PACKAGE_ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{document.sha256}  {document.relative_path}" for document in documents) + "\n",
        encoding="utf-8",
    )


def create_zip(expected_pdf_count: int) -> None:
    ZIP_PATH.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(PACKAGE_ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(ROOT))
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")
        pdf_count = sum(name.lower().endswith(".pdf") for name in archive.namelist())
        if pdf_count != expected_pdf_count:
            raise RuntimeError(f"Expected {expected_pdf_count} PDFs in final ZIP, found {pdf_count}")


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    for directory in (ANNUAL_DIR, PROSPECTUS_DIR, QUARTER_DIR, VERIFY_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    rows = fetch_notice_rows()
    annual_rows = select_all_annuals(rows)
    prospectus_row = select_formal_prospectus(rows)
    quarter_row = select_latest_quarter(rows)

    documents: list[Document] = []
    annual_years: list[int] = []

    for row in annual_rows:
        year = int(row["fiscal_year"])
        annual_years.append(year)
        title = str(row["title_norm"])
        revised = any(token in title for token in ("修订", "更新", "更正"))
        suffix = "_修订版" if revised else ""
        relative_path = f"01_年度报告/{year}_{COMPANY_SHORT}_年度报告全文{suffix}.pdf"
        destination = PACKAGE_ROOT / relative_path
        source_pdf_url = download_pdf(str(row["art_code"]), destination)
        document = Document(
            document_type="年度报告",
            report_period=str(year),
            title=title,
            publication_date=str(row["date_norm"]),
            announcement_id=str(row["art_code"]),
            source_pdf_url=source_pdf_url,
            source_detail_url=detail_url(str(row["art_code"])),
            relative_path=relative_path,
        )
        validate_pdf(destination, document, min_pages=80)
        documents.append(document)
        print("VALIDATED", json.dumps(asdict(document), ensure_ascii=False), flush=True)

    prospectus_title = str(prospectus_row["title_norm"])
    relative_path = f"02_招股说明书/2025_{COMPANY_SHORT}_首次公开发行股票并在主板上市招股说明书_正式发行版.pdf"
    destination = PACKAGE_ROOT / relative_path
    source_pdf_url = download_pdf(str(prospectus_row["art_code"]), destination)
    prospectus = Document(
        document_type="招股说明书",
        report_period="2025_IPO",
        title=prospectus_title,
        publication_date=str(prospectus_row["date_norm"]),
        announcement_id=str(prospectus_row["art_code"]),
        source_pdf_url=source_pdf_url,
        source_detail_url=detail_url(str(prospectus_row["art_code"])),
        relative_path=relative_path,
    )
    validate_pdf(destination, prospectus, min_pages=150)
    documents.append(prospectus)
    print("VALIDATED", json.dumps(asdict(prospectus), ensure_ascii=False), flush=True)

    rank = int(quarter_row["quarter_rank"])
    quarter_label = str(quarter_row["quarter_label"])
    quarter_code = "Q3" if rank == 3 else "Q1"
    quarter_year = int(quarter_row["fiscal_year"])
    relative_path = f"03_最新季报/{quarter_year}_{quarter_code}_{COMPANY_SHORT}_{quarter_label}.pdf"
    destination = PACKAGE_ROOT / relative_path
    source_pdf_url = download_pdf(str(quarter_row["art_code"]), destination)
    latest = Document(
        document_type="季度报告",
        report_period=f"{quarter_year}_{quarter_code}",
        title=str(quarter_row["title_norm"]),
        publication_date=str(quarter_row["date_norm"]),
        announcement_id=str(quarter_row["art_code"]),
        source_pdf_url=source_pdf_url,
        source_detail_url=detail_url(str(quarter_row["art_code"])),
        relative_path=relative_path,
    )
    validate_pdf(destination, latest, min_pages=8)
    documents.append(latest)
    print("VALIDATED", json.dumps(asdict(latest), ensure_ascii=False), flush=True)

    write_metadata(documents, annual_years, latest)
    create_zip(len(documents))

    summary = {
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256_file(ZIP_PATH),
        "pdf_count": len(documents),
        "annual_report_years": annual_years,
        "scope": "上市后全部年度报告全文 + 正式发行版招股说明书 + 最新严格季度报告",
        "latest_quarterly_report": latest.title,
        "latest_quarterly_report_date": latest.publication_date,
        "documents": [
            {
                "type": document.document_type,
                "period": document.report_period,
                "title": document.title,
                "publication_date": document.publication_date,
                "pages": document.pages,
                "bytes": document.bytes,
            }
            for document in documents
        ],
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PACKAGE_SUMMARY=" + json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
