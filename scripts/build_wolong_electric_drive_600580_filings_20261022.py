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

AS_OF = "2026-10-22"
COMPANY_SHORT = "卧龙电驱"
COMPANY_FULL = "卧龙电气驱动集团股份有限公司"
STOCK_CODE = "600580"
ANNUAL_YEARS = list(range(2020, 2026))

ROOT = Path("dist")
PACKAGE_NAME = f"{COMPANY_SHORT}_{STOCK_CODE}_2020-2025年报_最新季报_截至{AS_OF.replace('-', '')}"
PACKAGE_ROOT = ROOT / PACKAGE_NAME
ANNUAL_DIR = PACKAGE_ROOT / "01_年度报告"
QUARTER_DIR = PACKAGE_ROOT / "02_最新季报"
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
    return clean_text(row.get("title_ch") or row.get("title"))


def date_of(row: dict[str, Any]) -> str:
    raw = str(row.get("display_time") or row.get("notice_date") or row.get("sort_date") or "")
    match = re.search(r"\d{4}-\d{2}-\d{2}", raw)
    return match.group(0) if match else ""


def columns_of(row: dict[str, Any]) -> list[str]:
    columns = row.get("columns") or []
    result: list[str] = []
    for item in columns:
        if isinstance(item, dict):
            result.append(clean_text(item.get("column_name")))
    return result


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
    for ann_type in ("SHA", "SH"):
        collected: list[dict[str, Any]] = []
        for page in range(1, 20):
            params = {
                "sr": "-1",
                "page_size": "100",
                "page_index": str(page),
                "ann_type": ann_type,
                "client_source": "web",
                "stock_list": STOCK_CODE,
                "f_node": "0",
                "s_node": "0",
                "begin_time": "2021-01-01",
                "end_time": AS_OF,
            }
            response = request("GET", NOTICE_API, params=params, timeout=(20, 180))
            try:
                payload = response.json()
            finally:
                response.close()
            rows = (((payload or {}).get("data") or {}).get("list") or [])
            print("NOTICE_PAGE", ann_type, page, "rows", len(rows), flush=True)
            collected.extend(row for row in rows if isinstance(row, dict))
            if len(rows) < 100:
                break
        if collected:
            print("NOTICE_ROWS_COUNT", len(collected), "ANN_TYPE", ann_type, flush=True)
            for row in collected:
                title = title_of(row)
                if "年度报告" in title or "季度报告" in title:
                    print("CANDIDATE", date_of(row), title, row.get("art_code"), columns_of(row), flush=True)
            return collected
    raise RuntimeError(f"No announcement rows returned for stock {STOCK_CODE}")


def annual_score(row: dict[str, Any], year: int) -> int:
    title = title_of(row)
    columns = columns_of(row)
    score = 0
    if any(name == "年度报告全文" for name in columns):
        score += 500
    if re.search(fr"{year}年?年度报告(?:全文)?(?:[(（].*(?:修订|更新|更正).*[)）])?$", title):
        score += 350
    if f"{year}年年度报告" in title:
        score += 250
    if any(token in title for token in ("修订版", "更新后", "更正版", "修订后", "更正后")):
        score += 100
    if any(token in title for token in ("摘要", "英文", "取消", "提示性公告")):
        score -= 1000
    if any(token in title for token in ("审计报告", "问询函", "回复公告", "社会责任报告", "环境报告")):
        score -= 1000
    score += int(date_of(row).replace("-", "") or "0") // 10000
    return score


def select_annual(rows: list[dict[str, Any]], year: int) -> dict[str, Any]:
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for row in rows:
        title = title_of(row)
        if str(year) not in title or "年度报告" not in title:
            continue
        if any(token in title for token in ("摘要", "英文", "取消", "提示性公告")):
            continue
        score = annual_score(row, year)
        if score > 0 and row.get("art_code"):
            candidates.append((score, date_of(row), row))
    if not candidates:
        related = [title_of(row) for row in rows if str(year) in title_of(row)]
        raise RuntimeError(f"No annual report found for {year}; related titles={related[:40]}")
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = dict(candidates[0][2])
    selected["title_norm"] = title_of(selected)
    selected["date_norm"] = date_of(selected)
    selected["fiscal_year"] = year
    print("SELECTED_ANNUAL", year, selected["date_norm"], selected["title_norm"], selected.get("art_code"), flush=True)
    return selected


def quarter_rank(title: str) -> int:
    if any(token in title for token in ("第三季度报告", "三季度报告")):
        return 3
    if any(token in title for token in ("第一季度报告", "一季度报告")):
        return 1
    return 0


def select_latest_quarter(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for row in rows:
        title = title_of(row)
        if "2026" not in title or "季度报告" not in title:
            continue
        if any(token in title for token in ("摘要", "英文", "提示性公告")):
            continue
        rank = quarter_rank(title)
        if rank and row.get("art_code"):
            candidates.append((rank, date_of(row), row))
    if not candidates:
        related = [title_of(row) for row in rows if "2026" in title_of(row)]
        raise RuntimeError(f"No 2026 quarterly report found; related titles={related[:60]}")
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    rank, _, row = candidates[0]
    selected = dict(row)
    selected["title_norm"] = title_of(selected)
    selected["date_norm"] = date_of(selected)
    selected["fiscal_year"] = 2026
    selected["quarter_rank"] = rank
    selected["quarter_label"] = "第三季度报告" if rank == 3 else "第一季度报告"
    print("SELECTED_QUARTER", selected["date_norm"], selected["title_norm"], selected.get("art_code"), flush=True)
    return selected


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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

    indices = sorted({0, 1, min(2, document.pages - 1), min(5, document.pages - 1), document.pages // 2, document.pages - 1})
    text_parts: list[str] = []
    for index in indices:
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_WARNING", path.name, index + 1, repr(exc), flush=True)
    normalized = re.sub(r"\s+", "", "\n".join(text_parts))
    document.company_identity_verified = any(
        token in normalized for token in (COMPANY_SHORT, COMPANY_FULL, STOCK_CODE, "卧龙电气")
    )
    if normalized and not document.company_identity_verified:
        raise RuntimeError(f"Company identity not found in sampled text: {path.name}")

    first_pages_text = ""
    for index in range(min(8, document.pages)):
        try:
            first_pages_text += reader.pages[index].extract_text() or ""
        except Exception:
            pass
    first_normalized = re.sub(r"\s+", "", first_pages_text)
    if document.document_type == "年度报告":
        if "年度报告摘要" in first_normalized:
            raise RuntimeError(f"Annual-report summary detected: {path.name}")
        if first_normalized and "年度报告" not in first_normalized:
            raise RuntimeError(f"Annual-report marker missing: {path.name}")
        if first_normalized and document.report_period not in first_normalized:
            raise RuntimeError(f"Annual-report year missing: {path.name}")
    else:
        if first_normalized and "季度报告" not in first_normalized:
            raise RuntimeError(f"Quarterly-report marker missing: {path.name}")

    render_verification_pages(path, document)


def detail_url(announcement_id: str) -> str:
    return f"https://data.eastmoney.com/notices/detail/{STOCK_CODE}/{announcement_id}.html"


def write_metadata(documents: list[Document], latest: Document, q3_disclosed: bool) -> None:
    PACKAGE_ROOT.mkdir(parents=True, exist_ok=True)
    readme = f"""{COMPANY_SHORT}（{STOCK_CODE}）2020—2025年年度报告及最新季度报告

核对日期：{AS_OF}
公司全称：{COMPANY_FULL}
收录范围：2020、2021、2022、2023、2024、2025年年度报告全文，以及截至核对日期已披露的最新严格季度报告《{latest.title}》。
最新季报披露日期：{latest.publication_date}
2026年第三季度报告是否已在公告索引中检出：{'是' if q3_disclosed else '否'}
半年报不属于季度报告，未用于替代最新季报。
已排除年度报告摘要、英文版、公告提示、审计附件及重复/被替代版本。

校验：PDF文件头、实际页数、公司身份、首页和末页渲染、SHA-256及ZIP CRC。
PDF数量：{len(documents)}份
"""
    (PACKAGE_ROOT / "README.txt").write_text(readme, encoding="utf-8")

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
        "as_of": AS_OF,
        "annual_report_years": ANNUAL_YEARS,
        "latest_quarterly_report": latest.title,
        "latest_quarterly_report_date": latest.publication_date,
        "q3_2026_disclosed_in_checked_index": q3_disclosed,
        "scope": "2020—2025年年度报告全文 + 截至核对日期的最新严格季度报告",
        "documents": [asdict(document) for document in documents],
    }
    (PACKAGE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (PACKAGE_ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{document.sha256}  {document.relative_path}" for document in documents) + "\n",
        encoding="utf-8",
    )


def create_zip() -> None:
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
        if pdf_count != 7:
            raise RuntimeError(f"Expected 7 PDFs in final ZIP, found {pdf_count}")


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    ANNUAL_DIR.mkdir(parents=True, exist_ok=True)
    QUARTER_DIR.mkdir(parents=True, exist_ok=True)
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)

    rows = fetch_notice_rows()
    annual_rows = [select_annual(rows, year) for year in ANNUAL_YEARS]
    quarter_row = select_latest_quarter(rows)

    documents: list[Document] = []
    seen_hashes: set[str] = set()
    for row in annual_rows:
        year = int(row["fiscal_year"])
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
        if document.sha256 in seen_hashes:
            raise RuntimeError(f"Duplicate PDF detected: {destination.name}")
        seen_hashes.add(document.sha256)
        documents.append(document)
        print("VALIDATED", json.dumps(asdict(document), ensure_ascii=False), flush=True)

    rank = int(quarter_row["quarter_rank"])
    quarter_label = str(quarter_row["quarter_label"])
    quarter_code = "Q3" if rank == 3 else "Q1"
    relative_path = f"02_最新季报/2026_{quarter_code}_{COMPANY_SHORT}_{quarter_label}.pdf"
    destination = PACKAGE_ROOT / relative_path
    source_pdf_url = download_pdf(str(quarter_row["art_code"]), destination)
    latest = Document(
        document_type="季度报告",
        report_period=f"2026_{quarter_code}",
        title=str(quarter_row["title_norm"]),
        publication_date=str(quarter_row["date_norm"]),
        announcement_id=str(quarter_row["art_code"]),
        source_pdf_url=source_pdf_url,
        source_detail_url=detail_url(str(quarter_row["art_code"])),
        relative_path=relative_path,
    )
    validate_pdf(destination, latest, min_pages=5)
    if latest.sha256 in seen_hashes:
        raise RuntimeError(f"Duplicate PDF detected: {destination.name}")
    documents.append(latest)
    print("VALIDATED", json.dumps(asdict(latest), ensure_ascii=False), flush=True)

    write_metadata(documents, latest, q3_disclosed=(rank == 3))
    create_zip()

    summary = {
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256_file(ZIP_PATH),
        "pdf_count": len(documents),
        "scope": "2020—2025年年度报告全文 + 最新严格季度报告",
        "latest_quarterly_report": latest.title,
        "latest_quarterly_report_date": latest.publication_date,
        "q3_2026_disclosed_in_checked_index": rank == 3,
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
