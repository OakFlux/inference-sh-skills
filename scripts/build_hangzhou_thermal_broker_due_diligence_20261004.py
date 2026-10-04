from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import time
import zipfile
from pathlib import Path

import requests
from pypdf import PdfReader

COMPANY = "杭州热电"
FULL_COMPANY = "杭州热电集团股份有限公司"
CODE = "605011"
AS_OF = "2026-10-04"

ROOT = Path(f"{COMPANY}_{CODE}_平安证券尽调与核查材料_3份")
REPORT_DIR = ROOT / "01_平安证券尽调与核查材料"
VERIFY_DIR = Path("_verify_hangzhou_thermal_broker_docs")
ZIP_NAME = f"{COMPANY}_{CODE}_平安证券尽调与核查材料_3份_20261004.zip"

for directory in (REPORT_DIR, VERIFY_DIR):
    directory.mkdir(parents=True, exist_ok=True)

DOCUMENTS = [
    {
        "date": "2024-04-23",
        "title": "平安证券股份有限公司关于杭州热电集团股份有限公司首次公开发行股票并上市持续督导保荐总结报告书",
        "filename": "20240423_平安证券_首次公开发行股票并上市持续督导保荐总结报告书.pdf",
        "url": "https://static.cninfo.com.cn/finalpage/2024-04-23/1219736235.PDF",
        "announcement_id": "1219736235",
        "category": "保荐总结报告",
        "selection_note": "总结上市后持续督导期间的公司治理、信息披露、募集资金和经营变化，适合作为整体尽调补充材料。",
    },
    {
        "date": "2025-04-19",
        "title": "平安证券股份有限公司关于杭州热电集团股份有限公司部分募集资金投资项目重新论证并暂缓实施的核查意见",
        "filename": "20250419_平安证券_部分募投项目重新论证并暂缓实施的核查意见.pdf",
        "url": "https://static.cninfo.com.cn/finalpage/2025-04-19/1223155120.PDF",
        "announcement_id": "1223155120",
        "category": "募投项目核查意见",
        "selection_note": "分析部分募投项目重新论证与暂缓实施的原因、项目进度、资金安排和风险。",
    },
    {
        "date": "2025-09-18",
        "title": "平安证券股份有限公司关于杭州热电集团股份有限公司变更部分募投项目暨向控股子公司实缴注册资本以实施募投项目的核查意见",
        "filename": "20250918_平安证券_变更部分募投项目暨向控股子公司实缴注册资本的核查意见.pdf",
        "url": "https://static.cninfo.com.cn/finalpage/2025-09-18/1224667014.PDF",
        "announcement_id": "1224667014",
        "category": "募投项目变更核查意见",
        "selection_note": "覆盖较新的资本配置和项目调整事项，有助于理解公司当前投资方向和项目执行变化。",
    },
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Referer": "https://www.cninfo.com.cn/",
    "Accept": "application/pdf,application/octet-stream,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str) -> bytes:
    last_error = None
    for attempt in range(1, 6):
        try:
            response = session.get(url, timeout=(20, 180), allow_redirects=True)
            print("HTTP", attempt, response.status_code, response.headers.get("content-type"), len(response.content), response.url, flush=True)
            if response.status_code in {429, 500, 502, 503, 504}:
                time.sleep(attempt * 2)
                continue
            response.raise_for_status()
            if not response.content.startswith(b"%PDF"):
                raise RuntimeError(f"Not a PDF: {url}; header={response.content[:20]!r}")
            return response.content
        except Exception as exc:
            last_error = exc
            time.sleep(attempt * 2)
    raise RuntimeError(f"Download failed: {url}: {last_error}")


def validate_pdf(path: Path) -> dict:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 2:
        raise RuntimeError(f"Suspicious page count for {path.name}: {pages}")

    text_parts = []
    for index in sorted(set([0, 1, max(0, pages - 1)])):
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception:
            pass
    sample_text = "\n".join(text_parts)
    identity_ok = any(term in sample_text for term in ("杭州热电", "605011", "平安证券"))
    if len(sample_text.strip()) > 200 and not identity_ok:
        raise RuntimeError(f"Identity terms not found in {path.name}")

    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=120)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {qpdf.stdout}\n{qpdf.stderr}")

    for label, page_number in (("first", 1), ("last", pages)):
        out_base = VERIFY_DIR / f"{path.stem}_{label}"
        result = subprocess.run(
            ["pdftoppm", "-png", "-r", "100", "-f", str(page_number), "-l", str(page_number), "-singlefile", str(path), str(out_base)],
            capture_output=True,
            text=True,
            timeout=180,
        )
        png = Path(str(out_base) + ".png")
        if result.returncode != 0 or not png.exists() or png.stat().st_size < 1000:
            raise RuntimeError(f"Render failed for {path.name} page {page_number}: {result.stderr}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "first_last_page_rendered": True,
        "identity_text_verified_when_extractable": bool(identity_ok or len(sample_text.strip()) <= 200),
    }


records = []
for item in DOCUMENTS:
    destination = REPORT_DIR / item["filename"]
    destination.write_bytes(download(item["url"]))
    validation = validate_pdf(destination)
    record = {
        "relative_path": destination.relative_to(ROOT).as_posix(),
        "filename": destination.name,
        "company": FULL_COMPANY,
        "stock_code": CODE,
        "publish_date": item["date"],
        "institution": "平安证券",
        "title": item["title"],
        "document_category": item["category"],
        "source": "巨潮资讯网官方披露PDF",
        "source_url": item["url"],
        "announcement_id": item["announcement_id"],
        "selection_note": item["selection_note"],
        **validation,
    }
    records.append(record)
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

if len(records) != 3:
    raise RuntimeError("Expected exactly three documents")

readme = f"""{FULL_COMPANY}（{CODE}）平安证券尽调与核查材料包

资料截止日期：{AS_OF}

重要说明：
1. 经东方财富研报数据库按证券代码、申购代码、公司名称以及IPO前后时间段回溯，未检索到可公开下载的杭州热电公司级卖方深度覆盖报告或首次覆盖评级报告。
2. 为避免将AI分析、普通财经文章、财务分析模板或公司公告冒充券商研报，本包不使用上述材料凑数。
3. 本包改为收录3份由杭州热电保荐机构平安证券出具、并由巨潮资讯网正式披露的尽调/核查材料。它们属于保荐与专项核查文件，不属于卖方研究评级报告。
4. 三份材料分别覆盖持续督导总结、募投项目重新论证及暂缓实施、募投项目变更与资本安排，适合用于公司项目与资本配置研究。

文件来源：巨潮资讯网官方披露PDF。
文件校验：PDF文件头、实际页数、qpdf结构、公司/机构身份文本（可提取时）、首页和末页渲染、SHA-256及ZIP CRC。
"""
(ROOT / "00_重要说明与文件清单.txt").write_text(readme, encoding="utf-8")

with (ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    fields = [
        "relative_path", "title", "document_category", "publish_date", "institution",
        "pages", "bytes", "sha256", "source", "source_url", "announcement_id", "selection_note"
    ]
    writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(records)

manifest = {
    "company": FULL_COMPANY,
    "stock_code": CODE,
    "as_of": AS_OF,
    "package_type": "公开卖方深度报告缺失时的券商尽调/核查替代材料",
    "not_sell_side_research": True,
    "documents": records,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
(ROOT / "SHA256SUMS.txt").write_text(
    "\n".join(f"{record['sha256']}  {record['relative_path']}" for record in records) + "\n",
    encoding="utf-8",
)

zip_path = Path(ZIP_NAME)
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, arcname=f"{ROOT.name}/{path.relative_to(ROOT).as_posix()}")

with zipfile.ZipFile(zip_path, "r") as archive:
    bad = archive.testzip()
    if bad:
        raise RuntimeError(f"ZIP CRC failure: {bad}")
    pdf_count = sum(name.lower().endswith(".pdf") for name in archive.namelist())
    if pdf_count != 3:
        raise RuntimeError(f"ZIP PDF count mismatch: {pdf_count}")

print("FINAL_ZIP", zip_path.name, zip_path.stat().st_size, sha256_file(zip_path), flush=True)
print("FINAL_RECORDS", json.dumps(records, ensure_ascii=False), flush=True)
