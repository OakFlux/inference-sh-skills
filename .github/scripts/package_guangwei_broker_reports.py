from __future__ import annotations

import hashlib
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Any

import pymupdf as fitz
import requests
from pypdf import PdfReader

ROOT = Path.cwd()
PACKAGE = ROOT / "guangwei_broker_reports_verified"
REPORT_DIR = PACKAGE / "01_券商深度报告"
OUTPUT = ROOT / "光威复材_券商深度报告_3份_完整PDF.zip"

STOCK_CODE = "300699"
TICKER = "300699.SZ"
COMPANY = "威海光威复合材料股份有限公司"
SHORT_NAME = "光威复材"
PREPARED_DATE = "2026-08-30"

REPORTS: list[dict[str, Any]] = [
    {
        "info_code": "AP202407141637886293",
        "broker": "西南证券",
        "publish_date": "2024-07-14",
        "researcher": "刘倩倩",
        "title": "高性能碳纤维龙头，需求+产能共同驱动长期成长",
        "expected_pages": 47,
        "title_markers": ["高性能碳纤维龙头", "长期成长"],
    },
    {
        "info_code": "AP202203291555754328",
        "broker": "英大证券",
        "publish_date": "2022-03-29",
        "researcher": "刘杰",
        "title": "公司深度报告：双轮驱动：民品降本上量，军品次第接力",
        "expected_pages": 30,
        "title_markers": ["双轮驱动", "民品降本上量", "军品次第接力"],
    },
    {
        "info_code": "AP202112171535089188",
        "broker": "申港证券",
        "publish_date": "2021-12-17",
        "researcher": "曹旭特",
        "title": "风电与军工双轮驱动，碳纤维龙头行稳致远",
        "expected_pages": 26,
        "title_markers": ["风电与军工双轮驱动", "碳纤维龙头行稳致远"],
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


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def safe_filename(text: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:180]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pdf_urls(info_code: str) -> list[str]:
    base = f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"
    return [
        base,
        f"{base}?{int(time.time() * 1000)}.pdf=",
        base.replace("https://", "http://", 1),
    ]


def download_pdf(record: dict[str, Any], target: Path) -> str:
    errors: list[str] = []
    for url in pdf_urls(record["info_code"]):
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
                    timeout=(30, 300),
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
        raise RuntimeError(f"Encrypted PDF cannot be opened: {path}")
    pages = len(reader.pages)
    if pages != int(record["expected_pages"]):
        raise RuntimeError(
            f"Page-count mismatch for {record['title']}: "
            f"{pages} != {record['expected_pages']}"
        )

    document = fitz.open(path)
    if document.page_count != pages:
        raise RuntimeError(f"Page-count mismatch between parsers: {path}")

    front_text = "\n".join(
        document.load_page(index).get_text("text")
        for index in range(min(12, pages))
    )
    front_compact = normalize(front_text)

    if not any(
        normalize(marker) in front_compact
        for marker in (SHORT_NAME, COMPANY, STOCK_CODE)
    ):
        raise RuntimeError(f"Company marker missing from report front: {path}")

    if not any(
        normalize(marker) in front_compact
        for marker in (
            record["broker"],
            f"{record['broker']}研究所",
            "证券研究报告",
            "公司研究",
            "公司深度报告",
            "深度报告",
        )
    ):
        raise RuntimeError(f"Broker-research marker missing from report front: {path}")

    missing_title_markers = [
        marker
        for marker in record["title_markers"]
        if normalize(marker) not in front_compact
    ]
    if missing_title_markers:
        raise RuntimeError(
            f"Title markers missing from report front: {path}: {missing_title_markers}"
        )

    for index in sorted({0, pages // 2, pages - 1}):
        pixmap = document.load_page(index).get_pixmap(
            matrix=fitz.Matrix(0.55, 0.55), alpha=False
        )
        if pixmap.width < 150 or pixmap.height < 150:
            raise RuntimeError(f"Render check failed: {path}, page {index + 1}")
    document.close()

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def main() -> None:
    if PACKAGE.exists():
        import shutil
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
            "pages": metadata["pages"],
            "bytes": metadata["bytes"],
            "sha256": metadata["sha256"],
            "source_page": (
                f"https://data.eastmoney.com/report/info/{record['info_code']}.html"
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
        "1. 优先选择公开可下载、篇幅完整的公司深度报告，排除仅数页的业绩点评。",
        "2. 本包收录2024年、2022年和2021年三份系统性研究，覆盖近期竞争格局及历史产业逻辑。",
        "3. 三份报告来自不同券商，便于比较业务假设、产能判断和盈利预测。",
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
            "- 已渲染抽查每份PDF的首页、中间页和末页。",
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
                "selection_policy": "公开可下载、篇幅完整、不同券商的公司深度报告",
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
        pdfs = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
        if len(pdfs) != 3:
            raise RuntimeError(f"Expected 3 PDFs, found {len(pdfs)}")

    print("\n".join(readme_lines))
    print(f"ZIP_FILE={OUTPUT}")
    print(f"ZIP_BYTES={OUTPUT.stat().st_size}")
    print(f"ZIP_SHA256={sha256(OUTPUT)}")


if __name__ == "__main__":
    main()
