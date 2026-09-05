#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import time
import unicodedata
import zipfile
from pathlib import Path

import requests
from pypdf import PdfReader

CURRENT_DATE = "2026-09-05"
STOCK_CODE = "601333"
COMPANY = "广深铁路"
PACKAGE_DIR = Path("广深铁路_券商深度报告_3份")
WORK = Path("_work_guangshen_broker")
PREVIEW = WORK / "preview"
ZIP_CN = Path("广深铁路_券商深度报告_3份.zip")
ZIP_EN = Path("Guangshen_Railway_Broker_Deep_Reports_3_PDFs.zip")
API = "https://reportapi.eastmoney.com/report/list"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36"

PACKAGE_DIR.mkdir(exist_ok=True)
PREVIEW.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.headers.update({
    "User-Agent": UA,
    "Referer": "https://data.eastmoney.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
})

TARGETS = [
    {
        "phrase": "广铁枢纽高铁化加速",
        "institution": "甬兴证券",
        "date_hint": "2025-10-29",
        "filename": "01_甬兴证券_广深铁路_广铁枢纽高铁化加速_2025-10-29.pdf",
        "min_pages": 15,
    },
    {
        "phrase": "大湾区铁路运输龙头",
        "institution": "西南证券",
        "date_hint": "2025-07-16",
        "filename": "02_西南证券_广深铁路_大湾区铁路运输龙头_2025-07-16.pdf",
        "min_pages": 15,
    },
    {
        "phrase": "广铁核心枢纽的价值重构",
        "institution": "华福证券",
        "date_hint": "2024-07-15",
        "filename": "03_华福证券_广深铁路_广铁核心枢纽的价值重构_2024-07-15.pdf",
        "min_pages": 15,
    },
]


def compact(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"[^0-9A-Z\u4e00-\u9fff]+", "", text.upper())


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def query_reports() -> list[dict]:
    all_rows: list[dict] = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        params = {
            "industryCode": "*",
            "pageSize": "100",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": "2024-01-01",
            "endTime": CURRENT_DATE,
            "pageNo": str(page),
            "fields": "",
            "qType": "0",
            "orgCode": "",
            "code": STOCK_CODE,
            "rcode": "",
            "p": str(page),
            "pageNum": str(page),
            "pageNumber": str(page),
        }
        response = session.get(API, params=params, timeout=(30, 180))
        print("API", response.status_code, response.url, len(response.content), flush=True)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") or []
        total_pages = int(payload.get("TotalPage") or 1)
        print("PAGE", page, "TOTAL", total_pages, "ROWS", len(rows), flush=True)
        all_rows.extend(rows)
        page += 1
        time.sleep(0.5)
    filtered = []
    for row in all_rows:
        stock_name = str(row.get("stockName") or "")
        stock_code = str(row.get("stockCode") or "")
        title = str(row.get("title") or "")
        if stock_code == STOCK_CODE or COMPANY in stock_name or COMPANY in title:
            filtered.append(row)
            print("REPORT", json.dumps(row, ensure_ascii=False, default=str), flush=True)
    return filtered


def choose_record(rows: list[dict], target: dict) -> dict:
    phrase = compact(target["phrase"])
    institution = compact(target["institution"])
    matches = []
    for row in rows:
        title = compact(row.get("title"))
        org = compact((row.get("orgSName") or "") + (row.get("orgName") or ""))
        if phrase in title and institution in org:
            matches.append(row)
    if not matches:
        for row in rows:
            if phrase in compact(row.get("title")):
                matches.append(row)
    if not matches:
        raise RuntimeError(f"No matching research record for {target['phrase']}")
    matches.sort(
        key=lambda r: (
            int(r.get("attachPages") or 0),
            str(r.get("publishDate") or ""),
        ),
        reverse=True,
    )
    print("TARGET MATCHES", target["phrase"], json.dumps(matches, ensure_ascii=False, default=str), flush=True)
    return matches[0]


def fetch_pdf(info_code: str) -> tuple[requests.Response, str]:
    candidates = [
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf?{int(time.time())}",
    ]
    errors = []
    for attempt in range(1, 4):
        for url in candidates:
            try:
                response = session.get(
                    url,
                    headers={
                        "User-Agent": UA,
                        "Referer": "https://data.eastmoney.com/report/",
                        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
                    },
                    timeout=(30, 600),
                    allow_redirects=True,
                )
                print("PDF", response.status_code, len(response.content), response.headers.get("content-type"), url, flush=True)
                if response.status_code == 200 and response.content.startswith(b"%PDF-"):
                    return response, url
                errors.append(f"{url}: {response.status_code}/{len(response.content)}")
            except Exception as exc:
                errors.append(f"{url}: {exc!r}")
        time.sleep(attempt * 2)
    raise RuntimeError("PDF download failed: " + "; ".join(errors[-8:]))


def extract_text(path: Path, pages: int) -> str:
    reader = PdfReader(str(path))
    chunks = []
    inspect = list(range(min(20, pages)))
    if pages > 25:
        inspect.extend(range(max(20, pages - 5), pages))
    for idx in sorted(set(inspect)):
        try:
            chunks.append(reader.pages[idx].extract_text() or "")
        except Exception as exc:
            print("TEXT WARNING", path.name, idx, repr(exc), flush=True)
    text = "\n".join(chunks)
    if len(compact(text)) < 500:
        result = subprocess.run(
            ["pdftotext", "-f", "1", "-l", str(min(40, pages)), str(path), "-"],
            capture_output=True,
            check=False,
        )
        text += "\n" + result.stdout.decode("utf-8", errors="ignore")
    return text


def validate(path: Path, target: dict, row: dict) -> dict:
    with path.open("rb") as f:
        if f.read(5) != b"%PDF-":
            raise RuntimeError("PDF signature missing")
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise RuntimeError("Encrypted PDF") from exc
    pages = len(reader.pages)
    if pages < target["min_pages"]:
        raise RuntimeError(f"Only {pages} pages; not a deep report")

    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True)
    if check.returncode not in (0, 3):
        raise RuntimeError("qpdf validation failed: " + check.stderr[-500:])

    for label, page_no in (("first", 1), ("last", pages)):
        prefix = PREVIEW / f"{path.stem}_{label}"
        subprocess.run(
            ["pdftoppm", "-f", str(page_no), "-l", str(page_no), "-singlefile", "-png", "-r", "72", str(path), str(prefix)],
            check=True,
            capture_output=True,
        )
        rendered = Path(str(prefix) + ".png")
        if not rendered.exists() or rendered.stat().st_size < 1000:
            raise RuntimeError(f"Failed to render {label} page")

    text = extract_text(path, pages)
    text_norm = compact(text)
    company_ok = compact(COMPANY) in text_norm or STOCK_CODE in text_norm or "00525" in text_norm
    broker_ok = compact(target["institution"]) in text_norm
    title_tokens = [compact(x) for x in re.split(r"[，,:：—\- ]+", target["phrase"]) if len(compact(x)) >= 4]
    title_ok = any(token in text_norm for token in title_tokens) if title_tokens else True
    print("VALIDATE", path.name, pages, company_ok, broker_ok, title_ok, flush=True)
    if not company_ok:
        raise RuntimeError("Company identity not found in PDF text")
    if not broker_ok:
        raise RuntimeError("Broker identity not found in PDF text")

    api_pages = int(row.get("attachPages") or 0)
    if api_pages and abs(api_pages - pages) > 1:
        raise RuntimeError(f"Page-count mismatch: API={api_pages}, PDF={pages}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "company_verified": company_ok,
        "broker_verified": broker_ok,
        "title_verified": title_ok,
        "qpdf_status": check.returncode,
    }


def main() -> None:
    rows = query_reports()
    records = []
    for index, target in enumerate(TARGETS, 1):
        row = choose_record(rows, target)
        info_code = str(row.get("infoCode") or "").strip()
        if not info_code:
            raise RuntimeError("Missing Eastmoney infoCode")
        response, requested_url = fetch_pdf(info_code)
        temp = WORK / f"{index:02d}.pdf"
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_bytes(response.content)
        meta = validate(temp, target, row)
        destination = PACKAGE_DIR / target["filename"]
        shutil.copy2(temp, destination)
        record = {
            "sequence": index,
            "filename": target["filename"],
            "institution": row.get("orgSName") or row.get("orgName") or target["institution"],
            "report_date": str(row.get("publishDate") or target["date_hint"])[:10],
            "title": row.get("title") or target["phrase"],
            "rating": row.get("sRatingName") or row.get("emRatingName") or "",
            "researcher": row.get("researcher") or "",
            "info_code": info_code,
            "source_page": f"https://data.eastmoney.com/report/info/{info_code}.html",
            "requested_pdf_url": requested_url,
            "resolved_pdf_url": response.url,
            **meta,
        }
        records.append(record)
        print("VERIFIED", json.dumps(record, ensure_ascii=False, default=str), flush=True)

    if len(records) != 3:
        raise RuntimeError(f"Expected 3 reports, got {len(records)}")
    if len({r["sha256"] for r in records}) != 3:
        raise RuntimeError("Duplicate PDF detected")

    with (PACKAGE_DIR / "来源与校验清单.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = [
            "序号", "文件名", "券商", "报告日期", "原报告标题", "评级", "分析师",
            "页数", "文件大小_字节", "SHA256", "公司校验", "券商校验", "标题校验",
            "研报信息页", "PDF下载地址",
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in records:
            writer.writerow({
                "序号": r["sequence"],
                "文件名": r["filename"],
                "券商": r["institution"],
                "报告日期": r["report_date"],
                "原报告标题": r["title"],
                "评级": r["rating"],
                "分析师": r["researcher"],
                "页数": r["pages"],
                "文件大小_字节": r["bytes"],
                "SHA256": r["sha256"],
                "公司校验": r["company_verified"],
                "券商校验": r["broker_verified"],
                "标题校验": r["title_verified"],
                "研报信息页": r["source_page"],
                "PDF下载地址": r["resolved_pdf_url"],
            })

    readme = [
        "广深铁路股份有限公司（A股：601333；H股：00525）券商深度报告包",
        f"整理日期：{CURRENT_DATE}",
        "",
        "筛选原则：优先2024年以来、篇幅较完整的首次覆盖或公司深度报告；排除简短业绩点评、新闻摘要、加密文件和缺页预览。",
        "本包收录三家不同券商的完整原始PDF：甬兴证券、西南证券、华福证券。",
        "",
        "文件清单：",
    ]
    for r in records:
        readme.append(f"{r['sequence']}. {r['filename']}｜{r['pages']}页｜{r['institution']}｜{r['report_date']}｜SHA-256：{r['sha256']}")
    readme += [
        "",
        "校验说明：逐份检查PDF文件头、加密状态、实际页数、公司名称/证券代码、券商署名、qpdf结构完整性，并渲染首尾页确认可正常显示。",
        "详细来源及哈希见《来源与校验清单.csv》。",
    ]
    (PACKAGE_DIR / "README_文件说明.txt").write_text("\n".join(readme), encoding="utf-8")

    for zip_path in (ZIP_CN, ZIP_EN):
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for path in sorted(PACKAGE_DIR.rglob("*")):
                if path.is_file():
                    zf.write(path, arcname=str(path))
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad = zf.testzip()
            if bad:
                raise RuntimeError(f"ZIP CRC failure in {zip_path}: {bad}")

    package_hash = sha256(ZIP_EN)
    Path("PACKAGE_SHA256.txt").write_text(f"{package_hash}  {ZIP_EN.name}\n", encoding="utf-8")
    print("PACKAGE READY", ZIP_EN, ZIP_EN.stat().st_size, package_hash, flush=True)


if __name__ == "__main__":
    main()
