from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

import requests
from PIL import Image
from pypdf import PdfReader

CHECKED_AS_OF = "2026-10-04"
PACKAGE = "之江生物_688317_券商深度研究资料包_2份"
ROOT = Path(PACKAGE)
COMPANY_DIR = ROOT / "01_公司研究_公开可得版"
INDUSTRY_DIR = ROOT / "02_行业深度_含之江生物专节"
VERIFY_DIR = ROOT / "03_说明与校验"
WORK_DIR = Path("_zhijiang_688317_broker_research_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (COMPANY_DIR, INDUSTRY_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_verify(path: Path) -> tuple[int, list[int]]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-2000:]}")
    reader = PdfReader(str(path), strict=False)
    page_count = len(reader.pages)
    if page_count < 1:
        raise RuntimeError(f"empty PDF: {path.name}")
    page_numbers = sorted({1, max(1, (page_count + 1) // 2), page_count})
    for page_number in page_numbers:
        prefix = RENDER_DIR / f"{path.stem}_p{page_number}"
        proc = subprocess.run(
            [
                "pdftoppm", "-f", str(page_number), "-l", str(page_number),
                "-r", "100", "-png", "-singlefile", str(path), str(prefix),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        png = Path(str(prefix) + ".png")
        if proc.returncode != 0 or not png.exists() or png.stat().st_size < 3000:
            raise RuntimeError(f"render failed for {path.name} page {page_number}: {proc.stderr[-1000:]}")
    return page_count, page_numbers


# 1) 安信证券：公开来源可直接访问的报告页面图像。
anxin_source_page = "https://www.fxbaogao.com/detail/1408531"
anxin_image_base = "https://public.fxbaogao.com/report-image/2019/09/04/1408531-{}.png"
anxin_images: list[Path] = []
for page_number in range(1, 20):
    url = anxin_image_base.format(page_number)
    response = SESSION.get(url, headers={**HEADERS, "Referer": anxin_source_page}, timeout=90)
    print("ANXIN_PAGE", page_number, response.status_code, response.headers.get("content-type"), len(response.content), flush=True)
    if response.status_code == 200 and response.content.startswith(b"\x89PNG\r\n\x1a\n") and len(response.content) > 10000:
        image_path = WORK_DIR / f"anxin_{page_number:03d}.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(response.content)
        anxin_images.append(image_path)
    elif anxin_images:
        break
    time.sleep(0.05)
if len(anxin_images) < 2:
    raise RuntimeError(f"insufficient publicly available Anxin pages: {len(anxin_images)}")

image_objects: list[Image.Image] = []
for image_path in anxin_images:
    image = Image.open(image_path)
    if image.mode != "RGB":
        image = image.convert("RGB")
    image_objects.append(image.copy())
    image.close()
anxin_pdf = COMPANY_DIR / "20190902_安信证券_之江生物_专注分子诊断领域_公开可得版.pdf"
image_objects[0].save(anxin_pdf, save_all=True, append_images=image_objects[1:], resolution=150.0)
for image in image_objects:
    image.close()
anxin_pages, anxin_rendered = render_verify(anxin_pdf)

# 2) 广证恒生：公开全文页面，保留原网页样式打印为PDF。
industry_url = "https://www.cs.com.cn/ssgs/ssb/201712/t20171206_5609538.html"
industry_pdf = INDUSTRY_DIR / "20171206_广证恒生_体外诊断百花齐放证券化趋势明显_公开全文存档版.pdf"
chrome_candidates = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]
chrome = next((shutil.which(name) for name in chrome_candidates if shutil.which(name)), None)
if chrome is None:
    raise RuntimeError("Chrome/Chromium executable not found")
command = [
    chrome,
    "--headless=new",
    "--disable-gpu",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--hide-scrollbars",
    "--virtual-time-budget=12000",
    "--print-to-pdf-no-header",
    f"--print-to-pdf={industry_pdf.resolve()}",
    industry_url,
]
print("CHROME_COMMAND", command, flush=True)
process = subprocess.run(command, capture_output=True, text=True, timeout=300)
print("CHROME_RETURN", process.returncode, process.stdout[-1000:], process.stderr[-3000:], flush=True)
if process.returncode != 0 or not industry_pdf.exists() or industry_pdf.stat().st_size < 100000:
    raise RuntimeError("failed to print the public industry report page to PDF")
industry_pages, industry_rendered = render_verify(industry_pdf)

records = [
    {
        "date": "2019-09-02",
        "broker": "安信证券",
        "author": "诸海滨",
        "title": "之江生物（834839）：专注分子诊断领域，产品被WHO批准纳入官方采购名录",
        "classification": "独立公司研究；公开可得版",
        "relative_path": str(anxin_pdf.relative_to(ROOT)),
        "pages": anxin_pages,
        "bytes": anxin_pdf.stat().st_size,
        "sha256": sha256(anxin_pdf),
        "source_page": anxin_source_page,
        "source_note": "由公开可直接访问的报告页面图像合成；公开接口返回的页数已全部收入，但不宣称与券商内部或其他渠道版本完全一致。",
        "rendered_pages": anxin_rendered,
    },
    {
        "date": "2017-12-06",
        "broker": "广证恒生",
        "author": "公开页面未列明",
        "title": "体外诊断百花齐放，证券化趋势明显",
        "classification": "行业深度报告；含之江生物专节及明确推荐；非独立公司报告",
        "relative_path": str(industry_pdf.relative_to(ROOT)),
        "pages": industry_pages,
        "bytes": industry_pdf.stat().st_size,
        "sha256": sha256(industry_pdf),
        "source_page": industry_url,
        "source_note": "由中证网公开全文页面直接打印存档，不是广证恒生原始排版PDF。",
        "rendered_pages": industry_rendered,
    },
]

manifest = {
    "package_name": PACKAGE,
    "company": "上海之江生物科技股份有限公司",
    "current_stock_code": "688317",
    "former_neeq_code": "834839",
    "checked_as_of": CHECKED_AS_OF,
    "document_count": len(records),
    "important_scope_note": "公开检索仅确认1份可直接取得页面文件的独立公司研究。为满足2份资料需求，第2份为券商行业深度报告，含之江生物专节并明确推荐，已在目录、文件名和清单中区分。",
    "records": records,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as handle:
    writer = csv.writer(handle)
    writer.writerow(["文件", "日期", "券商", "作者", "标题", "分类", "页数", "字节数", "SHA-256", "来源页面", "来源说明"])
    for record in records:
        writer.writerow([
            record["relative_path"], record["date"], record["broker"], record["author"],
            record["title"], record["classification"], record["pages"], record["bytes"],
            record["sha256"], record["source_page"], record["source_note"],
        ])

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as handle:
    for record in records:
        handle.write(f"{record['sha256']}  {record['relative_path']}\n")

readme = f"""之江生物（688317，原新三板代码834839）券商研究资料包

核对日期：{CHECKED_AS_OF}

收录内容：
1. 安信证券，2019-09-02，《之江生物（834839）：专注分子诊断领域，产品被WHO批准纳入官方采购名录》；独立公司研究，公开可得版，共{anxin_pages}页。
2. 广证恒生，2017-12-06，《体外诊断百花齐放，证券化趋势明显》；行业深度报告，含之江生物专节并明确推荐，共{industry_pages}页。

重要说明：
- 公开检索没有发现第2份可验证且可直接下载的独立公司深度原始PDF，因此没有使用网页摘要或短篇财报点评冒充公司深度报告。
- 安信证券文件由公开可直接访问的页面图像合成；已收入公开接口返回的全部页面，但无法断言与其他渠道版本页数完全一致。
- 广证恒生文件为中证网公开全文页面的打印存档版，不是券商原始排版PDF；其内容属于行业深度研究，并包含对之江生物的独立分析、估值/交易情况及明确推荐。
- 两份文件均完成PDF结构检查、页数检查、首中末页渲染检查、SHA-256校验及ZIP完整性测试。

详细来源、分类和校验值见文件清单.csv、SHA256SUMS.txt与manifest.json。
"""
(VERIFY_DIR / "README.txt").write_text(readme, encoding="utf-8")

zip_path = Path(PACKAGE + ".zip")
zip_path.unlink(missing_ok=True)
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, path.as_posix())
with zipfile.ZipFile(zip_path, "r") as archive:
    bad_member = archive.testzip()
    if bad_member:
        raise RuntimeError(f"ZIP integrity failure: {bad_member}")
    pdf_count = sum(1 for name in archive.namelist() if name.lower().endswith(".pdf"))
    if pdf_count != 2:
        raise RuntimeError(f"expected 2 PDFs, got {pdf_count}")
print("FINAL_ZIP", zip_path, zip_path.stat().st_size, sha256(zip_path), flush=True)
print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
