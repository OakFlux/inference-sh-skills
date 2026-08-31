from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import shutil
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import img2pdf
import pymupdf
import requests
from bs4 import BeautifulSoup
from PIL import Image
from pypdf import PdfReader

ROOT = Path.cwd()
PACKAGE = ROOT / "shenzhen_international_broker_reports_verified"
REPORT_DIR = PACKAGE / "01_券商公司研究报告"
IMAGE_ROOT = ROOT / "_shenzhen_international_report_images"
OUTPUT = ROOT / "深圳国际_券商深度报告_3份_完整PDF.zip"

COMPANY = "深圳国际控股有限公司"
SHORT_NAME = "深圳国际"
STOCK_CODE = "00152"
TICKER = "00152.HK"
PREPARED_DATE = "2026-08-31"

# 这三份报告均有无需登录即可访问的完整逐页公开阅读页面。
REPORTS: list[dict[str, Any]] = [
    {
        "report_id": 4788440,
        "image_date": "2025/04/17",
        "broker": "西南证券",
        "publish_date": "2025-04-17",
        "researcher": "胡光怿",
        "title": "华南物流园增值添利，高比例分红回报股东",
        "report_type": "2024年年报点评（首次覆盖）",
        "title_markers": ["华南物流园增值添利", "高比例分红回报股东"],
        "min_pages": 11,
        "max_pages": 14,
    },
    {
        "report_id": 4438234,
        "image_date": "2024/08/10",
        "broker": "国金证券",
        "publish_date": "2024-08-10",
        "researcher": "郑树明",
        "title": "土地转性贡献弹性，高股息价值凸显",
        "report_type": "公司深度／首次覆盖",
        "title_markers": ["土地转性贡献弹性", "高股息价值凸显"],
        "min_pages": 24,
        "max_pages": 35,
    },
    {
        "report_id": 4069371,
        "image_date": "2023/12/20",
        "broker": "国投证券",
        "publish_date": "2023-12-20",
        "researcher": "孙延",
        "title": "高股息价值凸显，物流园资产释放盈利弹性",
        "report_type": "公司深度分析报告",
        "title_markers": ["高股息价值凸显", "物流园资产释放盈利弹性"],
        "min_pages": 20,
        "max_pages": 35,
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


def compact(text: str) -> str:
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


def source_pages(report_id: int) -> list[str]:
    return [
        f"https://www.fxbaogao.com/detail/{report_id}",
        f"https://www.fxbaogao.com/view?id={report_id}",
    ]


def request_html(url: str) -> tuple[str, str]:
    response = session.get(url, timeout=(25, 180), allow_redirects=True)
    response.raise_for_status()
    encoding = response.apparent_encoding or response.encoding or "utf-8"
    text = response.content.decode(encoding, errors="replace")
    return html_lib.unescape(text).replace("\\/", "/"), response.url


def validate_source_page(record: dict[str, Any]) -> tuple[str, list[int]]:
    collected_text: list[str] = []
    discovered_pages: set[int] = set()
    errors: list[str] = []
    report_id = int(record["report_id"])

    image_pattern = re.compile(
        rf"(?:https?:)?//public\.fxbaogao\.com/report-image/[^\"'<>\s]+?/{report_id}-(\d+)\.png",
        flags=re.I,
    )

    final_detail_url = source_pages(report_id)[0]
    for url in source_pages(report_id):
        try:
            text, final_url = request_html(url)
            if "/detail/" in url:
                final_detail_url = final_url
            soup = BeautifulSoup(text, "html.parser")
            collected_text.append(soup.get_text(" ", strip=True))
            for page_text in image_pattern.findall(text):
                discovered_pages.add(int(page_text))
            print(
                f"SOURCE {report_id} {url} -> {final_url}; "
                f"bytes={len(text.encode('utf-8'))}; images={sorted(discovered_pages)}"
            )
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            print(f"SOURCE ERROR {report_id} {url}: {exc}")

    all_text = compact("\n".join(collected_text))
    if not all_text:
        raise RuntimeError(
            f"Unable to read public source pages for {report_id}: " + " | ".join(errors)
        )

    required_groups = [
        (SHORT_NAME, "深圳國際", STOCK_CODE, "0152.hk"),
        (str(record["broker"]),),
    ]
    for group in required_groups:
        if not any(compact(marker) in all_text for marker in group):
            raise RuntimeError(
                f"Source page lacks required report identity marker {group}: {report_id}"
            )
    for marker in record["title_markers"]:
        if compact(marker) not in all_text:
            raise RuntimeError(
                f"Source page lacks title marker {marker!r}: {report_id}"
            )

    return final_detail_url, sorted(discovered_pages)


def image_candidates(record: dict[str, Any], page_number: int) -> list[str]:
    base = (
        "https://public.fxbaogao.com/report-image/"
        f"{record['image_date']}/{record['report_id']}-{page_number}.png"
    )
    return [
        base,
        base + "?x-oss-process=image/format,png",
        base + "?x-oss-process=image/format,webp",
    ]


def get_page_image(
    record: dict[str, Any], page_number: int, target: Path
) -> tuple[str, int, int] | None:
    detail_url = source_pages(int(record["report_id"]))[0]
    errors: list[str] = []
    for url in image_candidates(record, page_number):
        try:
            response = session.get(
                url,
                headers={
                    "Referer": detail_url,
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                },
                timeout=(25, 180),
                allow_redirects=True,
            )
            if response.status_code == 404:
                continue
            response.raise_for_status()
            raw = response.content
            if len(raw) < 30_000:
                errors.append(f"{url}: image too small ({len(raw)} bytes)")
                continue
            image = Image.open(BytesIO(raw))
            image.load()
            width, height = image.size
            if width < 700 or height < 900:
                errors.append(f"{url}: implausible dimensions {width}x{height}")
                continue
            # Normalize every page to PNG so img2pdf embeds a predictable image format.
            if image.mode not in ("RGB", "L"):
                background = Image.new("RGB", image.size, "white")
                if "A" in image.getbands():
                    background.paste(image, mask=image.getchannel("A"))
                else:
                    background.paste(image.convert("RGB"))
                image = background
            elif image.mode == "L":
                image = image.convert("RGB")
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target, format="PNG", optimize=True)
            print(
                f"IMAGE {record['report_id']} page={page_number} "
                f"{width}x{height} {target.stat().st_size} bytes <- {url}"
            )
            return url, width, height
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    if errors:
        print(
            f"IMAGE MISS {record['report_id']} page={page_number}: "
            + " | ".join(errors[-3:])
        )
    return None


def download_all_pages(
    record: dict[str, Any], discovered_pages: list[int]
) -> tuple[list[Path], list[str]]:
    report_image_dir = IMAGE_ROOT / str(record["report_id"])
    if report_image_dir.exists():
        shutil.rmtree(report_image_dir)
    report_image_dir.mkdir(parents=True)

    min_pages = int(record["min_pages"])
    max_pages = int(record["max_pages"])
    probe_limit = max(max_pages + 3, max(discovered_pages, default=0) + 3)
    image_paths: list[Path] = []
    source_urls: list[str] = []
    misses_after_found = 0

    for page_number in range(1, probe_limit + 1):
        target = report_image_dir / f"{page_number:03d}.png"
        result = get_page_image(record, page_number, target)
        if result is None:
            if image_paths:
                misses_after_found += 1
                if page_number > min_pages and misses_after_found >= 2:
                    break
            continue
        misses_after_found = 0
        image_paths.append(target)
        source_urls.append(result[0])
        time.sleep(0.08)

    found_numbers = [int(path.stem) for path in image_paths]
    if not found_numbers:
        raise RuntimeError(f"No public page images downloaded for {record['report_id']}")
    expected_numbers = list(range(1, max(found_numbers) + 1))
    if found_numbers != expected_numbers:
        raise RuntimeError(
            f"Non-contiguous public pages for {record['report_id']}: {found_numbers}"
        )
    page_count = len(image_paths)
    if not min_pages <= page_count <= max_pages:
        raise RuntimeError(
            f"Unexpected page count for {record['report_id']}: "
            f"{page_count}, expected {min_pages}..{max_pages}"
        )
    if discovered_pages and max(discovered_pages) > page_count:
        raise RuntimeError(
            f"Downloaded page count is below page numbers declared by source page: "
            f"{record['report_id']} {page_count} < {max(discovered_pages)}"
        )

    return image_paths, source_urls


def build_pdf(image_paths: list[Path], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    try:
        target.write_bytes(img2pdf.convert([str(path) for path in image_paths]))
    except Exception as exc:
        print(f"img2pdf fallback for {target.name}: {exc}")
        opened = [Image.open(path).convert("RGB") for path in image_paths]
        try:
            opened[0].save(
                target,
                "PDF",
                save_all=True,
                append_images=opened[1:],
                resolution=144.0,
                quality=95,
            )
        finally:
            for image in opened:
                image.close()


def inspect_pdf(path: Path, expected_pages: int) -> dict[str, Any]:
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF-"):
        raise RuntimeError(f"Not a PDF: {path}")
    reader = PdfReader(str(path))
    if reader.is_encrypted and reader.decrypt("") == 0:
        raise RuntimeError(f"PDF cannot be decrypted: {path}")
    pages = len(reader.pages)
    if pages != expected_pages:
        raise RuntimeError(f"PDF page mismatch: {path} {pages} != {expected_pages}")

    document = pymupdf.open(path)
    if document.page_count != pages:
        raise RuntimeError(f"Parser page mismatch: {path}")
    for page_index in sorted({0, pages // 2, pages - 1}):
        pixmap = document.load_page(page_index).get_pixmap(
            matrix=pymupdf.Matrix(0.45, 0.45), alpha=False
        )
        if pixmap.width < 250 or pixmap.height < 350:
            raise RuntimeError(
                f"Render check failed: {path}, page {page_index + 1}"
            )
    document.close()
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "text_searchable": False,
    }


def main() -> None:
    for path in (PACKAGE, IMAGE_ROOT):
        if path.exists():
            shutil.rmtree(path)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_ROOT.mkdir(parents=True, exist_ok=True)
    OUTPUT.unlink(missing_ok=True)

    documents: list[dict[str, Any]] = []
    checksum_lines: list[str] = []

    for index, record in enumerate(REPORTS, 1):
        source_page, discovered_pages = validate_source_page(record)
        image_paths, image_source_urls = download_all_pages(record, discovered_pages)
        filename = safe_filename(
            f"{index:02d}_{record['broker']}_{record['publish_date'].replace('-', '')}_"
            f"{record['title']}.pdf"
        )
        pdf_path = REPORT_DIR / filename
        build_pdf(image_paths, pdf_path)
        metadata = inspect_pdf(pdf_path, len(image_paths))
        rel_path = str(pdf_path.relative_to(PACKAGE))

        item = {
            "company": COMPANY,
            "short_name": SHORT_NAME,
            "ticker": TICKER,
            "broker": record["broker"],
            "publish_date": record["publish_date"],
            "researcher": record["researcher"],
            "title": record["title"],
            "report_type": record["report_type"],
            "file": rel_path,
            **metadata,
            "source_page": source_page,
            "public_page_image_base": (
                "https://public.fxbaogao.com/report-image/"
                f"{record['image_date']}/{record['report_id']}-{{page}}.png"
            ),
            "report_id": record["report_id"],
            "source_page_images": image_source_urls,
            "delivery_note": (
                "由来源页面公开展示的完整逐页图像按原页序合成为PDF；"
                "非券商原生文本层PDF，因此正文不可全文检索。"
            ),
        }
        documents.append(item)
        checksum_lines.append(f"{item['sha256']}  {rel_path}")

    if len(documents) != 3:
        raise RuntimeError(f"Expected 3 reports, found {len(documents)}")

    total_pages = sum(int(item["pages"]) for item in documents)
    total_bytes = sum(int(item["bytes"]) for item in documents)

    readme_lines = [
        f"{COMPANY}（{TICKER}，{SHORT_NAME}）券商公司研究报告",
        f"整理日期：{PREPARED_DATE}",
        "",
        "收录口径",
        "1. 收录两份篇幅较完整的公司深度/首次覆盖报告，以及一份11页首次覆盖年报点评。",
        "2. 排除只有3—5页的常规业绩点评，不使用短报告凑数。",
        "3. 来源网站无需登录即可公开完整阅读各报告的逐页页面图像。",
        "4. 本包将公开逐页图像按原顺序合成为PDF，保持完整页数和页面版式；",
        "   交付PDF为图像型PDF，不含券商原生文本层，正文不可全文检索。",
        "",
        "文件清单",
    ]
    for index, item in enumerate(documents, 1):
        readme_lines.extend(
            [
                f"{index}. {item['broker']}：{item['title']}",
                f"   类型：{item['report_type']}",
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
            f"- 共3份PDF，合计{total_pages}页，未压缩PDF总大小{total_bytes / 1024 / 1024:.2f} MiB。",
            "- 已核对每份报告的公司、股票代码、券商、标题、发布日期和连续页码。",
            "- 已检查PDF文件头、结构和页数，并渲染检查首页、中间页和末页。",
            "- ZIP已通过CRC完整性测试；逐文件SHA-256见SHA256SUMS.txt。",
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
                "delivery_format": "公开完整逐页图像合成的图像型PDF",
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
