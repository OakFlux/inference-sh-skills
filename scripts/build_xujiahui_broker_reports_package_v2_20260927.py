from __future__ import annotations

import csv
import hashlib
import json
import re
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

PACKAGE = "徐家汇_002561_券商研究报告精选_3份"
ROOT = Path(PACKAGE)
REPORT_DIR = ROOT / "01_券商研究报告"
VERIFY_DIR = ROOT / "02_来源与校验"
WORK = Path("_xujiahui_broker_v2_work")
RENDER_DIR = WORK / "renders"
for directory in (REPORT_DIR, VERIFY_DIR, WORK, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

REPORTS: list[dict[str, Any]] = [
    {
        "id": "929115",
        "date_path": "2015/08/20",
        "date": "2015-08-20",
        "broker": "中泰证券",
        "authors": ["胡彦超"],
        "type": "公司深度研究",
        "title": "优质商圈+高盈利能力+高分红",
        "pages": 15,
        "mode": "preview_images",
        "detail_url": "https://www.fxbaogao.com/detail/929115",
        "filename": "2015-08-20_中泰证券_徐家汇深度研究_优质商圈高盈利能力高分红_15页.pdf",
    },
    {
        "id": "89805",
        "date_path": "2016/12/19",
        "date": "2016-12-19",
        "broker": "民生证券",
        "authors": ["马科", "赵令伊", "李奇琦"],
        "type": "调研简报",
        "title": "主业经营稳健，持续深化全渠道布局",
        "pages": 4,
        "mode": "preview_images",
        "detail_url": "https://www.fxbaogao.com/detail/89805",
        "filename": "2016-12-19_民生证券_徐家汇调研简报_主业经营稳健持续深化全渠道布局_4页.pdf",
    },
    {
        "id": "AP201704010460545465",
        "date": "2017-03-31",
        "broker": "民生证券",
        "authors": ["马科", "赵令伊", "李奇琦"],
        "type": "年度报告点评",
        "title": "经营稳健，加速推进全渠道融合",
        "pages": 5,
        "mode": "direct_pdf",
        "url": "https://pdf.dfcfw.com/pdf/H3_AP201704010460545465_1.pdf",
        "detail_url": "https://data.eastmoney.com/report/info/AP201704010460545465.html",
        "filename": "2017-03-31_民生证券_徐家汇年报点评_经营稳健加速推进全渠道融合_5页.pdf",
    },
]

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def get_bytes(url: str, *, referer: str, accept: str, min_bytes: int, attempts: int = 5) -> tuple[bytes, str, str]:
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        headers = dict(HEADERS)
        headers["Referer"] = referer
        headers["Accept"] = accept
        try:
            response = SESSION.get(url, headers=headers, timeout=(20, 180), allow_redirects=True)
            content = response.content
            content_type = response.headers.get("content-type", "")
            print(
                "GET", url, "attempt", attempt, "status", response.status_code,
                "type", content_type, "bytes", len(content), "final", response.url,
                flush=True,
            )
            response.raise_for_status()
            if len(content) < min_bytes:
                raise RuntimeError(f"too small: {len(content)} bytes")
            return content, str(response.url), content_type
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(2 * attempt, 8))
    raise RuntimeError(f"download failed for {url}: {errors[-attempts:]}")


def download_preview_page(report: dict[str, Any], page_no: int, destination: Path) -> dict[str, Any]:
    base = f"https://public.fxbaogao.com/report-image/{report['date_path']}/{report['id']}-{page_no}.png"
    candidates = [
        base,
        base + "?x-oss-process=image/format,png",
        base + "?x-oss-process=image/format,webp",
    ]
    errors: list[str] = []
    for url in candidates:
        try:
            content, final_url, content_type = get_bytes(
                url,
                referer=report["detail_url"],
                accept="image/avif,image/webp,image/apng,image/png,image/*,*/*;q=0.8",
                min_bytes=5_000,
                attempts=3,
            )
            temp = destination.with_suffix(".download")
            temp.write_bytes(content)
            with Image.open(temp) as image:
                image.load()
                width, height = image.size
                if width < 500 or height < 700:
                    raise RuntimeError(f"unexpected image dimensions: {width}x{height}")
                output_image = image.convert("RGB") if image.mode not in ("RGB", "L") else image.copy()
                output_image.save(destination, format="PNG", optimize=False)
            temp.unlink(missing_ok=True)
            return {
                "page": page_no,
                "source_url": final_url,
                "content_type": content_type,
                "bytes": destination.stat().st_size,
                "width": width,
                "height": height,
                "sha256": sha256(destination),
            }
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc!r}")
            destination.with_suffix(".download").unlink(missing_ok=True)
    raise RuntimeError(f"failed page {page_no} for report {report['id']}: {errors[-6:]}")


def make_pdf_from_images(images: list[Path], output: Path) -> None:
    with output.open("wb") as fh:
        fh.write(img2pdf.convert([str(image) for image in images]))
    if output.read_bytes()[:8] != b"%PDF-1.4" and not output.read_bytes()[:8].startswith(b"%PDF-"):
        raise RuntimeError(f"invalid assembled PDF header: {output}")


def download_direct_pdf(report: dict[str, Any], output: Path) -> str:
    content, final_url, _ = get_bytes(
        report["url"],
        referer="https://data.eastmoney.com/report/002561.html",
        accept="application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
        min_bytes=50_000,
        attempts=5,
    )
    if not content.startswith(b"%PDF-"):
        raise RuntimeError(f"direct source is not a PDF: {report['url']}")
    output.write_bytes(content)
    return final_url


def render_check(path: Path, page: int, tag: str) -> None:
    prefix = RENDER_DIR / f"{path.stem}_{tag}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page), "-l", str(page), "-r", "100",
            "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    rendered = Path(str(prefix) + ".png")
    if (
        process.returncode != 0
        or not rendered.exists()
        or rendered.stat().st_size < 2_000
        or rendered.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n"
    ):
        raise RuntimeError(f"render check failed for {path.name} page {page}: {process.stderr[-1000:]}")
    rendered.unlink()


def validate_pdf(path: Path, expected_pages: int, mode: str) -> dict[str, Any]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=240)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-2000:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages != expected_pages:
        raise RuntimeError(f"page count mismatch for {path.name}: {pages} != {expected_pages}")
    render_check(path, 1, "first")
    render_check(path, pages, "last")

    text = ""
    if mode == "direct_pdf":
        text = "\n".join((reader.pages[index].extract_text() or "") for index in range(min(pages, 5)))
        normalized = re.sub(r"\s+", "", text)
        if text.strip() and not ("徐家汇" in normalized or "002561" in normalized):
            raise RuntimeError(f"issuer identity check failed for {path.name}")
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "render_verified_first_and_last_page": True,
        "sample_text_extractable": bool(text.strip()),
        "issuer_identity_verified_when_text_extractable": bool(text.strip()),
    }


records: list[dict[str, Any]] = []
page_source_records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()
for report in REPORTS:
    output = REPORT_DIR / report["filename"]
    if report["mode"] == "preview_images":
        page_dir = WORK / report["id"]
        if page_dir.exists():
            shutil.rmtree(page_dir)
        page_dir.mkdir(parents=True)
        images: list[Path] = []
        sources: list[dict[str, Any]] = []
        for page_no in range(1, report["pages"] + 1):
            image_path = page_dir / f"{page_no:03d}.png"
            source_record = download_preview_page(report, page_no, image_path)
            images.append(image_path)
            sources.append(source_record)
            print("PAGE_OK", report["id"], page_no, source_record["width"], source_record["height"], flush=True)
        make_pdf_from_images(images, output)
        final_source = report["detail_url"]
        source_form = "公开完整逐页预览图按原页序无删减合成PDF"
        page_source_records.append({"report_id": report["id"], "pages": sources})
    else:
        final_source = download_direct_pdf(report, output)
        source_form = "公开原始PDF"

    metadata = validate_pdf(output, report["pages"], report["mode"])
    if metadata["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate PDF detected: {output.name}")
    seen_hashes.add(metadata["sha256"])
    record = {
        "report_id": report["id"],
        "date": report["date"],
        "broker": report["broker"],
        "authors": report["authors"],
        "report_type": report["type"],
        "title": report["title"],
        "stock": "徐家汇（002561）",
        "relative_path": str(output.relative_to(ROOT)),
        "detail_url": report["detail_url"],
        "source_url": final_source,
        "source_form": source_form,
        **metadata,
    }
    records.append(record)
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

manifest = {
    "issuer": "上海徐家汇商城股份有限公司",
    "stock_code": "002561",
    "checked_as_of": "2026-09-27",
    "report_count": len(records),
    "reports": records,
    "page_sources": page_source_records,
    "method_note": "2015、2016年报告由公开完整逐页预览按原页序无删减合成PDF；2017年报告为公开原始PDF。",
}
(VERIFY_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as fh:
    writer = csv.writer(fh)
    writer.writerow(["日期", "券商", "类型", "标题", "分析师", "页数", "来源形式", "SHA-256", "文件"])
    for record in records:
        writer.writerow([
            record["date"], record["broker"], record["report_type"], record["title"],
            "、".join(record["authors"]), record["pages"], record["source_form"],
            record["sha256"], record["relative_path"],
        ])

readme = """徐家汇（002561）券商研究报告精选

核对日期：2026年9月27日

收录报告：
1. 2015-08-20，中泰证券，公司深度研究，《优质商圈+高盈利能力+高分红》，15页；
2. 2016-12-19，民生证券，调研简报，《主业经营稳健，持续深化全渠道布局》，4页；
3. 2017-03-31，民生证券，年度报告点评，《经营稳健，加速推进全渠道融合》，5页。

文件来源：
- 2015、2016年报告的原始直链PDF已失效，但公开档案仍提供全部逐页预览；本包按原页序无删减合成为PDF，未改写或重新排版内容。
- 2017年报告使用东方财富公开原始PDF。

校验：
- 每份PDF均通过qpdf结构检查和页数核对；
- 每份PDF的第一页、最后一页均实际渲染验证；
- 所有文件均计算SHA-256并进行去重；
- ZIP已执行CRC完整性检查。
"""
(VERIFY_DIR / "README.txt").write_text(readme, encoding="utf-8")

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as fh:
    for record in records:
        fh.write(f"{record['sha256']}  {record['relative_path']}\n")

zip_path = Path(PACKAGE + ".zip")
zip_path.unlink(missing_ok=True)
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, str(Path(PACKAGE) / path.relative_to(ROOT)))
with zipfile.ZipFile(zip_path, "r") as archive:
    bad = archive.testzip()
    if bad:
        raise RuntimeError(f"ZIP CRC failure: {bad}")
    pdf_count = sum(1 for name in archive.namelist() if name.lower().endswith(".pdf"))
    if pdf_count != 3:
        raise RuntimeError(f"ZIP PDF count mismatch: {pdf_count}")
print("FINAL_ZIP", zip_path, zip_path.stat().st_size, sha256(zip_path), flush=True)
