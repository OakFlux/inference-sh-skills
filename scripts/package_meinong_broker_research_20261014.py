#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import pymupdf
import requests
from pypdf import PdfReader

COMPANY = "美农生物"
COMPANY_FULL = "上海美农生物科技股份有限公司"
STOCK_CODE = "301156"
AS_OF = "2026-10-14"

ROOT = Path("dist_meinong_broker")
PACKAGE_ROOT = ROOT / f"{COMPANY}_{STOCK_CODE}_券商研究与深度尽调资料"
RESEARCH_DIR = PACKAGE_ROOT / "01_公开公司研究报告"
DUE_DILIGENCE_DIR = PACKAGE_ROOT / "02_中泰证券保荐与持续督导材料"
VERIFY_DIR = ROOT / "_verification_renders"
ZIP_PATH = ROOT / f"{COMPANY}_{STOCK_CODE}_券商研究与深度尽调资料_3份_20261014.zip"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


@dataclass
class Document:
    sequence: int
    category: str
    nature: str
    institution: str
    analyst: str
    publish_date: str
    title: str
    source_page: str
    pdf_url: str
    local_filename: str
    relative_path: str
    expected_min_pages: int
    pages: int = 0
    bytes: int = 0
    sha256: str = ""
    first_last_page_rendered: bool = False
    identity_verified: bool = False


DOCUMENTS = [
    Document(
        sequence=1,
        category="公开公司研究报告",
        nature="机构公司研究报告；篇幅较短，不属于20页以上传统长篇深度报告",
        institution="环球富盛理财",
        analyst="庄怀超",
        publish_date="2025-07-10",
        title="深耕饲料添加剂和酶解蛋白饲料原料业务，重点突破海外市场",
        source_page="https://data.eastmoney.com/report/info/AP202507101706481801.html",
        pdf_url="https://pdf.dfcfw.com/pdf/H3_AP202507101706481801_1.pdf",
        local_filename="01_20250710_环球富盛理财_深耕饲料添加剂和酶解蛋白饲料原料业务，重点突破海外市场.pdf",
        relative_path="01_公开公司研究报告/01_20250710_环球富盛理财_深耕饲料添加剂和酶解蛋白饲料原料业务，重点突破海外市场.pdf",
        expected_min_pages=3,
    ),
    Document(
        sequence=2,
        category="中泰证券保荐与持续督导材料",
        nature="证券公司IPO保荐工作报告；属于保荐尽调材料，不是卖方评级研报",
        institution="中泰证券",
        analyst="保荐机构项目组",
        publish_date="2022-06-06",
        title="关于公司首次公开发行股票并在创业板上市之保荐工作报告",
        source_page="https://www.cninfo.com.cn/new/disclosure/detail?stockCode=301156&announcementId=1213606415",
        pdf_url="https://static.cninfo.com.cn/finalpage/2022-06-06/1213606415.PDF",
        local_filename="02_20220606_中泰证券_首次公开发行股票并在创业板上市之保荐工作报告.pdf",
        relative_path="02_中泰证券保荐与持续督导材料/02_20220606_中泰证券_首次公开发行股票并在创业板上市之保荐工作报告.pdf",
        expected_min_pages=20,
    ),
    Document(
        sequence=3,
        category="中泰证券保荐与持续督导材料",
        nature="证券公司持续督导保荐总结；属于官方保荐材料，不是卖方评级研报",
        institution="中泰证券",
        analyst="保荐代表人",
        publish_date="2026-05-13",
        title="首次公开发行股票并在创业板上市持续督导保荐总结报告书",
        source_page="https://www.cninfo.com.cn/new/disclosure/detail?stockCode=301156&announcementId=1225303368",
        pdf_url="https://static.cninfo.com.cn/finalpage/2026-05-13/1225303368.PDF",
        local_filename="03_20260513_中泰证券_持续督导保荐总结报告书.pdf",
        relative_path="02_中泰证券保荐与持续督导材料/03_20260513_中泰证券_持续督导保荐总结报告书.pdf",
        expected_min_pages=3,
    ),
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download_pdf(session: requests.Session, document: Document, target: Path) -> None:
    urls = [document.pdf_url]
    if "pdf.dfcfw.com" in document.pdf_url:
        urls.extend([
            document.pdf_url + "?1752132928000.pdf=",
            document.pdf_url.replace("https://", "http://"),
        ])

    last_error = None
    for url in urls:
        for attempt in range(1, 5):
            try:
                headers = dict(HEADERS)
                headers["Referer"] = document.source_page
                response = session.get(url, headers=headers, timeout=120, allow_redirects=True)
                response.raise_for_status()
                payload = response.content
                if not payload.startswith(b"%PDF"):
                    raise RuntimeError(
                        f"Non-PDF response from {url}: {response.status_code}, "
                        f"{response.headers.get('content-type')}, {len(payload)} bytes"
                    )
                if len(payload) < 20_000:
                    raise RuntimeError(f"Suspiciously small PDF from {url}: {len(payload)} bytes")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                document.pdf_url = response.url
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < 4:
                    time.sleep(attempt * 1.5)
    raise RuntimeError(f"Unable to download {document.title}: {last_error}")


def collect_text(reader: PdfReader, limit: int = 12) -> str:
    chunks: list[str] = []
    for page in reader.pages[: min(limit, len(reader.pages))]:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            pass
    return "\n".join(chunks)


def render_page(pdf_path: Path, page_index: int, output_path: Path) -> None:
    with pymupdf.open(pdf_path) as doc:
        page = doc[page_index]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6), alpha=False)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(output_path)
        if output_path.stat().st_size < 5_000:
            raise RuntimeError(f"Rendered image too small: {output_path}")


def validate_pdf(document: Document, pdf_path: Path) -> None:
    reader = PdfReader(str(pdf_path), strict=False)
    page_count = len(reader.pages)
    if page_count < document.expected_min_pages:
        raise RuntimeError(
            f"Unexpected page count for {document.title}: {page_count} < {document.expected_min_pages}"
        )

    text = collect_text(reader)
    normalized = "".join(text.split())
    company_ok = COMPANY in normalized or COMPANY_FULL in normalized
    institution_ok = document.institution in normalized
    if not company_ok:
        raise RuntimeError(f"Company identity not found in {document.local_filename}")
    if not institution_ok:
        raise RuntimeError(f"Institution identity not found in {document.local_filename}")

    stem = f"{document.sequence:02d}"
    render_page(pdf_path, 0, VERIFY_DIR / f"{stem}_first.png")
    render_page(pdf_path, page_count - 1, VERIFY_DIR / f"{stem}_last.png")

    payload = pdf_path.read_bytes()
    document.pages = page_count
    document.bytes = len(payload)
    document.sha256 = sha256_bytes(payload)
    document.first_last_page_rendered = True
    document.identity_verified = True


def write_metadata(documents: Iterable[Document]) -> None:
    documents = list(documents)
    PACKAGE_ROOT.mkdir(parents=True, exist_ok=True)

    note = f"""美农生物（301156）券商研究与深度尽调资料包
整理日期：{AS_OF}

重要说明
========
经东方财富公开研报档案按证券代码301156、公司简称及完整时间区间检索，当前可直接取得并完成校验的公开公司研究报告只有1份，且全文为3页，不是传统20页以上的长篇卖方深度报告。

为避免将网页摘要、付费预览或不完整附件冒充完整券商研报，本包没有凑数。应用户希望取得2-3份券商材料的要求，另收录2份中泰证券官方保荐/持续督导材料。这两份资料对公司历史沿革、业务与技术、治理、IPO核查及上市后持续督导有较高研究价值，但性质上不是带评级与目标价的卖方研究报告。

文件构成
========
1. 2025-07-10 环球富盛理财：《深耕饲料添加剂和酶解蛋白饲料原料业务，重点突破海外市场》
   - 性质：公开公司研究报告
   - 作者：庄怀超
   - 页数：{documents[0].pages}页

2. 2022-06-06 中泰证券：《关于公司首次公开发行股票并在创业板上市之保荐工作报告》
   - 性质：IPO保荐工作/尽调材料，不是卖方评级研报
   - 页数：{documents[1].pages}页

3. 2026-05-13 中泰证券：《首次公开发行股票并在创业板上市持续督导保荐总结报告书》
   - 性质：持续督导保荐总结，不是卖方评级研报
   - 页数：{documents[2].pages}页

校验范围
========
- PDF文件头与结构解析
- 实际页数
- 美农生物/上海美农生物科技股份有限公司身份
- 研究或证券机构身份
- 首页与末页渲染
- 单文件SHA-256
- ZIP CRC完整性

资料仅供个人研究参考，不构成投资建议。报告和文件版权归相应机构、公司及作者所有。
"""
    (PACKAGE_ROOT / "00_重要说明与文件清单.txt").write_text(note, encoding="utf-8")

    csv_path = PACKAGE_ROOT / "文件清单.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "序号", "类别", "性质", "机构", "作者或责任人", "日期", "标题", "页数",
                "字节数", "SHA256", "来源页面", "PDF地址", "包内路径",
            ],
        )
        writer.writeheader()
        for d in documents:
            writer.writerow({
                "序号": d.sequence,
                "类别": d.category,
                "性质": d.nature,
                "机构": d.institution,
                "作者或责任人": d.analyst,
                "日期": d.publish_date,
                "标题": d.title,
                "页数": d.pages,
                "字节数": d.bytes,
                "SHA256": d.sha256,
                "来源页面": d.source_page,
                "PDF地址": d.pdf_url,
                "包内路径": d.relative_path,
            })

    manifest = {
        "company": COMPANY,
        "company_full_name": COMPANY_FULL,
        "stock_code": STOCK_CODE,
        "as_of": AS_OF,
        "package_scope": "1份公开公司研究报告 + 2份中泰证券官方保荐/持续督导深度材料",
        "important_caveat": (
            "仅第1份为公开公司研究报告；第2-3份为官方保荐/持续督导材料，"
            "不是带评级和目标价的卖方研报。"
        ),
        "documents": [asdict(d) for d in documents],
    }
    (PACKAGE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    checksum_lines = [f"{d.sha256}  {d.relative_path}" for d in documents]
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
        pdfs = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
        if len(pdfs) != 3:
            raise RuntimeError(f"Expected 3 PDFs in final ZIP, found {len(pdfs)}")


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    DUE_DILIGENCE_DIR.mkdir(parents=True, exist_ok=True)
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    for document in DOCUMENTS:
        local_path = PACKAGE_ROOT / document.relative_path
        print(f"Downloading {document.sequence}: {document.title}")
        download_pdf(session, document, local_path)
        print(f"Validating {local_path}")
        validate_pdf(document, local_path)
        print(
            json.dumps({
                "sequence": document.sequence,
                "pages": document.pages,
                "bytes": document.bytes,
                "sha256": document.sha256,
            }, ensure_ascii=False)
        )

    write_metadata(DOCUMENTS)
    build_zip()

    result = {
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256_bytes(ZIP_PATH.read_bytes()),
        "pdf_count": 3,
        "documents": [
            {
                "institution": d.institution,
                "date": d.publish_date,
                "title": d.title,
                "nature": d.nature,
                "pages": d.pages,
                "bytes": d.bytes,
            }
            for d in DOCUMENTS
        ],
    }
    (ROOT / "package_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("PACKAGE_SUMMARY", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
