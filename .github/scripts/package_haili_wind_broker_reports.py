from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

import pymupdf
import requests
from pypdf import PdfReader

ROOT = Path.cwd()
PACKAGE = ROOT / "haili_wind_broker_reports_verified"
REPORT_DIR = PACKAGE / "01_券商深度报告"
OUTPUT = ROOT / "海力风电_券商深度报告_3份_完整PDF.zip"

COMPANY = "江苏海力风电设备科技股份有限公司"
SHORT_NAME = "海力风电"
STOCK_CODE = "301155"
TICKER = "301155.SZ"
PREPARED_DATE = "2026-08-30"

REPORTS: list[dict[str, Any]] = [
    {
        "info_code": "AP202511031774257396",
        "broker": "国信证券",
        "publish_date": "2025-11-03",
        "researcher": "王蔚祺,王晓声",
        "title": "国内业务迎来拐点，出口业务突破可期",
        "expected_pages": 25,
        "title_markers": ["国内业务迎来拐点", "出口业务突破可期"],
    },
    {
        "info_code": "AP202501241642522008",
        "broker": "华安证券",
        "publish_date": "2025-01-24",
        "researcher": "张志邦",
        "title": "国内海风管桩领先企业，2025年有望量利齐升",
        "expected_pages": 23,
        "title_markers": ["国内海风管桩领先企业", "量利齐升"],
    },
    {
        "info_code": "AP202303241584529064",
        "broker": "东亚前海证券",
        "publish_date": "2023-03-24",
        "researcher": "燕楠",
        "title": "首次覆盖报告：海上能手，力乘东风",
        "expected_pages": 42,
        "title_markers": ["海上能手", "力乘东风"],
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
        "Referer": "https://data.eastmoney.com/report/",
    }
)


def compact(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def safe_filename(text: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:170]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def candidate_urls(info_code: str) -> list[str]:
    base = f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"
    return [
        base,
        f"{base}?{int(time.time() * 1000)}.pdf=",
        base.replace("https://", "http://", 1),
    ]


def download_pdf(record: dict[str, Any], target: Path) -> str:
    errors: list[str] = []
    for url in candidate_urls(record["info_code"]):
        for attempt in range(1, 4):
            part = target.with_suffix(target.suffix + ".part")
            part.unlink(missing_ok=True)
            try:
                with session.get(
                    url,
                    headers={
                        "Referer": (
                            "https://data.eastmoney.com/report/info/"
                            f"{record['info_code']}.html"
                        ),
                        "Accept": "application/pdf,*/*;q=0.8",
                    },
                    stream=True,
                    timeout=(30, 360),
                    allow_redirects=True,
                ) as response:
                    response.raise_for_status()
                    with part.open("wb") as handle:
                        for chunk in response.iter_content(1024 * 1024):
                            if chunk:
                                handle.write(chunk)
                if part.stat().st_size < 200_000:
                    raise RuntimeError(f"file too small: {part.stat().st_size}")
                with part.open("rb") as handle:
                    if handle.read(5) != b"%PDF-":
                        raise RuntimeError("response is not a PDF")
                part.replace(target)
                print(f"Downloaded {record['info_code']} -> {target}")
                return url
            except Exception as exc:
                part.unlink(missing_ok=True)
                errors.append(f"{url} attempt {attempt}: {exc}")
                time.sleep(attempt)
    raise RuntimeError(
        f"Unable to download {record['info_code']} {record['title']}: "
        + " | ".join(errors)
    )


def inspect_pdf(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    reader = PdfReader(str(path))
    if reader.is_encrypted and reader.decrypt("") == 0:
        raise RuntimeError(f"PDF cannot be decrypted: {path}")
    pages = len(reader.pages)
    if pages != int(record["expected_pages"]):
        raise RuntimeError(
            f"Page-count mismatch for {record['title']}: "
            f"{pages} != {record['expected_pages']}"
        )

    document = pymupdf.open(path)
    if document.page_count != pages:
        raise RuntimeError(f"Parser page-count mismatch: {path}")

    front_text = "\n".join(
        document.load_page(index).get_text("text")
        for index in range(min(12, pages))
    )
    front_compact = compact(front_text)

    if not any(
        compact(marker) in front_compact
        for marker in (SHORT_NAME, COMPANY, STOCK_CODE)
    ):
        raise RuntimeError(f"Company marker missing from front section: {path}")

    if not any(
        compact(marker) in front_compact
        for marker in (
            record["broker"],
            f"{record['broker']}研究所",
            "证券研究报告",
            "公司研究",
            "首次覆盖",
            "深度报告",
        )
    ):
        raise RuntimeError(f"Broker-research marker missing: {path}")

    for marker in record["title_markers"]:
        if compact(marker) not in front_compact:
            raise RuntimeError(f"Title marker {marker!r} missing: {path}")

    for page_index in sorted({0, pages // 2, pages - 1}):
        pixmap = document.load_page(page_index).get_pixmap(
            matrix=pymupdf.Matrix(0.55, 0.55), alpha=False
        )
        if pixmap.width < 150 or pixmap.height < 150:
            raise RuntimeError(
                f"Render check failed: {path}, page {page_index + 1}"
            )
    document.close()

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def main() -> None:
    if PACKAGE.exists():
        shutil.rmtree(PACKAGE)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.unlink(missing_ok=True)

    documents: list[dict[str, Any]] = []
    checksum_lines: list[str] = []

    for index, record in enumerate(REPORTS, 1):
        filename = safe_filename(
            f"{index:02d}_{record['broker']}_{record['publish_date'].replace('-', '')}_"
            f"{record['title']}.pdf"
        )
        target = REPORT_DIR / filename
        source_pdf = download_pdf(record, target)
        metadata = inspect_pdf(target, record)
        rel_path = str(target.relative_to(PACKAGE))
        item = {
            "company": SHORT_NAME,
            "stock_code": STOCK_CODE,
            "broker": record["broker"],
            "title": record["title"],
            "publish_date": record["publish_date"],
            "researcher": record["researcher"],
            "file": rel_path,
            **metadata,
            "source_page": (
                "https://data.eastmoney.com/report/info/"
                f"{record['info_code']}.html"
            ),
            "source_pdf": source_pdf,
            "info_code": record["info_code"],
        }
        documents.append(item)
        checksum_lines.append(f"{item['sha256']}  {rel_path}")

    if len(documents) != 3:
        raise RuntimeError(f"Expected 3 reports, found {len(documents)}")

    total_pages = sum(int(item["pages"]) for item in documents)
    total_bytes = sum(int(item["bytes"]) for item in documents)

    readme_lines = [
        f"{COMPANY}（{TICKER}，{SHORT_NAME}）券商深度研究报告",
        f"整理日期：{PREPARED_DATE}",
        "",
        "筛选口径",
        "1. 优先选择公开可下载且正文篇幅完整的公司深度或首次覆盖报告。",
        "2. 排除仅3—5页的季报、半年报及业绩点评，不以短报告凑数。",
        "3. 收录两份2025年报告及一份42页首次覆盖报告，来自三家不同券商。",
        "",
        "文件清单",
    ]
    for index, item in enumerate(documents, 1):
        readme_lines.extend(
            [
                f"{index}. {item['broker']}：{item['title']}",
                f"   发布日期：{item['publish_date']}",
                f"   研究员：{item['researcher']}",
                f"   页数：{item['pages']}",
                f"   文件：{item['file']}",
                f"   来源页面：{item['source_page']}",
                f"   SHA-256：{item['sha256']}",
                "",
            ]
        )

    readme_lines.extend(
        [
            "完整性检查",
            f"- 共3份PDF，合计{total_pages}页，未压缩总大小{total_bytes / 1024 / 1024:.2f} MiB。",
            "- 每份PDF均检查文件头、结构、页数、公司名称、券商标识和标题特征。",
            "- 已使用PyMuPDF渲染抽查每份PDF的首页、中间页和末页。",
            "- ZIP已通过CRC完整性测试；逐文件哈希见SHA256SUMS.txt。",
        ]
    )

    (PACKAGE / "README_来源与校验.txt").write_text(
        "\n".join(readme_lines), encoding="utf-8"
    )
    (PACKAGE / "SHA256SUMS.txt").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8"
    )
    (PACKAGE / "manifest.json").write_text(
        json.dumps(
            {
                "company": COMPANY,
                "short_name": SHORT_NAME,
                "stock_code": STOCK_CODE,
                "ticker": TICKER,
                "prepared_date": PREPARED_DATE,
                "selection_policy": "两份2025年完整深度报告加一份42页首次覆盖报告",
                "documents": documents,
                "total_pages": total_pages,
                "total_bytes": total_bytes,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    with zipfile.ZipFile(
        OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in sorted(PACKAGE.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(path.relative_to(PACKAGE)))

    with zipfile.ZipFile(OUTPUT, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")
        pdf_names = [
            name for name in archive.namelist() if name.lower().endswith(".pdf")
        ]
        if len(pdf_names) != 3:
            raise RuntimeError(f"Expected 3 PDFs, found {len(pdf_names)}")

    print("\n".join(readme_lines))
    print(f"ZIP_FILE={OUTPUT}")
    print(f"ZIP_BYTES={OUTPUT.stat().st_size}")
    print(f"ZIP_SHA256={sha256(OUTPUT)}")


if __name__ == "__main__":
    main()
