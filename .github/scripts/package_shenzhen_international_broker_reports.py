from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import zipfile
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pymupdf as fitz
import requests
from bs4 import BeautifulSoup
from PIL import Image
from pypdf import PdfReader

ROOT = Path.cwd()
PACKAGE = ROOT / "shenzhen_international_broker_reports_verified"
REPORT_DIR = PACKAGE / "01_券商研究报告"
IMAGE_ROOT = ROOT / "shenzhen_international_report_images"
for directory in (REPORT_DIR, IMAGE_ROOT):
    directory.mkdir(parents=True, exist_ok=True)

OUTPUT_ZIP = ROOT / "深圳国际_券商深度报告_2份_完整PDF.zip"

REPORTS = [
    {
        "detail_id": 4438234,
        "broker": "国金证券",
        "report_date": "2024-08-10",
        "title": "土地转性贡献弹性，高股息价值凸显",
        "kind": "公司深度/首次覆盖",
        "minimum_pages": 15,
        "expected_pages": None,
        "filename": "01_国金证券_20240810_土地转性贡献弹性，高股息价值凸显.pdf",
        "fallback_dates": ["2024/08/10", "2024/08/09", "2024/08/11"],
    },
    {
        "detail_id": 4788440,
        "broker": "西南证券",
        "report_date": "2025-04-17",
        "title": "华南物流园增值添利，高比例分红回报股东",
        "kind": "首次覆盖年报点评",
        "minimum_pages": 10,
        "expected_pages": 11,
        "filename": "02_西南证券_20250417_华南物流园增值添利，高比例分红回报股东.pdf",
        "fallback_dates": ["2025/04/17", "2025/05/07", "2025/04/18"],
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
        "Referer": "https://www.fxbaogao.com/",
    }
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def request_bytes(url: str, *, referer: str, minimum_size: int = 4_000) -> bytes:
    errors: list[str] = []
    for attempt in range(1, 5):
        try:
            response = session.get(
                url,
                headers={"Referer": referer},
                timeout=(20, 180),
                allow_redirects=True,
            )
            response.raise_for_status()
            content = response.content
            if len(content) < minimum_size:
                raise RuntimeError(f"response too small: {len(content)} bytes")
            return content
        except Exception as exc:
            errors.append(f"attempt {attempt}: {exc}")
            time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to download {url}: {' | '.join(errors)}")


def discover_first_image(report: dict) -> tuple[str, str]:
    detail_url = f"https://www.fxbaogao.com/detail/{report['detail_id']}"
    try:
        response = session.get(detail_url, timeout=(20, 120), allow_redirects=True)
        response.raise_for_status()
        text = response.text.replace("\\/", "/")
        soup = BeautifulSoup(text, "html.parser")
        candidates: list[str] = []
        for tag in soup.find_all("img", src=True):
            src = clean_url(tag["src"])
            if "report-image" in src and str(report["detail_id"]) in src:
                candidates.append(src)
        candidates.extend(
            clean_url(match)
            for match in re.findall(
                r'https?://[^\"\'<>\s]+report-image[^\"\'<>\s]+',
                text,
                flags=re.I,
            )
            if str(report["detail_id"]) in match
        )
        candidates = list(dict.fromkeys(candidates))
        for candidate in candidates:
            if re.search(rf"/{report['detail_id']}-1\.(?:png|jpg|jpeg|webp)$", candidate, flags=re.I):
                print(f"Discovered first page image from detail HTML: {candidate}")
                return candidate, response.url
    except Exception as exc:
        print(f"Detail-page discovery warning for {report['detail_id']}: {exc}")

    # Fallback to the public image convention used by the report viewer.
    for date_path in report["fallback_dates"]:
        for extension in ("png", "jpg", "jpeg"):
            candidate = (
                "https://public.fxbaogao.com/report-image/"
                f"{date_path}/{report['detail_id']}-1.{extension}"
            )
            try:
                content = request_bytes(candidate, referer=detail_url)
                with Image.open(BytesIO(content)) as image:
                    image.verify()
                print(f"Discovered first page image by probing: {candidate}")
                return candidate, detail_url
            except Exception:
                continue
    raise RuntimeError(f"Unable to discover public page images for report {report['detail_id']}")


def download_page_images(report: dict) -> tuple[list[Path], str, str]:
    first_image_url, referer = discover_first_image(report)
    match = re.match(r"(.*/)(\d+)-1\.(png|jpg|jpeg|webp)$", first_image_url, flags=re.I)
    if not match:
        raise RuntimeError(f"Unexpected first-image URL: {first_image_url}")
    prefix, report_id, extension = match.groups()
    if int(report_id) != int(report["detail_id"]):
        raise RuntimeError(f"Report ID mismatch in image URL: {first_image_url}")

    image_dir = IMAGE_ROOT / str(report["detail_id"])
    if image_dir.exists():
        shutil.rmtree(image_dir)
    image_dir.mkdir(parents=True)

    downloaded: list[Path] = []
    consecutive_misses = 0
    for page_number in range(1, 101):
        url = f"{prefix}{report_id}-{page_number}.{extension}"
        try:
            content = request_bytes(url, referer=referer)
            image_path = image_dir / f"{page_number:03d}.{extension.lower()}"
            image_path.write_bytes(content)
            with Image.open(image_path) as image:
                image.verify()
            if image_path.stat().st_size < 4_000:
                raise RuntimeError("page image is unexpectedly small")
            downloaded.append(image_path)
            consecutive_misses = 0
            print(f"Downloaded report {report_id} page {page_number}: {len(content)} bytes")
        except Exception as exc:
            consecutive_misses += 1
            print(f"Page miss report {report_id} page {page_number}: {exc}")
            if downloaded and consecutive_misses >= 3:
                break

    if len(downloaded) < int(report["minimum_pages"]):
        raise RuntimeError(
            f"Incomplete report {report_id}: only {len(downloaded)} pages, "
            f"minimum expected {report['minimum_pages']}"
        )
    expected_pages = report.get("expected_pages")
    if expected_pages is not None and len(downloaded) != int(expected_pages):
        raise RuntimeError(
            f"Unexpected page count for report {report_id}: "
            f"{len(downloaded)} != {expected_pages}"
        )
    return downloaded, first_image_url, referer


def images_to_pdf(image_paths: list[Path], target: Path) -> None:
    document = fitz.open()
    for image_path in image_paths:
        with Image.open(image_path) as image:
            width, height = image.size
        if width < 500 or height < 500:
            raise RuntimeError(f"Image dimensions too small: {image_path} {width}x{height}")
        page = document.new_page(width=width, height=height)
        page.insert_image(page.rect, filename=str(image_path), keep_proportion=True)
    document.set_metadata(
        {
            "title": target.stem,
            "subject": "Publicly viewable broker research pages assembled into PDF",
            "creator": "OpenAI report packaging workflow",
        }
    )
    document.save(target, deflate=True, garbage=4)
    document.close()


def verify_pdf(path: Path, expected_pages: int) -> dict[str, int | str]:
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF-"):
        raise RuntimeError(f"Not a PDF: {path}")
    reader = PdfReader(str(path))
    if reader.is_encrypted and reader.decrypt("") == 0:
        raise RuntimeError(f"Cannot decrypt PDF: {path}")
    pages = len(reader.pages)
    if pages != expected_pages:
        raise RuntimeError(f"PDF page-count mismatch: {path}: {pages} != {expected_pages}")

    document = fitz.open(path)
    if document.page_count != pages:
        raise RuntimeError(f"PyMuPDF page-count mismatch: {path}")
    for page_index in sorted({0, pages // 2, pages - 1}):
        pixmap = document.load_page(page_index).get_pixmap(
            matrix=fitz.Matrix(0.35, 0.35), alpha=False
        )
        if pixmap.width < 150 or pixmap.height < 150:
            raise RuntimeError(f"Page render failed: {path} page {page_index + 1}")
    document.close()
    return {"pages": pages, "bytes": path.stat().st_size, "sha256": sha256(path)}


documents: list[dict] = []
for report in REPORTS:
    image_paths, first_image_url, detail_url = download_page_images(report)
    target = REPORT_DIR / report["filename"]
    images_to_pdf(image_paths, target)
    verified = verify_pdf(target, len(image_paths))
    documents.append(
        {
            "company": "深圳国际控股有限公司",
            "ticker": "00152.HK",
            "broker": report["broker"],
            "report_date": report["report_date"],
            "title": report["title"],
            "kind": report["kind"],
            "file": str(target.relative_to(PACKAGE)),
            "pages": verified["pages"],
            "bytes": verified["bytes"],
            "sha256": verified["sha256"],
            "source_detail_page": f"https://www.fxbaogao.com/detail/{report['detail_id']}",
            "public_page_image_pattern": first_image_url,
            "format_note": (
                "由公开可查看的逐页页面图像按原顺序合成为PDF；"
                "不是券商原始矢量PDF，页面内容与顺序保持不变。"
            ),
        }
    )

if len(documents) != 2:
    raise RuntimeError(f"Expected two reports, got {len(documents)}")
if int(documents[0]["pages"]) < 15:
    raise RuntimeError("The selected Guojin report does not meet the deep-report page threshold")
if int(documents[1]["pages"]) != 11:
    raise RuntimeError("The selected Southwest report is not the verified 11-page version")

manifest = {
    "company": "深圳国际控股有限公司",
    "ticker": "00152.HK",
    "prepared_date": "2026-08-31",
    "selection_policy": (
        "优先选择公司深度或首次覆盖报告；排除仅数页的常规业绩快评。"
    ),
    "document_count": len(documents),
    "total_pages": sum(int(item["pages"]) for item in documents),
    "total_bytes": sum(int(item["bytes"]) for item in documents),
    "documents": documents,
}
(PACKAGE / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)

readme_lines = [
    "深圳国际控股有限公司（00152.HK）券商研究报告",
    "整理日期：2026-08-31",
    "",
    "筛选口径",
    "1. 优先选择公司深度或首次覆盖报告。",
    "2. 未将仅3—5页的常规业绩快评纳入压缩包。",
    "3. 国金证券报告为公司深度/首次覆盖；西南证券报告为11页首次覆盖年报点评。",
    "4. 两份PDF均由报告聚合平台公开可查看的逐页图像按原顺序合成，",
    "   因而不是券商原始矢量PDF，但页面内容、页数和顺序保持不变。",
    "",
    "文件清单",
]
for index, item in enumerate(documents, 1):
    readme_lines.extend(
        [
            f"{index}. {item['broker']}：《{item['title']}》",
            f"   类型：{item['kind']}",
            f"   报告日期：{item['report_date']}",
            f"   页数：{item['pages']}",
            f"   文件：{item['file']}",
            f"   SHA-256：{item['sha256']}",
            f"   来源页面：{item['source_detail_page']}",
            f"   说明：{item['format_note']}",
            "",
        ]
    )
readme_lines.extend(
    [
        "完整性检查",
        f"- 共{manifest['document_count']}份PDF，合计{manifest['total_pages']}页。",
        "- 每份PDF均检查文件头、结构、页数，并渲染首页、中间页及末页。",
        "- ZIP已通过CRC完整性测试；逐文件哈希见SHA256SUMS.txt。",
    ]
)
(PACKAGE / "README_来源与校验.txt").write_text(
    "\n".join(readme_lines), encoding="utf-8"
)
(PACKAGE / "SHA256SUMS.txt").write_text(
    "\n".join(f"{item['sha256']}  {item['file']}" for item in documents) + "\n",
    encoding="utf-8",
)

OUTPUT_ZIP.unlink(missing_ok=True)
with zipfile.ZipFile(
    OUTPUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
) as archive:
    for path in sorted(PACKAGE.rglob("*")):
        if path.is_file():
            archive.write(path, arcname=str(path.relative_to(PACKAGE)))

with zipfile.ZipFile(OUTPUT_ZIP, "r") as archive:
    bad = archive.testzip()
    if bad:
        raise RuntimeError(f"ZIP CRC verification failed: {bad}")
    pdf_count = sum(1 for name in archive.namelist() if name.lower().endswith(".pdf"))
    if pdf_count != 2:
        raise RuntimeError(f"Unexpected PDF count in ZIP: {pdf_count}")

print((PACKAGE / "README_来源与校验.txt").read_text(encoding="utf-8"))
print(f"ZIP_FILE={OUTPUT_ZIP}")
print(f"ZIP_BYTES={OUTPUT_ZIP.stat().st_size}")
print(f"ZIP_SHA256={sha256(OUTPUT_ZIP)}")
