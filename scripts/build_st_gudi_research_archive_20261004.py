from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

COMPANY = "顾地科技"
CURRENT_NAME = "*ST顾地"
CODE = "002694"
AS_OF = "2026-10-04"
ROOT = Path("ST顾地_002694_券商研究资料_1份全文_1份索引")
FULL_DIR = ROOT / "01_完整券商报告"
INDEX_DIR = ROOT / "02_历史报告索引_非全文"
VERIFY_DIR = Path("_verify_st_gudi_research_archive")
ZIP_NAME = "ST顾地_002694_券商研究资料_1份全文_1份索引_20261004.zip"

for directory in (FULL_DIR, INDEX_DIR, VERIFY_DIR):
    directory.mkdir(parents=True, exist_ok=True)

FULL_REPORT = {
    "publish_date": "2012-08-06",
    "institution": "国都证券",
    "analyst": "王双",
    "title": "国内大型综合塑料管道供应商",
    "info_code": "AP201208060005410276",
    "detail_url": "https://data.eastmoney.com/report/info/AP201208060005410276.html",
    "pdf_url": "https://pdf.dfcfw.com/pdf/H3_AP201208060005410276_1.pdf",
    "filename": "20120806_国都证券_国内大型综合塑料管道供应商_完整报告.pdf",
    "category": "新股研究/公司研究",
}

INDEX_REPORT = {
    "publish_date": "2012-10-26",
    "institution": "国海证券",
    "analyst": "代鹏举",
    "title": "布局完善，渠道稳固",
    "info_code": "AP201210260005551948",
    "detail_url": "https://data.eastmoney.com/report/info/AP201210260005551948.html",
    "historical_pages": 5,
    "current_attachment_status": "东方财富历史详情页仍保留题目、机构、分析师、日期和5页记录；原公开PDF附件端点现返回‘附件未授权’，无法取得全文。",
}

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def get(url: str, **kwargs: Any) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = session.get(url, timeout=(20, 180), allow_redirects=True, **kwargs)
            print("HTTP", attempt, response.status_code, response.headers.get("content-type"), len(response.content), response.url, flush=True)
            if response.status_code in {429, 500, 502, 503, 504}:
                time.sleep(attempt * 2)
                continue
            response.raise_for_status()
            return response
        except Exception as exc:
            last_error = exc
            if attempt < 5:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Request failed: {url}: {last_error}")


def validate_pdf(path: Path) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages != 3:
        raise RuntimeError(f"Unexpected page count for complete report: {pages}")

    sample_parts: list[str] = []
    for index in range(pages):
        try:
            sample_parts.append(reader.pages[index].extract_text() or "")
        except Exception:
            pass
    compact = re.sub(r"\s+", "", "\n".join(sample_parts))
    if len(compact) > 100 and not any(term in compact for term in ("顾地科技", "顾地", "002694")):
        raise RuntimeError("Company identity not found in PDF text")
    if len(compact) > 100 and "国都" not in compact:
        raise RuntimeError("Broker identity not found in PDF text")

    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=120)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed: {qpdf.returncode}\n{qpdf.stdout}\n{qpdf.stderr}")

    for label, page_number in (("first", 1), ("last", pages)):
        output_base = VERIFY_DIR / f"{path.stem}_{label}"
        render = subprocess.run([
            "pdftoppm", "-png", "-r", "72", "-f", str(page_number), "-l", str(page_number),
            "-singlefile", str(path), str(output_base)
        ], capture_output=True, text=True, timeout=180)
        png_path = Path(str(output_base) + ".png")
        if render.returncode != 0 or not png_path.exists() or png_path.stat().st_size < 1000:
            raise RuntimeError(f"Render failed for page {page_number}: {render.stderr}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "first_last_page_rendered": True,
        "company_and_broker_text_verified_when_extractable": True,
    }


def main() -> None:
    detail = get(FULL_REPORT["detail_url"], headers={"Referer": "https://data.eastmoney.com/"})
    if FULL_REPORT["title"] not in detail.text and FULL_REPORT["info_code"] not in detail.text:
        raise RuntimeError("Complete report detail page did not confirm metadata")

    pdf_response = get(
        FULL_REPORT["pdf_url"],
        headers={"Referer": FULL_REPORT["detail_url"], "Accept": "application/pdf,*/*"},
    )
    if not pdf_response.content.startswith(b"%PDF") or len(pdf_response.content) < 100_000:
        raise RuntimeError("Complete report download is not a valid PDF")

    pdf_path = FULL_DIR / FULL_REPORT["filename"]
    pdf_path.write_bytes(pdf_response.content)
    validation = validate_pdf(pdf_path)

    index_detail = get(INDEX_REPORT["detail_url"], headers={"Referer": "https://data.eastmoney.com/"})
    for expected in (INDEX_REPORT["title"], INDEX_REPORT["institution"], INDEX_REPORT["analyst"]):
        if expected not in index_detail.text:
            raise RuntimeError(f"Index detail page did not confirm metadata: {expected}")

    index_text = f"""历史券商报告公开索引记录（非报告全文）

公司：{COMPANY}（当前证券简称：{CURRENT_NAME}）
证券代码：{CODE}
报告名称：《{INDEX_REPORT['title']}》
机构：{INDEX_REPORT['institution']}
分析师：{INDEX_REPORT['analyst']}
发布日期：{INDEX_REPORT['publish_date']}
历史页数记录：{INDEX_REPORT['historical_pages']}页
东方财富研报编号：{INDEX_REPORT['info_code']}
公开详情页：{INDEX_REPORT['detail_url']}

当前附件状态：
{INDEX_REPORT['current_attachment_status']}

重要说明：
1. 本文件只是公开研报档案的索引与可核验元数据记录，不是原报告全文。
2. 未绕过登录、授权、会员或其他访问限制，也未使用新闻摘要、网页预览或自动生成内容冒充券商报告。
3. 截至{AS_OF}，未找到该报告另一处可公开直接下载并可核验的完整PDF镜像。
"""
    index_path = INDEX_DIR / "20121026_国海证券_布局完善渠道稳固_公开索引记录_非全文.txt"
    index_path.write_text(index_text, encoding="utf-8")

    search_note = f"""{CURRENT_NAME}（原证券简称：顾地科技；证券代码：{CODE}）券商研究资料包

资料截止日期：{AS_OF}

检索结论：
- 已回溯东方财富公开研报库、个股研报日历、2012年上市窗口及后续年度报告披露窗口。
- 公开档案仅确认到2条公司级券商研究记录，均发布于2012年。
- 其中仅国都证券《国内大型综合塑料管道供应商》仍可取得完整PDF，共3页。
- 国海证券《布局完善，渠道稳固》历史记录为5页，但原公开附件目前返回“附件未授权”，因此本包只附明确标注的索引记录，不将其冒充全文。
- 未发现可公开直接下载且来源可核验的20页以上长篇深度报告；本包中的完整文件属于上市前新股/公司研究，篇幅较短。

包内结构：
01_完整券商报告：1份完整官方公开PDF。
02_历史报告索引_非全文：1份公开元数据记录，明确不是报告全文。

版权与用途：报告版权归原证券研究机构及作者所有，仅供个人研究参考，不构成投资建议。
"""
    (ROOT / "00_重要说明与文件清单.txt").write_text(search_note, encoding="utf-8")

    full_record = {
        "relative_path": pdf_path.relative_to(ROOT).as_posix(),
        "record_type": "完整券商报告PDF",
        "company": COMPANY,
        "current_security_name": CURRENT_NAME,
        "stock_code": CODE,
        "publish_date": FULL_REPORT["publish_date"],
        "institution": FULL_REPORT["institution"],
        "analyst": FULL_REPORT["analyst"],
        "title": FULL_REPORT["title"],
        "category": FULL_REPORT["category"],
        "info_code": FULL_REPORT["info_code"],
        "detail_url": FULL_REPORT["detail_url"],
        "pdf_url": FULL_REPORT["pdf_url"],
        "source": "东方财富研报中心公开历史档案及公开PDF端点",
        **validation,
    }
    index_record = {
        "relative_path": index_path.relative_to(ROOT).as_posix(),
        "record_type": "历史研报索引记录（非全文）",
        "company": COMPANY,
        "current_security_name": CURRENT_NAME,
        "stock_code": CODE,
        "publish_date": INDEX_REPORT["publish_date"],
        "institution": INDEX_REPORT["institution"],
        "analyst": INDEX_REPORT["analyst"],
        "title": INDEX_REPORT["title"],
        "historical_pages": INDEX_REPORT["historical_pages"],
        "info_code": INDEX_REPORT["info_code"],
        "detail_url": INDEX_REPORT["detail_url"],
        "source": "东方财富研报中心公开历史详情页",
        "current_attachment_status": INDEX_REPORT["current_attachment_status"],
        "bytes": index_path.stat().st_size,
        "sha256": sha256_file(index_path),
    }
    records = [full_record, index_record]

    with (ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "record_type", "relative_path", "publish_date", "institution", "analyst", "title",
            "pages", "historical_pages", "bytes", "sha256", "info_code", "detail_url", "pdf_url",
            "source", "current_attachment_status"
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "company": COMPANY,
        "current_security_name": CURRENT_NAME,
        "stock_code": CODE,
        "as_of": AS_OF,
        "delivery_scope": "1份完整券商PDF + 1份历史研报索引记录（非全文）",
        "documents": records,
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{record['sha256']}  {record['relative_path']}" for record in records) + "\n",
        encoding="utf-8",
    )

    zip_path = Path(ZIP_NAME)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file_path in sorted(ROOT.rglob("*")):
            if file_path.is_file():
                archive.write(file_path, arcname=f"{ROOT.name}/{file_path.relative_to(ROOT).as_posix()}")

    with zipfile.ZipFile(zip_path, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")
        pdf_count = sum(name.lower().endswith(".pdf") for name in archive.namelist())
        if pdf_count != 1:
            raise RuntimeError(f"Expected exactly 1 complete PDF, found {pdf_count}")

    print("FINAL_ZIP", zip_path.name, zip_path.stat().st_size, sha256_file(zip_path), flush=True)
    print("FINAL_RECORDS", json.dumps(records, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
