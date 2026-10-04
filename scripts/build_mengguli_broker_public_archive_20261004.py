from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

import img2pdf
import requests
from PIL import Image
from pypdf import PdfReader

CHECKED_AS_OF = "2026-10-04"
COMPANY = "天津国安盟固利新材料科技股份有限公司"
SHORT_NAME = "盟固利"
STOCK_CODE = "301487"
PACKAGE = "盟固利_301487_券商研究报告_2份_公开页面存档版_2026-10-04"
ROOT = Path(PACKAGE)
WORK = Path("_mengguli_broker_public_archive_work")
IMAGE_ROOT = WORK / "images"
RENDER_ROOT = WORK / "renders"
for directory in (ROOT, IMAGE_ROOT, RENDER_ROOT):
    directory.mkdir(parents=True, exist_ok=True)

REPORTS: list[dict[str, Any]] = [
    {
        "sequence": 1,
        "broker": "西南证券",
        "title": "业绩扭亏为盈，NCA及前沿材料迎新机遇",
        "report_date": "2026-02-03",
        "authors": ["郑连声", "韩晨"],
        "page_count": 6,
        "page_url_template": "https://oss.sdyanbao.com/page/2026/2/3/1286977/{page}.png",
        "detail_url": "https://www.sdyanbao.com/detail/943276",
        "secondary_source_url": "https://wap.hibor.com.cn/repinfodetail_4884517.html",
        "filename": "01_西南证券_盟固利_业绩扭亏为盈_NCA及前沿材料迎新机遇_2026-02-03_公开页面图重组版.pdf",
    },
    {
        "sequence": 2,
        "broker": "华金证券",
        "title": "25年业绩表现亮眼，拟投资建设磷酸铁锂一体化项目",
        "report_date": "2026-05-14",
        "authors": ["贺朝晖"],
        "page_count": 5,
        "page_url_template": "https://oss.sdyanbao.com/page/2026/5/14/1333943/{page}.png",
        "detail_url": "https://www.sdyanbao.com/detail/970423",
        "secondary_source_url": "https://www.sohu.com/a/1022638091_115377",
        "filename": "02_华金证券_盟固利_25年业绩表现亮眼_拟投资建设磷酸铁锂一体化项目_2026-05-14_公开页面图重组版.pdf",
    },
]

SESSION = requests.Session()
SESSION.trust_env = False
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_image(url: str, destination: Path, referer: str) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    headers = dict(BASE_HEADERS)
    headers["Referer"] = referer
    errors: list[str] = []
    for attempt in range(1, 7):
        try:
            response = SESSION.get(url, headers=headers, timeout=(20, 180), allow_redirects=True)
            print(
                "HTTP", url, "attempt", attempt, "status", response.status_code,
                "type", response.headers.get("content-type"), "length", len(response.content),
                "final", response.url, flush=True,
            )
            response.raise_for_status()
            payload = response.content
            if len(payload) < 20_000:
                raise RuntimeError(f"image payload too small: {len(payload)} bytes")
            destination.write_bytes(payload)
            with Image.open(destination) as image:
                image.verify()
            with Image.open(destination) as image:
                width, height = image.size
                mode = image.mode
                fmt = image.format
            if width < 900 or height < 900:
                raise RuntimeError(f"unexpected image dimensions: {width}x{height}")
            return {
                "source_url": str(response.url),
                "bytes": len(payload),
                "sha256": sha256(destination),
                "width": width,
                "height": height,
                "mode": mode,
                "format": fmt,
            }
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            destination.unlink(missing_ok=True)
            time.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"failed to download {url}: {errors[-6:]}")


def normalize_for_pdf(source: Path, destination: Path) -> Path:
    with Image.open(source) as image:
        image.load()
        if image.mode in ("RGB", "L", "1"):
            shutil.copy2(source, destination)
        else:
            background = Image.new("RGB", image.size, "white")
            if image.mode in ("RGBA", "LA"):
                alpha = image.getchannel("A")
                background.paste(image.convert("RGB"), mask=alpha)
            else:
                background.paste(image.convert("RGB"))
            background.save(destination, format="PNG", optimize=False)
    return destination


def render_page(pdf_path: Path, page_number: int, tag: str) -> Path:
    prefix = RENDER_ROOT / f"{hashlib.sha1(str(pdf_path).encode()).hexdigest()}_{tag}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number), "-r", "96",
            "-png", "-singlefile", str(pdf_path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    image_path = Path(str(prefix) + ".png")
    if process.returncode != 0 or not image_path.exists() or image_path.stat().st_size < 10_000:
        raise RuntimeError(
            f"render validation failed for {pdf_path.name} page {page_number}: {process.stderr[-2000:]}"
        )
    with Image.open(image_path) as image:
        image.verify()
    return image_path


def build_report(report: dict[str, Any]) -> dict[str, Any]:
    report_image_dir = IMAGE_ROOT / f"{report['sequence']:02d}_{report['broker']}"
    report_image_dir.mkdir(parents=True, exist_ok=True)
    normalized_paths: list[Path] = []
    page_records: list[dict[str, Any]] = []

    for page_index in range(report["page_count"]):
        url = report["page_url_template"].format(page=page_index)
        raw_path = report_image_dir / f"page_{page_index + 1:02d}_raw.png"
        metadata = download_image(url, raw_path, report["detail_url"])
        normalized_path = report_image_dir / f"page_{page_index + 1:02d}.png"
        normalize_for_pdf(raw_path, normalized_path)
        with Image.open(normalized_path) as image:
            image.verify()
        normalized_paths.append(normalized_path)
        page_records.append({
            "page_number": page_index + 1,
            **metadata,
            "normalized_sha256": sha256(normalized_path),
        })

    output_path = ROOT / report["filename"]
    output_path.write_bytes(img2pdf.convert([str(path) for path in normalized_paths]))
    if output_path.read_bytes()[:5] != b"%PDF-":
        raise RuntimeError(f"invalid PDF header: {output_path}")

    qpdf = subprocess.run(
        ["qpdf", "--check", str(output_path)], capture_output=True, text=True, timeout=300
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf validation failed for {output_path.name}: {qpdf.stderr[-2500:]}")

    reader = PdfReader(str(output_path), strict=False)
    actual_pages = len(reader.pages)
    if actual_pages != report["page_count"]:
        raise RuntimeError(
            f"page-count mismatch for {output_path.name}: expected {report['page_count']}, got {actual_pages}"
        )
    first_render = render_page(output_path, 1, "first")
    last_render = render_page(output_path, actual_pages, "last")

    return {
        "broker": report["broker"],
        "title": report["title"],
        "report_date": report["report_date"],
        "authors": report["authors"],
        "stock_code": STOCK_CODE,
        "company": SHORT_NAME,
        "archive_status": "根据公开网页逐页图片按原顺序重组的存档PDF，不是券商分发的原始PDF",
        "content_processing": "未改写页面内容；仅按页码排序并封装为PDF",
        "relative_path": output_path.name,
        "pages": actual_pages,
        "bytes": output_path.stat().st_size,
        "sha256": sha256(output_path),
        "detail_url": report["detail_url"],
        "secondary_source_url": report["secondary_source_url"],
        "page_image_source_template": report["page_url_template"],
        "qpdf_return_code": qpdf.returncode,
        "first_page_render_sha256": sha256(first_render),
        "last_page_render_sha256": sha256(last_render),
        "page_images": page_records,
    }


def main() -> None:
    records = [build_report(report) for report in REPORTS]

    readme = [
        f"{SHORT_NAME}（{STOCK_CODE}.SZ）券商研究报告公开页面存档包",
        f"核对日期：{CHECKED_AS_OF}",
        "",
        "重要版本说明：",
        "1. 本包中的两份PDF均由公开网页提供的逐页报告图片，严格依照公开页码顺序重组。",
        "2. 这些文件不是券商研究所或数据平台直接分发的原始PDF，文件名已明确标注“公开页面图重组版”。",
        "3. 重组过程中未改写、删节或增补报告页面内容，只进行了图片下载、页序核对和PDF封装。",
        "4. 公开页面及其可访问性可能发生变化，本包同时保存逐页来源模板、文件哈希和验证记录。",
        "",
        "收录报告：",
    ]
    for index, record in enumerate(records, start=1):
        readme.extend([
            f"{index}. {record['broker']}：《{record['title']}》",
            f"   日期：{record['report_date']}",
            f"   作者：{'、'.join(record['authors'])}",
            f"   页数：{record['pages']}",
            f"   文件：{record['relative_path']}",
            f"   SHA-256：{record['sha256']}",
            f"   公开详情页：{record['detail_url']}",
            f"   辅助核对页：{record['secondary_source_url']}",
            f"   逐页图片模板：{record['page_image_source_template']}",
            "",
        ])
    readme.extend([
        "校验说明：",
        "- 每张公开页面图片均检查文件大小、图像格式、分辨率与SHA-256。",
        "- 每份PDF均检查PDF文件头、实际页数、QPDF结构，并渲染首页和末页进行可读性验证。",
        "- 最终ZIP执行完整性测试。",
        "",
        "版权与使用：",
        "报告著作权及相关权益归原券商研究机构及作者所有。本资料包仅用于个人研究、核验与存档，请勿用于商业再分发。",
    ])
    (ROOT / "README_说明与来源.txt").write_text("\n".join(readme), encoding="utf-8")
    (ROOT / "manifest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    checksum_lines = [f"{record['sha256']}  {record['relative_path']}" for record in records]
    checksum_lines.extend([
        f"{sha256(ROOT / 'README_说明与来源.txt')}  README_说明与来源.txt",
        f"{sha256(ROOT / 'manifest.json')}  manifest.json",
    ])
    (ROOT / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    zip_path = Path(PACKAGE + ".zip")
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, f"{ROOT.name}/{path.relative_to(ROOT).as_posix()}")
    with zipfile.ZipFile(zip_path, "r") as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP integrity test failed at {bad}")
        members = archive.namelist()

    summary = {
        "package": zip_path.name,
        "zip_bytes": zip_path.stat().st_size,
        "zip_sha256": sha256(zip_path),
        "report_count": len(records),
        "total_pages": sum(record["pages"] for record in records),
        "members": members,
        "records": records,
    }
    print("FINAL_SUMMARY", json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
