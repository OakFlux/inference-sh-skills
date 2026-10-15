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

COMPANY = "开立医疗"
COMPANY_FULL = "深圳开立生物医疗科技股份有限公司"
STOCK_CODE = "300633"
AS_OF = "2026-10-15"

ROOT = Path("dist_kaili_broker")
PACKAGE_ROOT = ROOT / f"{COMPANY}_{STOCK_CODE}_券商深度报告_3份"
REPORT_DIR = PACKAGE_ROOT / "01_券商深度报告"
VERIFY_DIR = ROOT / "_verification_renders"
ZIP_PATH = ROOT / f"{COMPANY}_{STOCK_CODE}_券商深度报告_3份_20261015.zip"
SUMMARY_PATH = ROOT / "package_summary.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


@dataclass
class Report:
    sequence: int
    institution: str
    analyst: str
    publish_date: str
    title: str
    rating: str
    info_code: str
    expected_pages: int
    local_filename: str
    detail_url: str
    pdf_url: str
    relative_path: str
    pages: int = 0
    bytes: int = 0
    sha256: str = ""
    company_identity_verified: bool = False
    institution_identity_verified: bool = False
    first_last_page_rendered: bool = False


REPORTS = [
    Report(
        sequence=1,
        institution="信达证券",
        analyst="唐爱金",
        publish_date="2026-04-22",
        title="公司深度报告：高端机型产品助盈利修复，新业务渐入收获期",
        rating="买入",
        info_code="AP202604221821459251",
        expected_pages=39,
        local_filename="01_20260422_信达证券_公司深度报告_高端机型产品助盈利修复_新业务渐入收获期.pdf",
        detail_url="https://data.eastmoney.com/report/info/AP202604221821459251.html",
        pdf_url="https://pdf.dfcfw.com/pdf/H3_AP202604221821459251_1.pdf",
        relative_path="01_券商深度报告/01_20260422_信达证券_公司深度报告_高端机型产品助盈利修复_新业务渐入收获期.pdf",
    ),
    Report(
        sequence=2,
        institution="国信证券",
        analyst="张佳博",
        publish_date="2024-07-18",
        title="超声和软镜行业领军者，多产线布局厚积薄发",
        rating="增持",
        info_code="AP202407181638027095",
        expected_pages=52,
        local_filename="02_20240718_国信证券_超声和软镜行业领军者_多产线布局厚积薄发.pdf",
        detail_url="https://data.eastmoney.com/report/info/AP202407181638027095.html",
        pdf_url="https://pdf.dfcfw.com/pdf/H3_AP202407181638027095_1.pdf",
        relative_path="01_券商深度报告/02_20240718_国信证券_超声和软镜行业领军者_多产线布局厚积薄发.pdf",
    ),
    Report(
        sequence=3,
        institution="开源证券",
        analyst="蔡明子、司乐致",
        publish_date="2022-04-19",
        title="公司首次覆盖报告：产品创新迭代突围高端市场，超声+内镜双翼驱动加快业绩腾飞",
        rating="买入",
        info_code="AP202204191560293623",
        expected_pages=50,
        local_filename="03_20220419_开源证券_首次覆盖_产品创新迭代突围高端市场_超声内镜双翼驱动.pdf",
        detail_url="https://data.eastmoney.com/report/info/AP202204191560293623.html",
        pdf_url="https://pdf.dfcfw.com/pdf/H3_AP202204191560293623_1.pdf",
        relative_path="01_券商深度报告/03_20220419_开源证券_首次覆盖_产品创新迭代突围高端市场_超声内镜双翼驱动.pdf",
    ),
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download_pdf(session: requests.Session, report: Report, target: Path) -> None:
    timestamp_variants = [
        report.pdf_url,
        report.pdf_url + "?1.pdf=",
        report.pdf_url + "?1700000000000.pdf=",
        report.pdf_url.replace("https://", "http://"),
    ]
    last_error: Exception | None = None
    for url in timestamp_variants:
        for attempt in range(1, 5):
            try:
                headers = dict(HEADERS)
                headers["Referer"] = report.detail_url
                response = session.get(url, headers=headers, timeout=120, allow_redirects=True)
                response.raise_for_status()
                payload = response.content
                if not payload.startswith(b"%PDF"):
                    raise RuntimeError(
                        f"Non-PDF response: status={response.status_code}, "
                        f"content-type={response.headers.get('content-type')}, bytes={len(payload)}"
                    )
                if len(payload) < 100_000:
                    raise RuntimeError(f"Suspiciously small PDF: {len(payload)} bytes")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                report.pdf_url = response.url
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < 4:
                    time.sleep(attempt * 1.2)
    raise RuntimeError(f"Unable to download {report.title}: {last_error}")


def collect_text(reader: PdfReader, page_limit: int = 15) -> str:
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
        pix = page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6), alpha=False)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(output_path)
    if output_path.stat().st_size < 8_000:
        raise RuntimeError(f"Rendered page image is unexpectedly small: {output_path}")


def validate_report(report: Report, pdf_path: Path) -> None:
    reader = PdfReader(str(pdf_path), strict=False)
    pages = len(reader.pages)
    if pages != report.expected_pages:
        raise RuntimeError(
            f"Page-count mismatch for {report.title}: expected {report.expected_pages}, got {pages}"
        )

    text = collect_text(reader)
    normalized = "".join(text.split())
    company_ok = COMPANY in normalized or COMPANY_FULL in normalized or STOCK_CODE in normalized
    institution_ok = report.institution in normalized
    if not company_ok:
        raise RuntimeError(f"Company identity not found in {report.local_filename}")
    if not institution_ok:
        raise RuntimeError(f"Institution identity not found in {report.local_filename}")

    render_page(pdf_path, 0, VERIFY_DIR / f"{report.sequence:02d}_first.png")
    render_page(pdf_path, pages - 1, VERIFY_DIR / f"{report.sequence:02d}_last.png")

    payload = pdf_path.read_bytes()
    report.pages = pages
    report.bytes = len(payload)
    report.sha256 = sha256_bytes(payload)
    report.company_identity_verified = True
    report.institution_identity_verified = True
    report.first_last_page_rendered = True


def write_metadata(reports: Iterable[Report]) -> None:
    reports = list(reports)
    PACKAGE_ROOT.mkdir(parents=True, exist_ok=True)

    note_lines = [
        f"{COMPANY}（{STOCK_CODE}）券商深度报告资料包",
        f"整理日期：{AS_OF}",
        "",
        "收录范围",
        "========",
        "本包精选3份公开可取得的完整券商长篇公司研究报告，优先考虑最新深度覆盖、篇幅、机构差异和历史首次覆盖价值。",
        "",
    ]
    for report in reports:
        note_lines.extend([
            f"{report.sequence}. {report.publish_date} {report.institution}：《{report.title}》",
            f"   分析师：{report.analyst}",
            f"   评级：{report.rating}",
            f"   实际页数：{report.pages}页",
            f"   来源页面：{report.detail_url}",
            "",
        ])
    note_lines.extend([
        "校验范围",
        "========",
        "- PDF文件头与结构解析",
        "- 实际页数",
        "- 开立医疗/证券代码300633身份",
        "- 券商机构身份",
        "- 首页与末页渲染",
        "- 单文件SHA-256",
        "- ZIP CRC完整性",
        "",
        "资料仅供个人研究参考，不构成投资建议。报告版权归相应证券研究机构及作者所有。",
    ])
    (PACKAGE_ROOT / "00_文件清单与来源说明.txt").write_text(
        "\n".join(note_lines) + "\n", encoding="utf-8"
    )

    with (PACKAGE_ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "序号", "机构", "分析师", "发布日期", "标题", "评级", "页数", "字节数",
                "SHA256", "研报详情页", "PDF来源", "包内路径",
            ],
        )
        writer.writeheader()
        for report in reports:
            writer.writerow({
                "序号": report.sequence,
                "机构": report.institution,
                "分析师": report.analyst,
                "发布日期": report.publish_date,
                "标题": report.title,
                "评级": report.rating,
                "页数": report.pages,
                "字节数": report.bytes,
                "SHA256": report.sha256,
                "研报详情页": report.detail_url,
                "PDF来源": report.pdf_url,
                "包内路径": report.relative_path,
            })

    manifest = {
        "company": COMPANY,
        "company_full_name": COMPANY_FULL,
        "stock_code": STOCK_CODE,
        "as_of": AS_OF,
        "selection_method": "按最新深度覆盖、篇幅、机构差异及首次覆盖研究价值精选3份",
        "documents": [asdict(report) for report in reports],
    }
    (PACKAGE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    checksum_lines = [f"{report.sha256}  {report.relative_path}" for report in reports]
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
        pdf_count = len([name for name in archive.namelist() if name.lower().endswith(".pdf")])
        if pdf_count != len(REPORTS):
            raise RuntimeError(f"Expected {len(REPORTS)} PDFs in ZIP, got {pdf_count}")


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    for report in REPORTS:
        target = PACKAGE_ROOT / report.relative_path
        print(f"Downloading {report.sequence}: {report.institution} - {report.title}")
        download_pdf(session, report, target)
        print(f"Validating {target}")
        validate_report(report, target)

    write_metadata(REPORTS)
    build_zip()

    zip_payload = ZIP_PATH.read_bytes()
    summary = {
        "zip": str(ZIP_PATH),
        "zip_bytes": len(zip_payload),
        "zip_sha256": sha256_bytes(zip_payload),
        "pdf_count": len(REPORTS),
        "documents": [
            {
                "institution": report.institution,
                "date": report.publish_date,
                "title": report.title,
                "analyst": report.analyst,
                "rating": report.rating,
                "pages": report.pages,
                "bytes": report.bytes,
                "sha256": report.sha256,
            }
            for report in REPORTS
        ],
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
