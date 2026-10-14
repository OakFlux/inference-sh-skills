#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

import pymupdf
import requests
from pypdf import PdfReader

COMPANY_SHORT = "美农生物"
COMPANY_FULL = "上海美农生物科技股份有限公司"
STOCK_CODE = "301156"
ORG_ID = "gfbj0873489"
AS_OF = "2026-10-14"

ROOT = Path("dist")
PACKAGE_NAME = f"{COMPANY_SHORT}_{STOCK_CODE}_全部年报_招股说明书_最新季报"
PACKAGE_ROOT = ROOT / PACKAGE_NAME
ZIP_PATH = ROOT / f"{PACKAGE_NAME}_20261014.zip"
VERIFY_DIR = ROOT / "_verification_renders"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,application/octet-stream,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={STOCK_CODE}",
}


@dataclass
class Document:
    document_type: str
    report_period: str
    title: str
    publication_date: str
    announcement_id: str
    pdf_url: str
    detail_url: str
    relative_path: str
    pages: int = 0
    bytes: int = 0
    sha256: str = ""
    company_identity_verified: bool = False
    first_last_page_rendered: bool = False


def detail_url(announcement_id: str) -> str:
    return (
        "https://www.cninfo.com.cn/new/disclosure/detail"
        f"?stockCode={STOCK_CODE}&announcementId={announcement_id}&orgId={ORG_ID}"
    )


DOCUMENTS = [
    Document(
        document_type="年度报告",
        report_period="2022",
        title="2022年年度报告",
        publication_date="2023-04-26",
        announcement_id="1216581273",
        pdf_url="https://static.cninfo.com.cn/finalpage/2023-04-26/1216581273.PDF",
        detail_url=detail_url("1216581273"),
        relative_path="01_年度报告/2022_美农生物_年度报告_巨潮资讯官方.pdf",
    ),
    Document(
        document_type="年度报告",
        report_period="2023",
        title="2023年年度报告",
        publication_date="2024-04-09",
        announcement_id="1219538819",
        pdf_url="https://static.cninfo.com.cn/finalpage/2024-04-09/1219538819.PDF",
        detail_url=detail_url("1219538819"),
        relative_path="01_年度报告/2023_美农生物_年度报告_巨潮资讯官方.pdf",
    ),
    Document(
        document_type="年度报告",
        report_period="2024",
        title="2024年年度报告",
        publication_date="2025-04-26",
        announcement_id="1223300140",
        pdf_url="https://static.cninfo.com.cn/finalpage/2025-04-26/1223300140.PDF",
        detail_url=detail_url("1223300140"),
        relative_path="01_年度报告/2024_美农生物_年度报告_巨潮资讯官方.pdf",
    ),
    Document(
        document_type="年度报告",
        report_period="2025",
        title="2025年年度报告",
        publication_date="2026-04-28",
        announcement_id="1225201776",
        pdf_url="https://static.cninfo.com.cn/finalpage/2026-04-28/1225201776.PDF",
        detail_url=detail_url("1225201776"),
        relative_path="01_年度报告/2025_美农生物_年度报告_巨潮资讯官方.pdf",
    ),
    Document(
        document_type="招股说明书",
        report_period="IPO",
        title="首次公开发行股票并在创业板上市招股说明书",
        publication_date="2022-06-06",
        announcement_id="1213606430",
        pdf_url="https://static.cninfo.com.cn/finalpage/2022-06-06/1213606430.PDF",
        detail_url=detail_url("1213606430"),
        relative_path="02_招股说明书/2022_美农生物_首次公开发行股票并在创业板上市招股说明书_巨潮资讯官方.pdf",
    ),
    Document(
        document_type="季度报告",
        report_period="2026_Q1",
        title="2026年一季度报告",
        publication_date="2026-04-28",
        announcement_id="1225201785",
        pdf_url="https://static.cninfo.com.cn/finalpage/2026-04-28/1225201785.PDF",
        detail_url=detail_url("1225201785"),
        relative_path="03_最新季报/2026_Q1_美农生物_第一季度报告_巨潮资讯官方.pdf",
    ),
]


def download_pdf(session: requests.Session, document: Document) -> Path:
    path = PACKAGE_ROOT / document.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    error: Exception | None = None
    for attempt in range(1, 6):
        try:
            headers = {**HEADERS, "Referer": document.detail_url}
            with session.get(document.pdf_url, headers=headers, stream=True, timeout=180) as response:
                response.raise_for_status()
                with path.open("wb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            raw = path.read_bytes()
            if not raw.startswith(b"%PDF"):
                raise RuntimeError(f"Downloaded content is not PDF: {document.pdf_url}")
            if len(raw) < 50_000:
                raise RuntimeError(f"Downloaded PDF is too small ({len(raw)} bytes): {document.pdf_url}")
            return path
        except Exception as exc:  # noqa: BLE001
            error = exc
            path.unlink(missing_ok=True)
            if attempt < 5:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Failed to download {document.title}: {error}")


def verify_pdf(path: Path, document: Document) -> None:
    raw = path.read_bytes()
    document.bytes = len(raw)
    document.sha256 = hashlib.sha256(raw).hexdigest()

    reader = PdfReader(str(path), strict=False)
    document.pages = len(reader.pages)
    if document.document_type == "招股说明书":
        minimum_pages = 200
    elif document.document_type == "年度报告":
        minimum_pages = 100
    else:
        minimum_pages = 8
    if document.pages < minimum_pages:
        raise RuntimeError(
            f"Unexpected page count for {path.name}: {document.pages} < {minimum_pages}"
        )

    pdf = pymupdf.open(path)
    text = ""
    for index in range(min(12, document.pages)):
        text += pdf.load_page(index).get_text("text")
    normalized = text.replace(" ", "").replace("\n", "")
    document.company_identity_verified = any(
        token in normalized for token in (COMPANY_SHORT, COMPANY_FULL, STOCK_CODE)
    )
    if not document.company_identity_verified:
        raise RuntimeError(f"Company identity was not verified in {path.name}")

    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    for label, index in (("first", 0), ("last", document.pages - 1)):
        page = pdf.load_page(index)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(0.85, 0.85), alpha=False)
        out = VERIFY_DIR / f"{path.stem}_{label}.png"
        pix.save(out)
        if out.stat().st_size < 5_000:
            raise RuntimeError(f"Rendered verification page is suspiciously small: {out}")
    document.first_last_page_rendered = True
    pdf.close()


def write_metadata(documents: list[Document]) -> None:
    latest = next(d for d in documents if d.document_type == "季度报告")
    note = f"""{COMPANY_SHORT}（{STOCK_CODE}）官方披露文件包

收录范围：
1. 上市后全部完整年度报告：2022、2023、2024、2025年度。
2. 首次公开发行股票并在创业板上市的最终版招股说明书。
3. 截至{AS_OF}的最新严格季度报告：《{latest.title}》，披露日期为{latest.publication_date}。
4. 2026年半年度报告不属于季度报告，因此未用于替代季报；截至上述日期尚未披露2026年第三季度报告。
5. 已排除年度报告摘要、招股书确认意见、半年报、审计附件、公告摘要及重复版本。

来源：巨潮资讯网官方公开PDF端点。
校验：PDF文件头、实际页数、公司身份、首末页渲染、SHA-256及ZIP CRC。
生成日期：{AS_OF}
PDF数量：{len(documents)}份
"""
    (PACKAGE_ROOT / "00_文件清单与范围说明.txt").write_text(note, encoding="utf-8")

    with (PACKAGE_ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "类别", "报告期", "文件标题", "披露日期", "实际页数", "文件大小（字节）",
            "SHA-256", "本地路径", "官方PDF地址", "公告详情地址",
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
                document.pdf_url,
                document.detail_url,
            ])

    manifest = {
        "company": COMPANY_SHORT,
        "company_full_name": COMPANY_FULL,
        "stock_code": STOCK_CODE,
        "cninfo_org_id": ORG_ID,
        "as_of": AS_OF,
        "source": "巨潮资讯网（CNINFO）官方公开披露",
        "scope": {
            "annual_report_years": [2022, 2023, 2024, 2025],
            "prospectus": "首次公开发行股票并在创业板上市最终版招股说明书",
            "latest_quarterly_report": latest.title,
            "latest_quarterly_report_date": latest.publication_date,
        },
        "documents": [asdict(document) for document in documents],
    }
    (PACKAGE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (PACKAGE_ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{d.sha256}  {d.relative_path}" for d in documents) + "\n",
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


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    PACKAGE_ROOT.mkdir(parents=True, exist_ok=True)
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(HEADERS)

    for document in DOCUMENTS:
        path = download_pdf(session, document)
        verify_pdf(path, document)
        print(
            "VALIDATED",
            json.dumps(
                {
                    "type": document.document_type,
                    "period": document.report_period,
                    "title": document.title,
                    "publication_date": document.publication_date,
                    "pages": document.pages,
                    "bytes": document.bytes,
                    "sha256": document.sha256,
                },
                ensure_ascii=False,
            ),
        )

    write_metadata(DOCUMENTS)
    create_zip()

    summary = {
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest(),
        "pdf_count": len(DOCUMENTS),
        "documents": [
            {
                "type": d.document_type,
                "period": d.report_period,
                "title": d.title,
                "publication_date": d.publication_date,
                "pages": d.pages,
                "bytes": d.bytes,
            }
            for d in DOCUMENTS
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
