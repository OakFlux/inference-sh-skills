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
from urllib.parse import urljoin

import img2pdf
import requests
from bs4 import BeautifulSoup
from PIL import Image
from pypdf import PdfReader

PACKAGE = "中国能源建设_中国能建_601868_券商深度报告_3份_20260927"
ROOT = Path(PACKAGE)
REPORT_DIR = ROOT / "01_券商深度报告"
NOTE_DIR = ROOT / "02_说明与校验"
WORK = Path("_ceec_broker_work")
PAGE_DIR = WORK / "pages"
RENDER_DIR = WORK / "renders"
for d in (REPORT_DIR, NOTE_DIR, PAGE_DIR, RENDER_DIR):
    d.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def request(url: str, *, referer: str | None = None, stream: bool = False, timeout=(15, 180)) -> requests.Response:
    errors = []
    candidates = [url]
    if "pdf.dfcfw.com" in url and url.startswith("https://"):
        candidates.append(url.replace("https://", "http://", 1))
    for candidate in dict.fromkeys(candidates):
        for attempt in range(1, 5):
            try:
                headers = dict(BASE_HEADERS)
                headers["Accept"] = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8" if "report-image" in candidate else "application/pdf,text/html,application/xhtml+xml,application/octet-stream;q=0.9,*/*;q=0.8"
                if referer:
                    headers["Referer"] = referer
                r = SESSION.get(candidate, headers=headers, timeout=timeout, allow_redirects=True, stream=stream)
                print("GET", candidate, "attempt", attempt, "status", r.status_code, "type", r.headers.get("content-type"), "length", r.headers.get("content-length"), "final", r.url, flush=True)
                if r.status_code == 404:
                    return r
                r.raise_for_status()
                return r
            except Exception as exc:
                errors.append(f"{candidate} attempt {attempt}: {exc!r}")
                time.sleep(min(attempt * 2, 6))
    raise RuntimeError(f"request failed for {url}: {errors[-8:]}")


def download_pdf(url: str, dest: Path, referer: str, min_bytes: int = 100_000) -> str:
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.unlink(missing_ok=True)
    r = request(url, referer=referer, stream=True)
    try:
        with tmp.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
        final_url = str(r.url)
    finally:
        r.close()
    if tmp.stat().st_size < min_bytes or not tmp.read_bytes()[:8].startswith(b"%PDF-"):
        raise RuntimeError(f"invalid downloaded PDF: {dest.name}, bytes={tmp.stat().st_size}")
    tmp.replace(dest)
    return final_url


def valid_image_bytes(data: bytes) -> tuple[bool, str]:
    if len(data) < 5_000:
        return False, "too small"
    temp = WORK / "_probe_image"
    temp.write_bytes(data)
    try:
        with Image.open(temp) as im:
            im.verify()
            return True, im.format or "unknown"
    except Exception as exc:
        return False, repr(exc)
    finally:
        temp.unlink(missing_ok=True)


def discover_cover_url(detail_url: str, report_id: int) -> tuple[str | None, str]:
    r = request(detail_url, referer="https://www.fxbaogao.com/", stream=False, timeout=(15, 90))
    try:
        html = r.text
        final_url = str(r.url)
    finally:
        r.close()
    patterns = [
        rf"https?://public\.fxbaogao\.com/report-image/\d{{4}}/\d{{2}}/\d{{2}}/{report_id}-1\.(?:png|jpg|jpeg|webp)",
        rf"//public\.fxbaogao\.com/report-image/\d{{4}}/\d{{2}}/\d{{2}}/{report_id}-1\.(?:png|jpg|jpeg|webp)",
        rf"/report-image/\d{{4}}/\d{{2}}/\d{{2}}/{report_id}-1\.(?:png|jpg|jpeg|webp)",
    ]
    for pattern in patterns:
        m = re.search(pattern, html, re.I)
        if m:
            found = m.group(0)
            if found.startswith("//"):
                found = "https:" + found
            elif found.startswith("/"):
                found = urljoin("https://public.fxbaogao.com", found)
            return found, final_url
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["img", "a"]):
        val = tag.get("src") or tag.get("href") or ""
        if str(report_id) in val and "report-image" in val:
            return urljoin(final_url, val), final_url
    return None, final_url


def download_fxbaogao_pages(*, report_id: int, detail_url: str, date_paths: list[str], min_pages: int) -> tuple[list[Path], str, str]:
    cover, resolved_detail = discover_cover_url(detail_url, report_id)
    bases: list[str] = []
    if cover:
        # remove page number and extension; page URL will be rebuilt below
        m = re.match(r"(.*/)(\d+)-1\.(png|jpg|jpeg|webp)", cover, re.I)
        if m:
            bases.append(m.group(1) + m.group(2))
    for date_path in date_paths:
        bases.append(f"https://public.fxbaogao.com/report-image/{date_path}/{report_id}")
    bases = list(dict.fromkeys(bases))

    last_errors: list[str] = []
    for base in bases:
        report_page_dir = PAGE_DIR / str(report_id)
        shutil.rmtree(report_page_dir, ignore_errors=True)
        report_page_dir.mkdir(parents=True, exist_ok=True)
        pages: list[Path] = []
        format_used = ""
        for page_no in range(1, 81):
            found = False
            for ext in ("png", "jpg", "jpeg", "webp"):
                url = f"{base}-{page_no}.{ext}"
                try:
                    r = request(url, referer=detail_url, stream=False, timeout=(10, 90))
                    try:
                        if r.status_code == 404:
                            continue
                        data = r.content
                        final_url = str(r.url)
                    finally:
                        r.close()
                    ok, image_format = valid_image_bytes(data)
                    if not ok:
                        last_errors.append(f"{url}: invalid image {image_format}")
                        continue
                    suffix = "." + ("jpg" if image_format.upper() in {"JPEG", "JPG"} else image_format.lower())
                    path = report_page_dir / f"page_{page_no:03d}{suffix}"
                    path.write_bytes(data)
                    pages.append(path)
                    format_used = image_format
                    print("PAGE_OK", report_id, page_no, final_url, image_format, len(data), flush=True)
                    found = True
                    break
                except Exception as exc:
                    last_errors.append(f"{url}: {exc!r}")
            if not found:
                if page_no == 1:
                    pages = []
                    break
                # Full public previews are contiguous. First missing page marks the end.
                print("PAGE_END", report_id, "after", len(pages), "pages", flush=True)
                break
        if len(pages) >= min_pages:
            expected = list(range(1, len(pages) + 1))
            actual = [int(re.search(r"(\d{3})", p.name).group(1)) for p in pages]
            if actual != expected:
                raise RuntimeError(f"non-contiguous page sequence for {report_id}: {actual}")
            return pages, base, resolved_detail
    raise RuntimeError(f"could not retrieve at least {min_pages} pages for report {report_id}; errors={last_errors[-12:]}")


def pages_to_pdf(pages: list[Path], dest: Path) -> None:
    normalized_dir = WORK / (dest.stem + "_jpg")
    shutil.rmtree(normalized_dir, ignore_errors=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)
    normalized: list[Path] = []
    for idx, page in enumerate(pages, start=1):
        out = normalized_dir / f"page_{idx:03d}.jpg"
        with Image.open(page) as im:
            rgb = im.convert("RGB")
            rgb.save(out, "JPEG", quality=95, subsampling=0, optimize=True)
        normalized.append(out)
    pdf_bytes = img2pdf.convert([str(p) for p in normalized])
    dest.write_bytes(pdf_bytes)


def validate_pdf(path: Path, min_pages: int) -> dict:
    if not path.exists() or path.stat().st_size < 50_000 or not path.read_bytes()[:8].startswith(b"%PDF-"):
        raise RuntimeError(f"invalid PDF file {path}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"report too short {path.name}: {pages} pages")
    q = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True)
    if q.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {q.stderr[-1500:]}")
    for page_no in sorted(set([1, pages])):
        prefix = RENDER_DIR / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{page_no}"
        run = subprocess.run(
            ["pdftoppm", "-f", str(page_no), "-l", str(page_no), "-r", "72", "-png", "-singlefile", str(path), str(prefix)],
            capture_output=True, text=True, timeout=180,
        )
        png = Path(str(prefix) + ".png")
        if run.returncode != 0 or not png.exists() or png.stat().st_size < 1_000:
            raise RuntimeError(f"render failed {path.name} page {page_no}: {run.stderr[-1000:]}")
        png.unlink()
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": q.returncode,
        "first_last_page_render_verified": True,
    }


records: list[dict] = []

# 1. Original PDF published through Eastmoney's PDF host.
kaiyuan_path = REPORT_DIR / "2023-07-11_开源证券_中国能建首次覆盖_能源电力建设龙头布局新能源发电.pdf"
kaiyuan_source = download_pdf(
    "https://pdf.dfcfw.com/pdf/H3_AP202307121592198509_1.pdf?1689148257000.pdf=",
    kaiyuan_path,
    referer="https://data.eastmoney.com/report/info/AP202307121592198509.html",
)
kaiyuan_meta = validate_pdf(kaiyuan_path, min_pages=20)
records.append({
    "filename": kaiyuan_path.name,
    "relative_path": str(kaiyuan_path.relative_to(ROOT)),
    "broker": "开源证券",
    "report_date": "2023-07-11",
    "title": "公司首次覆盖报告：能源电力建设龙头，布局新能源发电培育全新增长极",
    "report_type": "首次覆盖/深度公司研究",
    "source_detail_url": "https://data.eastmoney.com/report/info/AP202307121592198509.html",
    "source_file_url": kaiyuan_source,
    "file_form": "公开发布的原始PDF",
    "analyst": "齐东",
    **kaiyuan_meta,
})

# 2. Full report reconstructed from the public, sequential full-page preview images.
gth_pages, gth_base, gth_detail = download_fxbaogao_pages(
    report_id=5289222,
    detail_url="https://www.fxbaogao.com/detail/5289222",
    date_paths=["2026/03/08", "2026/03/09"],
    min_pages=25,
)
gth_path = REPORT_DIR / "2026-03-08_国泰海通证券_中国能建_发挥算电协同优势建设东数西算.pdf"
pages_to_pdf(gth_pages, gth_path)
gth_meta = validate_pdf(gth_path, min_pages=25)
records.append({
    "filename": gth_path.name,
    "relative_path": str(gth_path.relative_to(ROOT)),
    "broker": "国泰海通证券",
    "report_date": "2026-03-08",
    "title": "发挥算电协同优势建设东数西算，投建绿电氢氨醇和绿色燃料",
    "report_type": "公司深度研究",
    "source_detail_url": gth_detail,
    "source_file_url": gth_base + "-{page}.png",
    "file_form": "由公开完整逐页预览图按原顺序无删减合成为PDF；非券商原始PDF二进制文件",
    "analyst": "欧阳晓辉",
    **gth_meta,
})

# 3. Full report reconstructed from the public, sequential full-page preview images.
dfcf_pages, dfcf_base, dfcf_detail = download_fxbaogao_pages(
    report_id=5245393,
    detail_url="https://www.fxbaogao.com/detail/5245393",
    date_paths=["2026/01/28", "2026/01/27", "2026/01/29"],
    min_pages=20,
)
dfcf_path = REPORT_DIR / "2026-01-28_东方财富证券_中国能建深度研究_四新转型求变.pdf"
pages_to_pdf(dfcf_pages, dfcf_path)
dfcf_meta = validate_pdf(dfcf_path, min_pages=20)
records.append({
    "filename": dfcf_path.name,
    "relative_path": str(dfcf_path.relative_to(ROOT)),
    "broker": "东方财富证券",
    "report_date": "2026-01-28",
    "title": "深度研究：“四新”转型求变，积极布局新型能源体系建设",
    "report_type": "公司深度研究",
    "source_detail_url": dfcf_detail,
    "source_file_url": dfcf_base + "-{page}.png",
    "file_form": "由公开完整逐页预览图按原顺序无删减合成为PDF；非券商原始PDF二进制文件",
    "analyst": "王翩翩、郁晾、闫广",
    **dfcf_meta,
})

if len(records) != 3:
    raise RuntimeError(f"expected 3 reports, got {len(records)}")
if len({r["sha256"] for r in records}) != 3:
    raise RuntimeError("duplicate report PDF detected")

manifest = {
    "package": PACKAGE,
    "issuer": "中国能源建设股份有限公司（中国能建）",
    "securities": {"A_share": "601868.SH", "H_share": "03996.HK"},
    "checked_on": "2026-09-27",
    "report_count": len(records),
    "scope_note": "优先收录完整的公司深度或首次覆盖报告，未将3—5页普通业绩点评作为深度报告混入。",
    "records": records,
}
(NOTE_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (NOTE_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["券商", "报告日期", "报告题目", "报告类型", "页数", "字节数", "SHA-256", "文件形式", "来源详情页", "来源文件"])
    for r in records:
        w.writerow([r["broker"], r["report_date"], r["title"], r["report_type"], r["pages"], r["bytes"], r["sha256"], r["file_form"], r["source_detail_url"], r["source_file_url"]])

readme_lines = [
    "中国能源建设（中国能建，601868.SH / 03996.HK）券商深度报告包",
    "",
    "核验日期：2026年9月27日",
    "",
    "收录原则：仅选择篇幅和内容达到公司深度/首次覆盖标准的报告；未将数页的普通业绩点评混入。",
    "",
]
for idx, r in enumerate(records, start=1):
    readme_lines.extend([
        f"{idx}. {r['broker']}｜{r['report_date']}｜{r['title']}",
        f"   页数：{r['pages']}页",
        f"   文件形式：{r['file_form']}",
        f"   来源详情页：{r['source_detail_url']}",
        "",
    ])
readme_lines.extend([
    "校验说明：",
    "- 每份PDF均完成文件头、页数、qpdf结构和首末页渲染检查。",
    "- manifest.json及文件清单.csv记录来源、页数、大小与SHA-256。",
    "- 对逐页预览图重建的PDF，仅进行了格式转换与顺序合并，未修改报告内容。",
])
(ROOT / "00_文件清单与来源说明.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

sums: list[str] = []
for path in sorted(ROOT.rglob("*")):
    if path.is_file() and path.name != "SHA256SUMS.txt":
        sums.append(f"{sha256(path)}  {path.relative_to(ROOT)}")
(NOTE_DIR / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")

zip_path = Path(PACKAGE + ".zip")
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            z.write(path, arcname=str(Path(PACKAGE) / path.relative_to(ROOT)))
with zipfile.ZipFile(zip_path, "r") as z:
    bad = z.testzip()
    if bad:
        raise RuntimeError(f"ZIP CRC failure: {bad}")
print("FINAL_ZIP", zip_path, zip_path.stat().st_size, sha256(zip_path), flush=True)
print("REPORTS", json.dumps(records, ensure_ascii=False), flush=True)
