from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from pypdf import PdfReader

COMPANY_CN = "中国化学"
COMPANY_EN = "China National Chemical Engineering Co., Ltd."
STOCK_CODE = "601117.SH"
PACKAGE_STEM = "中国化学_601117_2020-2025年报及最新财务报告"
ROOT = Path(PACKAGE_STEM)
ANNUAL_DIR = ROOT / "01_年度报告"
LATEST_DIR = ROOT / "02_最新财务报告"
NOTES_DIR = ROOT / "03_资料说明"
PREVIEW_DIR = Path("_previews_china_chemical_filings")
RESULT_JSON = Path("china_chemical_filings_result.json")
ZIP_PATH = Path("中国化学_601117_2020-2025年报及2026年最新财务报告.zip")

DOCUMENTS: list[dict[str, Any]] = [
    {
        "filename": "01_年度报告/中国化学_2020年年度报告.pdf",
        "document_type": "年度报告",
        "fiscal_period": "2020",
        "release_date": "2021-04-29",
        "url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2021-04-29/601117_20210429_11.pdf",
        "expected_year": 2020,
        "minimum_pages": 80,
        "preview_name": "annual_2020_first",
    },
    {
        "filename": "01_年度报告/中国化学_2021年年度报告.pdf",
        "document_type": "年度报告",
        "fiscal_period": "2021",
        "release_date": "2022-04-28",
        "url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2022-04-28/601117_20220428_2_ay38JzKR.pdf",
        "expected_year": 2021,
        "minimum_pages": 80,
        "preview_name": "annual_2021_first",
    },
    {
        "filename": "01_年度报告/中国化学_2022年年度报告.pdf",
        "document_type": "年度报告",
        "fiscal_period": "2022",
        "release_date": "2023-03-28",
        "url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2023-03-28/601117_20230328_HU01.pdf",
        "expected_year": 2022,
        "minimum_pages": 80,
        "preview_name": "annual_2022_first",
    },
    {
        "filename": "01_年度报告/中国化学_2023年年度报告.pdf",
        "document_type": "年度报告",
        "fiscal_period": "2023",
        "release_date": "2024-04-29",
        "url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2024-04-29/601117_20240429_DE4Z.pdf",
        "expected_year": 2023,
        "minimum_pages": 80,
        "preview_name": "annual_2023_first",
    },
    {
        "filename": "01_年度报告/中国化学_2024年年度报告.pdf",
        "document_type": "年度报告",
        "fiscal_period": "2024",
        "release_date": "2025-04-30",
        "url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-04-30/601117_20250430_PYFX.pdf",
        "expected_year": 2024,
        "minimum_pages": 80,
        "preview_name": "annual_2024_first",
    },
    {
        "filename": "01_年度报告/中国化学_2025年年度报告.pdf",
        "document_type": "年度报告",
        "fiscal_period": "2025",
        "release_date": "2026-03-25",
        "url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-03-25/601117_20260325_POJ5.pdf",
        "expected_year": 2025,
        "minimum_pages": 80,
        "preview_name": "annual_2025_first",
    },
    {
        "filename": "02_最新财务报告/中国化学_2026年第一季度报告.pdf",
        "document_type": "第一季度报告",
        "fiscal_period": "截至2026年3月31日止三个月",
        "release_date": "2026-04-28",
        "url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-04-28/601117_20260428_Z4MB.pdf",
        "expected_year": 2026,
        "minimum_pages": 8,
        "preview_name": "quarter_2026_q1_first",
    },
    {
        "filename": "02_最新财务报告/中国化学_2026年半年度报告.pdf",
        "document_type": "半年度报告",
        "fiscal_period": "截至2026年6月30日止六个月",
        "release_date": "2026-08-31",
        "url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-08-31/601117_20260831_CG6A.pdf",
        "expected_year": 2026,
        "minimum_pages": 50,
        "preview_name": "interim_2026_first",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Referer": "https://www.sse.com.cn/",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_text(value: str) -> str:
    return "".join(ch for ch in (value or "").upper() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def download_pdf(client: httpx.Client, url: str, destination: Path) -> None:
    last_error: Exception | None = None
    destination.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, 6):
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            if temporary.exists():
                temporary.unlink()
            with client.stream(
                "GET",
                url,
                timeout=httpx.Timeout(240.0, connect=60.0),
                headers=HEADERS,
            ) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            size = temporary.stat().st_size
            if size < 80_000:
                raise RuntimeError(f"Downloaded file is too small: {size} bytes")
            with temporary.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise RuntimeError("Downloaded content is not a PDF")
            temporary.replace(destination)
            print("DOWNLOADED", destination, size, url, flush=True)
            return
        except Exception as exc:
            last_error = exc
            print("DOWNLOAD_RETRY", attempt, url, repr(exc), flush=True)
            time.sleep(attempt * 4)
    raise RuntimeError(f"Failed to download {url}: {last_error!r}")


def extract_text(path: Path, max_pages: int = 8) -> str:
    pieces: list[str] = []
    try:
        reader = PdfReader(str(path), strict=False)
        for page in reader.pages[: min(max_pages, len(reader.pages))]:
            try:
                pieces.append(page.extract_text() or "")
            except Exception:
                continue
    except Exception:
        return ""
    return "\n".join(pieces)


def render_first_page(path: Path, preview_stem: str) -> Path:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    output_stem = PREVIEW_DIR / preview_stem
    subprocess.run(
        ["pdftoppm", "-f", "1", "-singlefile", "-png", "-r", "120", str(path), str(output_stem)],
        check=True,
        timeout=240,
        capture_output=True,
        text=True,
    )
    preview = output_stem.with_suffix(".png")
    if not preview.exists() or preview.stat().st_size < 8_000:
        raise RuntimeError(f"First-page rendering failed for {path}")
    return preview


def validate_document(path: Path, doc: dict[str, Any]) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size < 80_000:
        raise RuntimeError(f"Missing or undersized PDF: {path}")
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise RuntimeError(f"Invalid PDF header: {path}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < int(doc["minimum_pages"]):
        raise RuntimeError(f"Unexpected page count for {path}: {pages}")

    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf validation failed for {path}: {qpdf.stderr[-1500:]}")

    text = normalize_text(extract_text(path))
    if text:
        company_ok = any(
            normalize_text(marker) in text
            for marker in [COMPANY_CN, "中国化学工程股份有限公司", COMPANY_EN, "CHINANATIONALCHEMICALENGINEERING"]
        )
        year_ok = str(doc["expected_year"]) in text
        if not company_ok:
            raise RuntimeError(f"Company marker not found in {path}")
        if not year_ok:
            raise RuntimeError(f"Expected year {doc['expected_year']} not found in {path}")

    preview = render_first_page(path, str(doc["preview_name"]))
    record = {
        "filename": str(path.relative_to(ROOT)),
        "company": COMPANY_EN,
        "company_chinese": COMPANY_CN,
        "stock_code": STOCK_CODE,
        "document_type": doc["document_type"],
        "fiscal_period": doc["fiscal_period"],
        "release_date": doc["release_date"],
        "official_source_url": doc["url"],
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "first_page_preview": str(preview),
    }
    print("VERIFIED", json.dumps(record, ensure_ascii=False), flush=True)
    return record


def write_notes(records: list[dict[str, Any]]) -> None:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).isoformat()
    manifest = {
        "package": PACKAGE_STEM,
        "company": COMPANY_EN,
        "company_chinese": COMPANY_CN,
        "stock_code": STOCK_CODE,
        "source": "上海证券交易所公告PDF（static.sse.com.cn）",
        "generated_at_utc": generated,
        "annual_report_years": list(range(2020, 2026)),
        "latest_quarterly_report": "2026年第一季度报告",
        "latest_periodic_financial_report": "2026年半年度报告",
        "file_count": len(records),
        "records": records,
    }
    (NOTES_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    checksum_lines = [f"{item['sha256']}  {item['filename']}" for item in records]
    (NOTES_DIR / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    lines = [
        f"公司：{COMPANY_CN}（{COMPANY_EN}）",
        f"证券代码：{STOCK_CODE}",
        "来源：上海证券交易所公告PDF",
        "",
        "说明：",
        "1. 年度报告收录2020—2025年度完整报告。",
        "2. 截至2026年9月27日，2026年第三季度报告尚未披露；因此同时收录2026年第一季度报告（最新正式季报）与2026年半年度报告（最新一期定期财务报告）。",
        "3. 每份PDF均完成文件头、页数、qpdf结构及首页面渲染检查。",
        "",
        "文件清单：",
    ]
    for item in records:
        lines.append(
            f"- {item['filename']} | {item['pages']}页 | 发布日 {item['release_date']} | "
            f"SHA-256 {item['sha256']} | {item['official_source_url']}"
        )
    (NOTES_DIR / "资料清单与来源说明.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def package_zip() -> dict[str, Any]:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file_path in sorted(ROOT.rglob("*")):
            if file_path.is_file():
                archive.write(file_path, file_path.as_posix())
    return {
        "zip_filename": ZIP_PATH.name,
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256(ZIP_PATH),
    }


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    if PREVIEW_DIR.exists():
        shutil.rmtree(PREVIEW_DIR)
    for folder in (ANNUAL_DIR, LATEST_DIR, NOTES_DIR, PREVIEW_DIR):
        folder.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    with httpx.Client(http2=True, follow_redirects=True, headers=HEADERS) as client:
        for doc in DOCUMENTS:
            destination = ROOT / str(doc["filename"])
            download_pdf(client, str(doc["url"]), destination)
            records.append(validate_document(destination, doc))

    write_notes(records)
    zip_info = package_zip()
    result = {
        **zip_info,
        "pdf_count": len(records),
        "annual_report_years": list(range(2020, 2026)),
        "latest_quarterly_report": "2026年第一季度报告",
        "latest_periodic_financial_report": "2026年半年度报告",
        "records": records,
    }
    RESULT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("FINAL_RESULT", json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
