from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

import img2pdf
import requests
from PIL import Image
from pypdf import PdfReader

PACKAGE = "希迪智驾_03881_券商深度报告_2份_20260922"
ROOT = Path(PACKAGE)
REPORT_DIR = ROOT / "01_券商报告"
SOURCE_DIR = ROOT / "02_来源与校验"
WORK = Path("_cidi_reports_work")
RENDER = WORK / "renders"
for directory in (REPORT_DIR, SOURCE_DIR, WORK, RENDER):
    directory.mkdir(parents=True, exist_ok=True)

REPORTS = [
    {
        "key": "guosen",
        "broker": "国信证券",
        "title": "希迪智驾（03881.HK）：无人驾驶矿卡领先企业，技术叠加降本推进商业化",
        "report_date": "2026-01-15",
        "analysts": "唐旭霞、杨钐",
        "rating": "优于大市（首次覆盖）",
        "page_count": 70,
        "filename": "01_国信证券_无人驾驶矿卡领先企业_技术叠加降本推进商业化_20260115_70页.pdf",
        "source_page": "https://www.sdyanbao.com/detail/943185",
        "image_kind": "sdy_png",
        "image_base": "https://oss.sdyanbao.com/page/2026/2/3/1286719",
        "source_note": "由公开可访问的70页逐页预览图按原页序合成PDF；非券商服务器上的原始PDF二进制文件。",
    },
    {
        "key": "dongwu",
        "broker": "东吴证券",
        "title": "希迪智驾（03881.HK）：定位升维，从无人矿卡进化到重载具身智能",
        "report_date": "2026-06-30",
        "analysts": "黄细里、孙仁昊",
        "rating": "买入",
        "page_count": 12,
        "filename": "02_东吴证券_定位升维从无人矿卡进化到重载具身智能_20260630_12页.pdf",
        "source_page": "https://www.sgpjbg.com/baogao/1272831.html",
        "image_kind": "sgpjbg_gif",
        "image_base": "https://file.sgpjbg.com/fileroot3/2026-6/30/b38d686c-c9c3-4e65-a64e-2c2719bcb1b0/b38d686c-c9c3-4e65-a64e-2c2719bcb1b0",
        "source_note": "由公开可访问的12页逐页预览图按原页序合成PDF；非券商服务器上的原始PDF二进制文件。",
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
SESSION = requests.Session()
SESSION.trust_env = False


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_candidates(report: dict, page_index: int) -> list[str]:
    if report["image_kind"] == "sdy_png":
        zero_based = page_index - 1
        base = report["image_base"]
        return [
            f"{base}/{zero_based}.png",
            f"{base}/{zero_based}.jpg",
            f"{base}/{zero_based}.webp",
        ]
    base = report["image_base"]
    return [
        f"{base}{page_index}.gif",
        f"{base}{page_index}.png",
        f"{base}{page_index}.jpg",
    ]


def download_page(report: dict, page_index: int, destination: Path) -> dict:
    request_headers = dict(HEADERS)
    request_headers["Referer"] = report["source_page"]
    errors: list[str] = []
    for url in get_candidates(report, page_index):
        for attempt in range(1, 6):
            temporary = destination.with_suffix(".download")
            temporary.unlink(missing_ok=True)
            try:
                response = SESSION.get(url, headers=request_headers, timeout=(15, 180), allow_redirects=True)
                content_type = response.headers.get("content-type", "")
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}")
                if len(response.content) < 3000:
                    raise RuntimeError(f"response too small: {len(response.content)} bytes")
                temporary.write_bytes(response.content)
                with Image.open(temporary) as image:
                    image.load()
                    width, height = image.size
                    image_format = image.format
                    if width < 600 or height < 800:
                        raise RuntimeError(f"page image too small: {width}x{height}")
                    if image.mode not in ("RGB", "L"):
                        image = image.convert("RGB")
                    image.save(destination, format="PNG", optimize=False)
                temporary.unlink(missing_ok=True)
                return {
                    "page": page_index,
                    "source_url": str(response.url),
                    "content_type": content_type,
                    "original_format": image_format,
                    "width": width,
                    "height": height,
                    "bytes": destination.stat().st_size,
                    "sha256": sha256(destination),
                }
            except Exception as exc:
                errors.append(f"{url} attempt {attempt}: {exc!r}")
                temporary.unlink(missing_ok=True)
                time.sleep(min(attempt * 2, 8))
    raise RuntimeError(f"Unable to obtain page {page_index} for {report['key']}: {errors[-10:]}")


def build_pdf(images: list[Path], output: Path) -> dict:
    with output.open("wb") as handle:
        handle.write(img2pdf.convert([str(path) for path in images]))
    if output.stat().st_size < 100_000 or not output.read_bytes()[:8].startswith(b"%PDF-"):
        raise RuntimeError(f"Invalid generated PDF: {output}")
    reader = PdfReader(str(output), strict=False)
    page_count = len(reader.pages)
    if page_count != len(images):
        raise RuntimeError(f"Page count mismatch for {output}: {page_count} != {len(images)}")
    qpdf = subprocess.run(["qpdf", "--check", str(output)], capture_output=True, text=True)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {output}: {qpdf.stderr[-2000:]}")
    rendered = []
    for page_number in sorted(set([1, page_count])):
        prefix = RENDER / f"{output.stem}_{page_number}"
        process = subprocess.run(
            ["pdftoppm", "-f", str(page_number), "-l", str(page_number), "-r", "72", "-png", "-singlefile", str(output), str(prefix)],
            capture_output=True,
            text=True,
            timeout=240,
        )
        png = Path(str(prefix) + ".png")
        if process.returncode != 0 or not png.exists() or png.stat().st_size < 5000:
            raise RuntimeError(f"Render validation failed for {output}, page {page_number}: {process.stderr[-1500:]}")
        rendered.append({"page": page_number, "bytes": png.stat().st_size, "sha256": sha256(png)})
        png.unlink()
    return {
        "pages": page_count,
        "bytes": output.stat().st_size,
        "sha256": sha256(output),
        "qpdf_return_code": qpdf.returncode,
        "render_verified_pages": rendered,
    }


records = []
page_manifests = []
for report in REPORTS:
    page_directory = WORK / report["key"]
    if page_directory.exists():
        shutil.rmtree(page_directory)
    page_directory.mkdir(parents=True)
    images: list[Path] = []
    page_records = []
    for page_index in range(1, report["page_count"] + 1):
        destination = page_directory / f"{page_index:03d}.png"
        page_record = download_page(report, page_index, destination)
        images.append(destination)
        page_records.append(page_record)
        print(report["key"], page_index, page_record["width"], page_record["height"], page_record["bytes"], flush=True)
    output = REPORT_DIR / report["filename"]
    validation = build_pdf(images, output)
    record = {
        "broker": report["broker"],
        "title": report["title"],
        "report_date": report["report_date"],
        "analysts": report["analysts"],
        "rating": report["rating"],
        "source_page": report["source_page"],
        "source_form": "公开逐页预览图按原页序合成PDF",
        "source_note": report["source_note"],
        "filename": report["filename"],
        "relative_path": str(output.relative_to(ROOT)),
        **validation,
    }
    records.append(record)
    page_manifests.append({"report_key": report["key"], "pages": page_records})
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

manifest = {
    "issuer": "希迪智驾科技股份有限公司",
    "stock_code": "03881.HK",
    "package_date": "2026-09-22",
    "report_count": len(records),
    "reports": records,
    "page_sources": page_manifests,
    "important_note": "两份PDF均由公开可访问的逐页预览图按原页序合成，内容页未改写、未删减；它们不是券商原始PDF文件的字节级副本。",
}
(SOURCE_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (SOURCE_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as handle:
    writer = csv.writer(handle)
    writer.writerow(["券商", "报告日期", "报告标题", "分析师", "评级", "页数", "文件大小（字节）", "SHA-256", "来源页面", "文件名"])
    for record in records:
        writer.writerow([
            record["broker"], record["report_date"], record["title"], record["analysts"], record["rating"],
            record["pages"], record["bytes"], record["sha256"], record["source_page"], record["filename"],
        ])

readme = """希迪智驾（03881.HK）券商研究报告文件包

整理日期：2026年9月22日
报告数量：2份

收录文件
1. 国信证券：《无人驾驶矿卡领先企业，技术叠加降本推进商业化》，报告日期2026年1月15日，共70页，评级“优于大市（首次覆盖）”。
2. 东吴证券：《定位升维，从无人矿卡进化到重载具身智能》，报告日期2026年6月30日，共12页，评级“买入”。

文件性质与完整性
- 两份PDF均由公开可访问的逐页预览图按原页序合成。
- 报告内容页未改写、未删减或重新排版，但PDF并非券商原始文件的字节级副本，书签、可搜索文本层等原始PDF属性可能不保留。
- 每份PDF均完成页数核对、qpdf结构检查及首末页渲染检查。
- 逐页来源网址、图像尺寸、文件SHA-256均记录在02_来源与校验/manifest.json中。
- 报告中的评级、预测、目标价和观点属于券商在报告发布时的判断，不构成当前投资建议。
"""
(ROOT / "00_文件清单与说明.txt").write_text(readme, encoding="utf-8")

checksum_lines = []
for path in sorted(ROOT.rglob("*")):
    if path.is_file() and path.name != "SHA256SUMS.txt":
        checksum_lines.append(f"{sha256(path)}  {path.relative_to(ROOT)}")
(ROOT / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

zip_path = Path(PACKAGE + ".zip")
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, arcname=str(Path(PACKAGE) / path.relative_to(ROOT)))
with zipfile.ZipFile(zip_path, "r") as archive:
    bad_file = archive.testzip()
    if bad_file:
        raise RuntimeError(f"ZIP CRC failure: {bad_file}")
print("FINAL_ZIP", zip_path, zip_path.stat().st_size, sha256(zip_path), flush=True)
