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

PACKAGE = "中国能源建设_中国能建_601868_券商深度报告_2份_20260927"
ROOT = Path(PACKAGE)
REPORT_DIR = ROOT / "01_券商深度报告"
META_DIR = ROOT / "02_说明与校验"
WORK = Path("_ceec_broker_2_work")
IMG_DIR = WORK / "cmb_images"
JPG_DIR = WORK / "cmb_jpg"
RENDER_DIR = WORK / "renders"
for d in (REPORT_DIR, META_DIR, IMG_DIR, JPG_DIR, RENDER_DIR):
    d.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def get(url: str, *, referer: str, stream: bool = False, timeout=(15, 180)) -> requests.Response:
    errors = []
    for attempt in range(1, 5):
        try:
            h = dict(headers)
            h["Referer"] = referer
            h["Accept"] = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8" if "file.sgpjbg.com" in url else "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8"
            r = session.get(url, headers=h, timeout=timeout, allow_redirects=True, stream=stream)
            print("GET", url, "attempt", attempt, "status", r.status_code, "type", r.headers.get("content-type"), "length", r.headers.get("content-length"), "final", r.url, flush=True)
            r.raise_for_status()
            return r
        except Exception as exc:
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(attempt * 2, 6))
    raise RuntimeError(f"request failed: {url}: {errors}")


def download_pdf(url: str, dest: Path, referer: str) -> str:
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.unlink(missing_ok=True)
    r = get(url, referer=referer, stream=True)
    try:
        with tmp.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
        final_url = str(r.url)
    finally:
        r.close()
    if tmp.stat().st_size < 100_000 or not tmp.read_bytes()[:8].startswith(b"%PDF-"):
        raise RuntimeError(f"invalid PDF download: {dest.name}, bytes={tmp.stat().st_size}")
    tmp.replace(dest)
    return final_url


def download招商_pages() -> tuple[list[Path], list[dict]]:
    referer = "https://www.sgpjbg.com/baogao/106562.html"
    root_url = "https://file.sgpjbg.com/fileroot_temp1/2022-11/17/aaac65d7-9674-4f54-879d-2cc503680168/"
    stem = "aaac65d7-9674-4f54-879d-2cc503680168"
    images = []
    metadata = []
    shutil.rmtree(IMG_DIR, ignore_errors=True)
    shutil.rmtree(JPG_DIR, ignore_errors=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    JPG_DIR.mkdir(parents=True, exist_ok=True)

    for page_no in range(1, 48):
        url = f"{root_url}{stem}{page_no}.gif"
        r = get(url, referer=referer, stream=False, timeout=(15, 120))
        try:
            data = r.content
            final_url = str(r.url)
            ctype = r.headers.get("content-type")
        finally:
            r.close()
        gif_path = IMG_DIR / f"page_{page_no:03d}.gif"
        gif_path.write_bytes(data)
        if gif_path.stat().st_size < 10_000:
            raise RuntimeError(f"unexpectedly small page image {page_no}: {gif_path.stat().st_size}")
        try:
            with Image.open(gif_path) as im:
                im.seek(0)
                width, height = im.size
                if width < 600 or height < 800:
                    raise RuntimeError(f"page {page_no} resolution too low: {width}x{height}")
                rgb = im.convert("RGB")
                jpg_path = JPG_DIR / f"page_{page_no:03d}.jpg"
                rgb.save(jpg_path, "JPEG", quality=95, subsampling=0, optimize=True)
        except Exception as exc:
            raise RuntimeError(f"invalid page image {page_no}: {exc!r}") from exc
        images.append(jpg_path)
        metadata.append({
            "page": page_no,
            "source_url": final_url,
            "content_type": ctype,
            "source_bytes": len(data),
            "width": width,
            "height": height,
            "source_sha256": sha256(gif_path),
        })
        print("PAGE_VALID", page_no, width, height, len(data), final_url, flush=True)

    expected = list(range(1, 48))
    actual = [int(p.stem.split("_")[-1]) for p in images]
    if actual != expected:
        raise RuntimeError(f"page sequence mismatch: {actual}")
    if len({m["source_sha256"] for m in metadata}) != 47:
        raise RuntimeError("duplicate page images detected")
    return images, metadata


def images_to_pdf(images: list[Path], dest: Path) -> None:
    dest.write_bytes(img2pdf.convert([str(p) for p in images]))


def validate_pdf(path: Path, *, expected_pages: int) -> dict:
    if not path.exists() or path.stat().st_size < 100_000 or not path.read_bytes()[:8].startswith(b"%PDF-"):
        raise RuntimeError(f"invalid final PDF: {path}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages != expected_pages:
        raise RuntimeError(f"wrong page count for {path.name}: expected {expected_pages}, got {pages}")
    q = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True)
    if q.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {q.stderr[-2000:]}")
    renders = []
    for page_no in (1, pages):
        prefix = RENDER_DIR / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{page_no}"
        run = subprocess.run(
            ["pdftoppm", "-f", str(page_no), "-l", str(page_no), "-r", "100", "-png", "-singlefile", str(path), str(prefix)],
            capture_output=True,
            text=True,
            timeout=240,
        )
        png = Path(str(prefix) + ".png")
        if run.returncode != 0 or not png.exists() or png.stat().st_size < 2_000:
            raise RuntimeError(f"render failed {path.name} page {page_no}: {run.stderr[-1200:]}")
        with Image.open(png) as im:
            width, height = im.size
            if width < 500 or height < 600:
                raise RuntimeError(f"render dimensions too small: {path.name} page {page_no} {width}x{height}")
        renders.append({"page": page_no, "png_bytes": png.stat().st_size, "width": width, "height": height})
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": q.returncode,
        "first_last_page_render_verified": True,
        "render_checks": renders,
    }


records = []

# 开源证券：公开发布的原始PDF文件。
kaiyuan = REPORT_DIR / "2023-07-11_开源证券_中国能建首次覆盖_能源电力建设龙头布局新能源发电.pdf"
kaiyuan_detail = "https://data.eastmoney.com/report/info/AP202307121592198509.html"
kaiyuan_file = "https://pdf.dfcfw.com/pdf/H3_AP202307121592198509_1.pdf?1689148257000.pdf="
kaiyuan_final = download_pdf(kaiyuan_file, kaiyuan, kaiyuan_detail)
kaiyuan_meta = validate_pdf(kaiyuan, expected_pages=28)
records.append({
    "relative_path": str(kaiyuan.relative_to(ROOT)),
    "broker": "开源证券",
    "report_date": "2023-07-11",
    "title": "公司首次覆盖报告：能源电力建设龙头，布局新能源发电培育全新增长极",
    "analyst": "齐东",
    "report_type": "首次覆盖/公司深度研究",
    "file_form": "公开发布的原始PDF",
    "source_detail_url": kaiyuan_detail,
    "source_file_url": kaiyuan_final,
    **kaiyuan_meta,
})

# 招商证券：由公开在线阅读的47页逐页图像按原顺序合并。
cm_pages, cm_page_meta = download招商_pages()
cm_pdf = REPORT_DIR / "2022-11-16_招商证券_中国能建首次覆盖_火然泉达风光盛满舵低碳新征程.pdf"
images_to_pdf(cm_pages, cm_pdf)
cm_meta = validate_pdf(cm_pdf, expected_pages=47)
(META_DIR / "招商证券报告_逐页来源清单.json").write_text(json.dumps(cm_page_meta, ensure_ascii=False, indent=2), encoding="utf-8")
records.append({
    "relative_path": str(cm_pdf.relative_to(ROOT)),
    "broker": "招商证券",
    "report_date": "2022-11-16",
    "title": "火然泉达风光盛，满舵低碳新征程",
    "analyst": "报告封面及正文所列招商证券研究团队",
    "report_type": "首次覆盖/公司深度报告",
    "file_form": "由公开在线阅读的完整47页逐页图像按原顺序合并为PDF；不是券商原始PDF二进制文件，未改动页面内容",
    "source_detail_url": "https://www.sgpjbg.com/baogao/106562.html",
    "source_file_url": "https://file.sgpjbg.com/fileroot_temp1/2022-11/17/aaac65d7-9674-4f54-879d-2cc503680168/aaac65d7-9674-4f54-879d-2cc503680168{page}.gif",
    **cm_meta,
})

if len(records) != 2:
    raise RuntimeError("expected exactly two reports")
if len({r["sha256"] for r in records}) != 2:
    raise RuntimeError("duplicate report hash detected")

manifest = {
    "package_name": PACKAGE,
    "issuer": "中国能源建设股份有限公司（中国能建）",
    "securities": {"A_share": "601868.SH", "H_share": "03996.HK"},
    "checked_on": "2026-09-27",
    "selection_note": "收录两份篇幅完整、可核验来源的首次覆盖/公司深度报告。未将数页的普通业绩点评或仅开放两页预览的报告混入。",
    "report_count": len(records),
    "records": records,
}
(META_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (META_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["券商", "日期", "题目", "类型", "页数", "字节数", "SHA-256", "文件形式", "来源详情页", "来源文件"])
    for r in records:
        w.writerow([r["broker"], r["report_date"], r["title"], r["report_type"], r["pages"], r["bytes"], r["sha256"], r["file_form"], r["source_detail_url"], r["source_file_url"]])

readme = [
    "中国能源建设（中国能建，601868.SH / 03996.HK）券商深度报告包",
    "",
    "核验日期：2026年9月27日",
    "",
    "收录文件：",
]
for i, r in enumerate(records, 1):
    readme.extend([
        f"{i}. {r['broker']}｜{r['report_date']}｜{r['title']}",
        f"   类型：{r['report_type']}；页数：{r['pages']}页",
        f"   文件形式：{r['file_form']}",
        f"   来源详情页：{r['source_detail_url']}",
        "",
    ])
readme.extend([
    "筛选口径：",
    "- 仅收录完整的首次覆盖或公司深度报告。",
    "- 未将3至8页的普通业绩点评混入。",
    "- 未将仅公开两页预览、无法核验完整性的2026年报告作为完整报告收录。",
    "",
    "校验：",
    "- 每份PDF均完成文件头、精确页数、qpdf结构及首末页渲染检查。",
    "- manifest.json、文件清单.csv及SHA256SUMS.txt记录来源与校验信息。",
])
(ROOT / "00_文件清单与来源说明.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")

sums = []
for p in sorted(ROOT.rglob("*")):
    if p.is_file() and p.name != "SHA256SUMS.txt":
        sums.append(f"{sha256(p)}  {p.relative_to(ROOT)}")
(META_DIR / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")

zip_path = Path(PACKAGE + ".zip")
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
    for p in sorted(ROOT.rglob("*")):
        if p.is_file():
            z.write(p, arcname=str(Path(PACKAGE) / p.relative_to(ROOT)))
with zipfile.ZipFile(zip_path, "r") as z:
    bad = z.testzip()
    if bad:
        raise RuntimeError(f"ZIP CRC failure: {bad}")
print("FINAL_ZIP", zip_path, zip_path.stat().st_size, sha256(zip_path), flush=True)
print("REPORT_RECORDS", json.dumps(records, ensure_ascii=False), flush=True)
