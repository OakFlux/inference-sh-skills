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
REPORT_DIR = ROOT / "01_券商深度报告"
SOURCE_DIR = ROOT / "02_来源与校验"
WORK = Path("_cidi_broker_work")
for d in (REPORT_DIR, SOURCE_DIR, WORK):
    d.mkdir(parents=True, exist_ok=True)

REPORTS = [
    {
        "id": "5228577",
        "date_path": "2026/01/15",
        "broker": "国信证券",
        "date": "2026-01-15",
        "title": "无人驾驶矿卡领先企业，技术叠加降本推进商业化",
        "analysts": "唐旭霞、杨钐",
        "rating": "优于大市（首次覆盖）",
        "pages": 68,
        "filename": "01_国信证券_希迪智驾_无人驾驶矿卡领先企业_技术叠加降本推进商业化_20260115_68页.pdf",
        "detail_url": "https://www.fxbaogao.com/detail/5228577",
        "notes": "海外公司深度报告；公开完整逐页预览合成PDF。",
    },
    {
        "id": "5466816",
        "date_path": "2026/06/03",
        "broker": "国盛证券",
        "date": "2026-06-03",
        "title": "深耕商用车智能驾驶，开拓无人驾驶矿卡新蓝海",
        "analysts": "丁逸朦、孙行臻、刘晓恬",
        "rating": "买入（首次覆盖）",
        "pages": 23,
        "filename": "02_国盛证券_希迪智驾_深耕商用车智能驾驶_开拓无人驾驶矿卡新蓝海_20260603_23页.pdf",
        "detail_url": "https://www.fxbaogao.com/detail/5466816",
        "notes": "公司深度报告；公开完整逐页预览合成PDF。",
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
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_page(report: dict, page_no: int, dest: Path) -> dict:
    base = f"https://public.fxbaogao.com/report-image/{report['date_path']}/{report['id']}-{page_no}.png"
    candidates = [
        base,
        base + "?x-oss-process=image/format,png",
        base + "?x-oss-process=image/format,webp",
    ]
    errors = []
    headers = dict(HEADERS)
    headers["Referer"] = report["detail_url"]
    for url in candidates:
        for attempt in range(1, 5):
            try:
                r = SESSION.get(url, headers=headers, timeout=(15, 120), allow_redirects=True)
                ctype = r.headers.get("content-type", "")
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                if len(r.content) < 5000 or not ("image" in ctype.lower() or r.content[:12].startswith((b"\x89PNG", b"RIFF", b"\xff\xd8\xff"))):
                    raise RuntimeError(f"not image: type={ctype}, bytes={len(r.content)}")
                temp = dest.with_suffix(".download")
                temp.write_bytes(r.content)
                with Image.open(temp) as im:
                    im.load()
                    width, height = im.size
                    if width < 500 or height < 700:
                        raise RuntimeError(f"image too small: {width}x{height}")
                    if im.mode not in ("RGB", "L"):
                        im = im.convert("RGB")
                    im.save(dest, format="PNG", optimize=False)
                temp.unlink(missing_ok=True)
                return {
                    "page": page_no,
                    "source_url": str(r.url),
                    "bytes": dest.stat().st_size,
                    "width": width,
                    "height": height,
                    "sha256": sha256(dest),
                }
            except Exception as exc:
                errors.append(f"{url} attempt {attempt}: {exc!r}")
                time.sleep(min(2 * attempt, 6))
                dest.with_suffix(".download").unlink(missing_ok=True)
    raise RuntimeError(f"Failed page {page_no} of report {report['id']}: {errors[-8:]}")


def make_pdf(image_paths: list[Path], output: Path) -> None:
    with output.open("wb") as f:
        f.write(img2pdf.convert([str(p) for p in image_paths]))
    if not output.read_bytes()[:8].startswith(b"%PDF-"):
        raise RuntimeError(f"Invalid PDF header: {output}")
    reader = PdfReader(str(output), strict=False)
    if len(reader.pages) != len(image_paths):
        raise RuntimeError(f"Page count mismatch: {output}: {len(reader.pages)} != {len(image_paths)}")
    q = subprocess.run(["qpdf", "--check", str(output)], capture_output=True, text=True)
    if q.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed: {output}: {q.stderr[-2000:]}")
    for pageno in (1, len(image_paths)):
        prefix = WORK / f"render_{report_id}_{pageno}"
        proc = subprocess.run(
            ["pdftoppm", "-f", str(pageno), "-l", str(pageno), "-r", "72", "-png", "-singlefile", str(output), str(prefix)],
            capture_output=True, text=True, timeout=180,
        )
        rendered = Path(str(prefix) + ".png")
        if proc.returncode != 0 or not rendered.exists() or rendered.stat().st_size < 5000:
            raise RuntimeError(f"Render check failed for {output} page {pageno}: {proc.stderr[-1000:]}")
        rendered.unlink()


records = []
all_page_records = []
for report in REPORTS:
    report_id = report["id"]
    page_dir = WORK / report_id
    if page_dir.exists():
        shutil.rmtree(page_dir)
    page_dir.mkdir(parents=True)
    images = []
    page_records = []
    for page_no in range(1, report["pages"] + 1):
        dest = page_dir / f"{page_no:03d}.png"
        rec = download_page(report, page_no, dest)
        images.append(dest)
        page_records.append(rec)
        print(report_id, page_no, rec["bytes"], rec["width"], rec["height"], flush=True)
    output = REPORT_DIR / report["filename"]
    make_pdf(images, output)
    pdf_pages = len(PdfReader(str(output), strict=False).pages)
    record = {
        "broker": report["broker"],
        "title": report["title"],
        "report_date": report["date"],
        "analysts": report["analysts"],
        "rating": report["rating"],
        "pages": pdf_pages,
        "filename": report["filename"],
        "relative_path": str(output.relative_to(ROOT)),
        "bytes": output.stat().st_size,
        "sha256": sha256(output),
        "detail_url": report["detail_url"],
        "image_url_pattern": f"https://public.fxbaogao.com/report-image/{report['date_path']}/{report['id']}-{{page}}.png",
        "source_form": "公开完整逐页预览图按原页序无删减合成PDF",
        "notes": report["notes"],
    }
    records.append(record)
    all_page_records.append({"report_id": report_id, "pages": page_records})
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

manifest = {
    "issuer": "希迪智驾科技股份有限公司",
    "stock_code": "03881.HK",
    "package_date": "2026-09-22",
    "report_count": len(records),
    "reports": records,
    "page_sources": all_page_records,
    "method": "从公开可访问的完整逐页研报预览图下载，按原页序合成为PDF；未改写、删减或重新排版报告内容。",
}
(SOURCE_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (SOURCE_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["券商", "报告日期", "报告标题", "分析师", "评级", "页数", "文件大小（字节）", "SHA-256", "来源页面", "文件名"])
    for r in records:
        w.writerow([r["broker"], r["report_date"], r["title"], r["analysts"], r["rating"], r["pages"], r["bytes"], r["sha256"], r["detail_url"], r["filename"]])

readme = f"""希迪智驾（03881.HK）券商深度报告文件包

整理日期：2026年9月22日
报告数量：{len(records)}份

收录文件：
1. 国信证券：《无人驾驶矿卡领先企业，技术叠加降本推进商业化》，2026年1月15日，68页，首次覆盖，评级“优于大市”。
2. 国盛证券：《深耕商用车智能驾驶，开拓无人驾驶矿卡新蓝海》，2026年6月3日，23页，首次覆盖，评级“买入”。

文件说明：
- 两份报告均由公开可访问的完整逐页预览图按原页序合成为PDF。
- 未删减、改写或重新排版报告正文；PDF为方便离线阅读而制作。
- 每份文件的来源、页数、大小与SHA-256见manifest.json及文件清单.csv。
- 报告中的观点、预测、目标价和评级均属于券商在报告发布时的判断，不构成当前投资建议。
"""
(ROOT / "00_文件清单与说明.txt").write_text(readme, encoding="utf-8")

sum_lines = []
for p in sorted(ROOT.rglob("*")):
    if p.is_file() and p.name != "SHA256SUMS.txt":
        sum_lines.append(f"{sha256(p)}  {p.relative_to(ROOT)}")
(ROOT / "SHA256SUMS.txt").write_text("\n".join(sum_lines) + "\n", encoding="utf-8")

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
