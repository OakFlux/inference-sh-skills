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

import requests
from pypdf import PdfReader

COMPANY = "顾地科技"
CURRENT_NAME = "*ST顾地"
CODE = "002694"
AS_OF = "2026-10-04"
ROOT = Path(f"{CURRENT_NAME}_{CODE}_券商研究报告_2份")
REPORT_DIR = ROOT / "01_券商研究报告"
VERIFY_DIR = Path("_verify_st_gudi_broker")
ZIP_NAME = f"{CURRENT_NAME}_{CODE}_券商研究报告_2份_20261004.zip"
for d in (REPORT_DIR, VERIFY_DIR):
    d.mkdir(parents=True, exist_ok=True)

REPORTS = [
    {
        "publish_date": "2012-08-06",
        "institution": "国都证券",
        "analyst": "王双",
        "title": "国内大型综合塑料管道供应商",
        "info_code": "AP201208060005410276",
        "detail_url": "https://data.eastmoney.com/report/info/AP201208060005410276.html",
        "pdf_url": "https://pdf.dfcfw.com/pdf/H3_AP201208060005410276_1.pdf",
        "filename": "20120806_国都证券_国内大型综合塑料管道供应商.pdf",
        "category": "新股研究/公司研究",
        "selection_note": "上市前新股研究，篇幅较短，梳理公司业务、行业空间及发行估值。",
    },
    {
        "publish_date": "2012-10-26",
        "institution": "国海证券",
        "analyst": "代鹏举",
        "title": "布局完善，渠道稳固",
        "info_code": "AP201210260005551948",
        "detail_url": "https://data.eastmoney.com/report/info/AP201210260005551948.html",
        "pdf_url": "https://pdf.dfcfw.com/pdf/H3_AP201210260005551948_1.pdf",
        "filename": "20121026_国海证券_布局完善，渠道稳固.pdf",
        "category": "公司研究",
        "selection_note": "上市后公司研究，重点讨论生产布局、渠道基础与经营表现。",
    },
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def get(url: str, **kwargs: Any) -> requests.Response:
    last = None
    for attempt in range(1, 6):
        try:
            r = session.get(url, timeout=(20, 180), allow_redirects=True, **kwargs)
            print("HTTP", attempt, r.status_code, r.headers.get("content-type"), len(r.content), r.url, flush=True)
            if r.status_code in {429, 500, 502, 503, 504}:
                time.sleep(attempt * 2)
                continue
            r.raise_for_status()
            return r
        except Exception as exc:
            last = exc
            if attempt < 5:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Request failed: {url}: {last}")


def validate_pdf(path: Path, report: dict[str, str]) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 2:
        raise RuntimeError(f"Too few pages: {path.name}: {pages}")

    text_parts = []
    for idx in sorted(set([0, min(1, pages - 1), pages - 1])):
        try:
            text_parts.append(reader.pages[idx].extract_text() or "")
        except Exception:
            pass
    sample = "\n".join(text_parts)
    compact = re.sub(r"\s+", "", sample)
    identity_ok = any(term in compact for term in ("顾地科技", "顾地", "002694", "GOODY"))
    institution_ok = report["institution"][:2] in compact or len(compact) < 100
    if len(compact) >= 100 and not identity_ok:
        raise RuntimeError(f"Company identity not found in PDF sample: {path.name}")

    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=120)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {qpdf.returncode}\n{qpdf.stdout}\n{qpdf.stderr}")

    for label, page_no in (("first", 1), ("last", pages)):
        out_base = VERIFY_DIR / f"{path.stem}_{label}"
        res = subprocess.run([
            "pdftoppm", "-png", "-r", "72", "-f", str(page_no), "-l", str(page_no),
            "-singlefile", str(path), str(out_base)
        ], capture_output=True, text=True, timeout=180)
        png = Path(str(out_base) + ".png")
        if res.returncode != 0 or not png.exists() or png.stat().st_size < 1000:
            raise RuntimeError(f"Render failed for {path.name} page {page_no}: {res.stderr}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "first_last_page_rendered": True,
        "identity_text_verified_when_extractable": identity_ok or len(compact) < 100,
        "institution_text_verified_when_extractable": institution_ok,
    }


def main() -> None:
    records = []
    for report in REPORTS:
        # Fetch detail page as provenance check.
        detail = get(report["detail_url"], headers={"Referer": "https://data.eastmoney.com/"})
        if report["title"] not in detail.text and report["info_code"] not in detail.text:
            raise RuntimeError(f"Detail page did not confirm report metadata: {report['title']}")

        dest = REPORT_DIR / report["filename"]
        pdf = get(report["pdf_url"], headers={"Referer": report["detail_url"], "Accept": "application/pdf,*/*"})
        if not pdf.content.startswith(b"%PDF"):
            raise RuntimeError(f"Not a PDF: {report['pdf_url']}: {pdf.content[:20]!r}")
        if len(pdf.content) < 100_000:
            raise RuntimeError(f"Suspiciously small PDF: {report['title']}: {len(pdf.content)}")
        dest.write_bytes(pdf.content)
        validation = validate_pdf(dest, report)
        record = {
            "relative_path": dest.relative_to(ROOT).as_posix(),
            "filename": dest.name,
            "company": COMPANY,
            "current_security_name": CURRENT_NAME,
            "stock_code": CODE,
            "publish_date": report["publish_date"],
            "institution": report["institution"],
            "analyst": report["analyst"],
            "title": report["title"],
            "category": report["category"],
            "selection_note": report["selection_note"],
            "info_code": report["info_code"],
            "detail_url": report["detail_url"],
            "pdf_url": report["pdf_url"],
            "source": "东方财富研报中心公开历史档案及公开PDF端点",
            **validation,
        }
        records.append(record)
        print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

    if len({r["sha256"] for r in records}) != len(records):
        raise RuntimeError("Duplicate PDFs detected")

    readme = f"""{CURRENT_NAME}（原证券简称：顾地科技；证券代码：{CODE}）公开券商研究资料包

资料截止日期：{AS_OF}

检索结论：
1. 已回溯公开卖方研报库、东方财富历史个股研报日历以及上市期和历年年报窗口。
2. 公开档案仅确认到本包中的2份公司级券商研究报告，均发布于2012年。
3. 两份材料篇幅均较短，不属于当前常见的20页以上长篇深度报告；本包未将其冒充为长篇深度覆盖。
4. 2012年上市期间另有多家券商给出询价或上市定价区间，但对应完整PDF未在可公开直接下载的档案中保留，因此没有使用新闻摘要或付费预览页替代。

收录文件：
- 国都证券：《国内大型综合塑料管道供应商》，2012-08-06。
- 国海证券：《布局完善，渠道稳固》，2012-10-26。

来源：东方财富研报中心公开历史档案及公开PDF端点。
用途：仅供个人研究参考，版权归原证券研究机构及作者所有，不构成投资建议。
"""
    (ROOT / "00_重要说明与文件清单.txt").write_text(readme, encoding="utf-8")

    with (ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = [
            "relative_path", "publish_date", "institution", "analyst", "title", "category",
            "pages", "bytes", "sha256", "detail_url", "pdf_url", "source", "selection_note"
        ]
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "company": COMPANY,
        "current_security_name": CURRENT_NAME,
        "stock_code": CODE,
        "as_of": AS_OF,
        "scope_note": "公开可核验的公司级券商研究报告2份；非20页以上长篇深度覆盖",
        "documents": records,
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{r['sha256']}  {r['relative_path']}" for r in records) + "\n", encoding="utf-8"
    )

    zip_path = Path(ZIP_NAME)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=f"{ROOT.name}/{path.relative_to(ROOT).as_posix()}")
    with zipfile.ZipFile(zip_path, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failed: {bad}")
        pdf_count = sum(n.lower().endswith(".pdf") for n in zf.namelist())
        if pdf_count != 2:
            raise RuntimeError(f"Expected 2 PDFs in ZIP, got {pdf_count}")

    print("FINAL_ZIP", zip_path.name, zip_path.stat().st_size, sha256_file(zip_path), flush=True)
    print("FINAL_RECORDS", json.dumps(records, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
