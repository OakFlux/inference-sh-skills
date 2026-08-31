from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import requests
from pypdf import PdfReader

ROOT = Path.cwd()
PACKAGE = ROOT / "kwih_verified_package"
ANNUAL_DIR = PACKAGE / "01_年度报告_2020-2025"
INTERIM_DIR = PACKAGE / "02_最新完整中期报告"
RENDER_DIR = ROOT / "kwih_render_checks"
for directory in (ANNUAL_DIR, INTERIM_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

COMPANY = "嘉华国际集团有限公司"
EN_COMPANY = "K. Wah International Holdings Limited"
STOCK_CODE = "00173"
TICKER = "00173.HK"
PREPARED_DATE = "2026-08-31"
LATEST_FULL_INTERIM_YEAR = 2025
LATEST_FULL_INTERIM_PUBLISHED_DATE = "2025-09-23"
LATEST_INTERIM_RESULTS_DATE = "2026-08-27"

REPORTS = [
    {
        "category": "Annual Report",
        "year": 2020,
        "title": "嘉华国际2020年年度报告",
        "url": "https://www.kwih.com/uploads/IR/Financial%20Reports/TC_SC/c_00173_2020_ar.pdf",
        "target": ANNUAL_DIR / "嘉华国际_2020年年度报告.pdf",
    },
    {
        "category": "Annual Report",
        "year": 2021,
        "title": "嘉华国际2021年年度报告",
        "url": "https://www.kwih.com/uploads/IR/Financial%20Reports/TC_SC/c_00173_2021_ar.pdf",
        "target": ANNUAL_DIR / "嘉华国际_2021年年度报告.pdf",
    },
    {
        "category": "Annual Report",
        "year": 2022,
        "title": "嘉华国际2022年年度报告",
        "url": "https://www.kwih.com/uploads/IR/Financial%20Reports/TC_SC/c_00173_2022_ar.pdf",
        "target": ANNUAL_DIR / "嘉华国际_2022年年度报告.pdf",
    },
    {
        "category": "Annual Report",
        "year": 2023,
        "title": "嘉华国际2023年年度报告",
        "url": "https://www.kwih.com/uploads/IR/Financial%20Reports/c_00173_2023AR.pdf",
        "target": ANNUAL_DIR / "嘉华国际_2023年年度报告.pdf",
    },
    {
        "category": "Annual Report",
        "year": 2024,
        "title": "嘉华国际2024年年度报告",
        "url": "https://www.kwih.com/uploads/IR/Financial%20Reports/c_00173_2024AR.pdf",
        "target": ANNUAL_DIR / "嘉华国际_2024年年度报告.pdf",
    },
    {
        "category": "Annual Report",
        "year": 2025,
        "title": "嘉华国际2025年年度报告",
        "url": "https://www.kwih.com/uploads/IR/Financial%20Reports/c_00173_2025AR.pdf",
        "target": ANNUAL_DIR / "嘉华国际_2025年年度报告.pdf",
    },
    {
        "category": "Latest Full Interim Report",
        "year": 2025,
        "title": "嘉华国际2025年中期报告",
        "url": "https://www.kwih.com/uploads/IR/Financial%20Reports/c_173_2025IR.pdf",
        "target": INTERIM_DIR / "嘉华国际_2025年中期报告_截至目前最新完整中报.pdf",
    },
]

session = requests.Session()
session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def chinese_year(year: int) -> str:
    digits = {"0": "零", "1": "一", "2": "二", "3": "三", "4": "四", "5": "五", "6": "六", "7": "七", "8": "八", "9": "九"}
    return "".join(digits[ch] for ch in str(year))


def download_pdf(url: str, target: Path) -> None:
    errors: list[str] = []
    for attempt in range(1, 5):
        part = target.with_suffix(target.suffix + ".part")
        part.unlink(missing_ok=True)
        try:
            with session.get(
                url,
                stream=True,
                timeout=(30, 600),
                allow_redirects=True,
                headers={"Referer": "https://www.kwih.com/sc/investor-relations/financial-reports"},
            ) as response:
                response.raise_for_status()
                with part.open("wb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            if part.stat().st_size < 400_000:
                raise RuntimeError(f"file too small: {part.stat().st_size}")
            with part.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise RuntimeError("response is not a PDF")
            part.replace(target)
            print(f"Downloaded {url} -> {target} ({target.stat().st_size} bytes)")
            return
        except Exception as exc:
            part.unlink(missing_ok=True)
            errors.append(f"attempt {attempt}: {exc}")
            time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to download {url}: {' | '.join(errors)}")


def inspect_pdf(item: dict[str, Any], index: int) -> dict[str, Any]:
    path = Path(item["target"])
    reader = PdfReader(str(path))
    encrypted = reader.is_encrypted
    if encrypted and reader.decrypt("") == 0:
        raise RuntimeError(f"Cannot decrypt PDF: {path}")
    pages = len(reader.pages)

    minimum_pages = 100 if item["category"] == "Annual Report" else 25
    if pages < minimum_pages:
        raise RuntimeError(f"Unexpectedly short report: {path}, {pages} pages")

    document = fitz.open(path)
    if document.page_count != pages:
        raise RuntimeError(f"Page-count mismatch: {path}")

    front_text = "\n".join(
        document.load_page(page_index).get_text("text")
        for page_index in range(min(30, pages))
    )
    front_compact = compact(front_text)

    company_markers = (
        "嘉華國際",
        "嘉华国际",
        compact(EN_COMPANY),
        STOCK_CODE,
    )
    if not any(compact(marker) in front_compact for marker in company_markers):
        raise RuntimeError(f"Company marker missing: {path}")

    year = int(item["year"])
    year_markers = (str(year), chinese_year(year), chinese_year(year).replace("零", "○"))
    if not any(compact(marker) in front_compact for marker in year_markers):
        raise RuntimeError(f"Year marker {year} missing: {path}")

    if item["category"] == "Annual Report":
        type_markers = ("年報", "年报", "annualreport")
    else:
        type_markers = ("中期報告", "中期报告", "interimreport")
    if not any(compact(marker) in front_compact for marker in type_markers):
        raise RuntimeError(f"Document type marker missing: {path}")

    for page_index in sorted({0, pages // 2, pages - 1}):
        pixmap = document.load_page(page_index).get_pixmap(
            matrix=fitz.Matrix(0.55, 0.55), alpha=False
        )
        if pixmap.width < 150 or pixmap.height < 150:
            raise RuntimeError(f"PyMuPDF render failed: {path}, page {page_index + 1}")
    document.close()

    output_prefix = RENDER_DIR / f"report_{index:02d}"
    result = subprocess.run(
        [
            "pdftoppm",
            "-f", "1",
            "-l", "1",
            "-singlefile",
            "-png",
            "-r", "90",
            str(path),
            str(output_prefix),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    rendered_png = output_prefix.with_suffix(".png")
    if result.returncode != 0 or not rendered_png.exists() or rendered_png.stat().st_size < 5_000:
        raise RuntimeError(f"Poppler render failed: {path}; {result.stderr[-500:]}")

    return {
        "category": item["category"],
        "year": year,
        "title": item["title"],
        "file": str(path.relative_to(PACKAGE)),
        "source": item["url"],
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "encrypted": bool(encrypted),
    }


# Verify the official financial-report page still identifies 2025 as the latest complete interim report.
financial_page = session.get(
    "https://www.kwih.com/sc/investor-relations/financial-reports",
    timeout=(30, 180),
)
financial_page.raise_for_status()
page_text = financial_page.text
if "二零二五年中期报告" not in page_text and "2025 中期报告" not in page_text:
    raise RuntimeError("Official financial-report page does not list the 2025 interim report")
if "二零二六年中期报告" in page_text or "2026 中期报告" in page_text:
    raise RuntimeError("A 2026 full interim report is now listed; update the package")

for report in REPORTS:
    download_pdf(str(report["url"]), Path(report["target"]))

documents = [inspect_pdf(report, index) for index, report in enumerate(REPORTS, 1)]

annual_years = sorted(
    item["year"] for item in documents if item["category"] == "Annual Report"
)
if annual_years != list(range(2020, 2026)):
    raise RuntimeError(f"Annual report coverage mismatch: {annual_years}")

interim_items = [
    item for item in documents if item["category"] == "Latest Full Interim Report"
]
if len(interim_items) != 1 or interim_items[0]["year"] != LATEST_FULL_INTERIM_YEAR:
    raise RuntimeError(f"Interim report coverage mismatch: {interim_items}")

# Guard against accidental duplicates.
hashes = [item["sha256"] for item in documents]
if len(hashes) != len(set(hashes)):
    raise RuntimeError("Duplicate PDF content detected")

total_pages = sum(int(item["pages"]) for item in documents)
total_bytes = sum(int(item["bytes"]) for item in documents)

readme_lines = [
    f"{COMPANY}（{TICKER}，嘉华国际）",
    "2020—2025年年度报告及截至目前最新完整中期报告",
    f"整理日期：{PREPARED_DATE}",
    "",
    "文件口径",
    "1. 收录2020—2025年共6份完整年度报告，均为公司官网发布的PDF正文。",
    "2. 截至2026年8月31日，公司已于2026年8月27日公布2026年中期业绩，",
    "   但官网财务报告栏目尚未发布完整《2026年中期报告》。",
    "3. 因此，本包所收录的最新完整中期报告为《嘉华国际2025年中期报告》。",
    "4. 不以2026年中期业绩公告替代完整中期报告；待完整报告正式发布后才应更新。",
    "",
    "文件清单",
]

checksum_lines: list[str] = []
for index, item in enumerate(documents, 1):
    period = (
        f"截至{item['year']}年12月31日止年度"
        if item["category"] == "Annual Report"
        else "截至2025年6月30日止六个月"
    )
    readme_lines.extend(
        [
            f"{index}. {item['title']}",
            f"   报告期：{period}",
            f"   文件：{item['file']}",
            f"   页数：{item['pages']}",
            f"   大小：{item['bytes']} bytes",
            f"   SHA-256：{item['sha256']}",
            f"   来源：{item['source']}",
            "",
        ]
    )
    checksum_lines.append(f"{item['sha256']}  {item['file']}")

readme_lines.extend(
    [
        "完整性检查",
        f"- 共{len(documents)}份PDF，合计{total_pages}页，未压缩总大小{total_bytes / 1024 / 1024:.2f} MiB。",
        "- 每份PDF均检查文件头、结构、页数、公司名称、报告年份及文档类型。",
        "- 每份PDF均使用PyMuPDF渲染首页、中间页和末页，并使用Poppler再次渲染首页。",
        "- ZIP已通过CRC完整性测试；逐文件SHA-256见SHA256SUMS.txt。",
    ]
)

(PACKAGE / "README_来源与校验.txt").write_text("\n".join(readme_lines), encoding="utf-8")
(PACKAGE / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
(PACKAGE / "manifest.json").write_text(
    json.dumps(
        {
            "company": COMPANY,
            "english_company": EN_COMPANY,
            "ticker": TICKER,
            "stock_code": STOCK_CODE,
            "prepared_date": PREPARED_DATE,
            "annual_report_years": annual_years,
            "latest_full_interim_report_year": LATEST_FULL_INTERIM_YEAR,
            "latest_full_interim_report_published_date": LATEST_FULL_INTERIM_PUBLISHED_DATE,
            "latest_interim_results_announcement_date": LATEST_INTERIM_RESULTS_DATE,
            "latest_full_interim_note": (
                "截至2026-08-31，2026年中期业绩已公布，但完整2026年中期报告尚未在公司官网财务报告栏目发布；"
                "因此最新完整中期报告为2025年中期报告。"
            ),
            "documents": documents,
            "total_pages": total_pages,
            "total_bytes": total_bytes,
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)

output = ROOT / "嘉华国际_2020-2025年报及2025年最新完整中期报告_完整PDF.zip"
with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(PACKAGE.rglob("*")):
        if path.is_file():
            archive.write(path, arcname=str(path.relative_to(PACKAGE)))

with zipfile.ZipFile(output, "r") as archive:
    bad = archive.testzip()
    if bad:
        raise RuntimeError(f"ZIP CRC failure: {bad}")
    pdfs = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
    if len(pdfs) != 7:
        raise RuntimeError(f"Expected 7 PDFs, found {len(pdfs)}")

print("\n".join(readme_lines))
print(f"ZIP_FILE={output}")
print(f"ZIP_BYTES={output.stat().st_size}")
print(f"ZIP_SHA256={sha256(output)}")
