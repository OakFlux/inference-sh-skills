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
COMPANY = "广深铁路"
STOCK_CODE = "601333"
PACKAGE = Path("广深铁路_券商深度报告_3份")
WORK = Path("_work_guangshen_v2")
PREVIEW = WORK / "preview"
ZIP_CN = Path("广深铁路_券商深度报告_3份.zip")
ZIP_EN = Path("Guangshen_Railway_Broker_Deep_Reports_3_PDFs.zip")
API = "https://reportapi.eastmoney.com/report/list"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36"

PACKAGE.mkdir(exist_ok=True)
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
        "report_date": "2025-10-29",
        "windows": [("2025-10-27", "2025-11-04")],
        "filename": "01_甬兴证券_广深铁路_广铁枢纽高铁化加速_2025-10-29.pdf",
        "min_pages": 15,
    },
    {
        "phrase": "大湾区铁路运输龙头",
        "institution": "西南证券",
        "report_date": "2025-07-16",
        "windows": [("2025-07-14", "2025-07-30")],
        "filename": "02_西南证券_广深铁路_大湾区铁路运输龙头_2025-07-16.pdf",
        "min_pages": 15,
    },
    {
        "phrase": "广铁核心枢纽的价值重构",
        "institution": "华福证券",
        "report_date": "2024-07-15",
        "windows": [("2024-07-12", "2024-07-19")],
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


def api_page(begin: str, end: str, page: int, code: str = "") -> dict:
    params = {
        "industryCode": "*",
        "pageSize": "100",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": begin,
        "endTime": end,
        "pageNo": str(page),
        "fields": "",
        "qType": "0",
        "orgCode": "",
        "code": code,
        "rcode": "",
        "p": str(page),
        "pageNum": str(page),
        "pageNumber": str(page),
    }
    response = session.get(API, params=params, timeout=(30, 180))
    print("API", response.status_code, begin, end, "page", page, "code", code, len(response.content), flush=True)
    response.raise_for_status()
    return response.json()


def scan_range(begin: str, end: str, code: str = "") -> list[dict]:
    first = api_page(begin, end, 1, code=code)
    total_pages = int(first.get("TotalPage") or 1)
    rows = list(first.get("data") or [])
    print("RANGE", begin, end, "code", code, "pages", total_pages, "first_rows", len(rows), flush=True)
    for page in range(2, total_pages + 1):
        payload = api_page(begin, end, page, code=code)
        rows.extend(payload.get("data") or [])
        time.sleep(0.25)
    return rows


def collect_rows() -> list[dict]:
    rows = scan_range("2024-01-01", CURRENT_DATE, code=STOCK_CODE)
    for target in TARGETS:
        for begin, end in target["windows"]:
            rows.extend(scan_range(begin, end, code=""))
    dedup = {}
    for row in rows:
        key = str(row.get("infoCode") or "")
        if key:
            dedup[key] = row
    result = list(dedup.values())
    for row in result:
        title = compact(row.get("title"))
        org = compact((row.get("orgSName") or "") + (row.get("orgName") or ""))
        stock = compact((row.get("stockName") or "") + (row.get("stockCode") or ""))
        if compact(COMPANY) in stock or STOCK_CODE in stock or any(compact(t["phrase"]) in title for t in TARGETS):
            print("CANDIDATE", json.dumps(row, ensure_ascii=False, default=str), flush=True)
    return result


def choose(rows: list[dict], target: dict) -> dict:
    phrase = compact(target["phrase"])
    institution = compact(target["institution"])
    exact = []
    fallback = []
    for row in rows:
        title = compact(row.get("title"))
        org = compact((row.get("orgSName") or "") + (row.get("orgName") or ""))
        stock = compact((row.get("stockName") or "") + (row.get("stockCode") or ""))
        company_match = compact(COMPANY) in stock or STOCK_CODE in stock or compact(COMPANY) in title
        if phrase in title and institution in org:
            exact.append(row)
        elif company_match and institution in org:
            fallback.append(row)
    matches = exact or fallback
    if not matches:
        raise RuntimeError(f"No record found for {target['institution']} / {target['phrase']}")
    matches.sort(key=lambda r: (
        1 if phrase in compact(r.get("title")) else 0,
        int(r.get("attachPages") or 0),
        str(r.get("publishDate") or ""),
    ), reverse=True)
    print("MATCHES", target["phrase"], json.dumps(matches, ensure_ascii=False, default=str), flush=True)
    return matches[0]


def fetch_pdf(info_code: str) -> tuple[bytes, str]:
    urls = [
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf?{int(time.time())}",
    ]
    errors = []
    for attempt in range(1, 4):
        for url in urls:
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
                    return response.content, response.url
                errors.append(f"{url}: {response.status_code}/{len(response.content)}")
            except Exception as exc:
                errors.append(f"{url}: {exc!r}")
        time.sleep(2 * attempt)
    raise RuntimeError("; ".join(errors[-8:]))


def probe_text(path: Path, pages: int) -> str:
    reader = PdfReader(str(path))
    chunks = []
    indexes = list(range(min(25, pages)))
    if pages > 25:
        indexes.extend(range(max(25, pages - 5), pages))
    for idx in sorted(set(indexes)):
        try:
            chunks.append(reader.pages[idx].extract_text() or "")
        except Exception as exc:
            print("TEXT WARNING", idx, repr(exc), flush=True)
    text = "\n".join(chunks)
    if len(compact(text)) < 500:
        result = subprocess.run(
            ["pdftotext", "-f", "1", "-l", str(min(50, pages)), str(path), "-"],
            capture_output=True,
            check=False,
        )
        text += "\n" + result.stdout.decode("utf-8", errors="ignore")
    return text


def validate(path: Path, target: dict, row: dict) -> dict:
    with path.open("rb") as f:
        if f.read(5) != b"%PDF-":
            raise RuntimeError("Invalid PDF signature")
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise RuntimeError("Encrypted PDF") from exc
    pages = len(reader.pages)
    if pages < target["min_pages"]:
        raise RuntimeError(f"Only {pages} pages")
    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError("qpdf failed: " + qpdf.stderr[-500:])
    for label, page in (("first", 1), ("last", pages)):
        prefix = PREVIEW / f"{path.stem}_{label}"
        subprocess.run(
            ["pdftoppm", "-f", str(page), "-l", str(page), "-singlefile", "-png", "-r", "72", str(path), str(prefix)],
            check=True,
            capture_output=True,
        )
        image = Path(str(prefix) + ".png")
        if not image.exists() or image.stat().st_size < 1000:
            raise RuntimeError("Render check failed")
    text = compact(probe_text(path, pages))
    company_ok = compact(COMPANY) in text or STOCK_CODE in text or "00525" in text
    broker_ok = compact(target["institution"]) in text
    phrase_ok = compact(target["phrase"]) in text or any(
        compact(token) in text for token in re.split(r"[，,:：—\- ]+", target["phrase"]) if len(compact(token)) >= 4
    )
    print("VALIDATE", target["institution"], pages, company_ok, broker_ok, phrase_ok, flush=True)
    if not company_ok:
        raise RuntimeError("Company identity not found")
    if not broker_ok:
        raise RuntimeError("Broker identity not found")
    api_pages = int(row.get("attachPages") or 0)
    if api_pages and abs(api_pages - pages) > 1:
        raise RuntimeError(f"Page mismatch API={api_pages} PDF={pages}")
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "company_verified": company_ok,
        "broker_verified": broker_ok,
        "title_verified": phrase_ok,
        "qpdf_status": qpdf.returncode,
    }


def main() -> None:
    rows = collect_rows()
    records = []
    for index, target in enumerate(TARGETS, 1):
        row = choose(rows, target)
        info_code = str(row.get("infoCode") or "")
        data, resolved_url = fetch_pdf(info_code)
        temp = WORK / f"{index:02d}.pdf"
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_bytes(data)
        meta = validate(temp, target, row)
        shutil.copy2(temp, PACKAGE / target["filename"])
        record = {
            "sequence": index,
            "filename": target["filename"],
            "institution": row.get("orgSName") or row.get("orgName") or target["institution"],
            "report_date": target["report_date"],
            "database_publish_date": str(row.get("publishDate") or "")[:10],
            "title": row.get("title") or target["phrase"],
            "rating": row.get("sRatingName") or row.get("emRatingName") or "",
            "researcher": row.get("researcher") or "",
            "info_code": info_code,
            "source_page": f"https://data.eastmoney.com/report/info/{info_code}.html",
            "pdf_url": resolved_url,
            **meta,
        }
        records.append(record)
        print("VERIFIED", json.dumps(record, ensure_ascii=False, default=str), flush=True)

    if len(records) != 3 or len({r["sha256"] for r in records}) != 3:
        raise RuntimeError("Report count or uniqueness validation failed")

    with (PACKAGE / "来源与校验清单.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = [
            "序号", "文件名", "券商", "报告日期", "数据库收录日期", "原报告标题", "评级", "分析师",
            "页数", "文件大小_字节", "SHA256", "公司校验", "券商校验", "标题校验", "研报信息页", "PDF地址",
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in records:
            writer.writerow({
                "序号": r["sequence"], "文件名": r["filename"], "券商": r["institution"],
                "报告日期": r["report_date"], "数据库收录日期": r["database_publish_date"],
                "原报告标题": r["title"], "评级": r["rating"], "分析师": r["researcher"],
                "页数": r["pages"], "文件大小_字节": r["bytes"], "SHA256": r["sha256"],
                "公司校验": r["company_verified"], "券商校验": r["broker_verified"],
                "标题校验": r["title_verified"], "研报信息页": r["source_page"], "PDF地址": r["pdf_url"],
            })

    lines = [
        "广深铁路股份有限公司（601333.SH / 00525.HK）券商深度报告包",
        f"整理日期：{CURRENT_DATE}", "",
        "筛选口径：优先2024年以来的公司深度或首次覆盖报告；排除普通业绩点评、摘要、缺页预览和加密文件。",
        "本包收录甬兴证券、西南证券、华福证券三家机构的完整原始PDF。", "", "文件清单：",
    ]
    for r in records:
        lines.append(f"{r['sequence']}. {r['filename']}｜{r['pages']}页｜{r['institution']}｜SHA-256：{r['sha256']}")
    lines += ["", "校验：PDF文件头、加密状态、实际页数、公司/证券代码、券商署名、qpdf结构及首尾页渲染均已检查。", "详细来源见《来源与校验清单.csv》。"]
    (PACKAGE / "README_文件说明.txt").write_text("\n".join(lines), encoding="utf-8")

    for zip_path in (ZIP_CN, ZIP_EN):
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for path in sorted(PACKAGE.rglob("*")):
                if path.is_file():
                    zf.write(path, arcname=str(path))
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad = zf.testzip()
            if bad:
                raise RuntimeError(f"ZIP CRC failure: {bad}")
    package_hash = sha256(ZIP_EN)
    Path("PACKAGE_SHA256.txt").write_text(f"{package_hash}  {ZIP_EN.name}\n", encoding="utf-8")
    print("PACKAGE READY", ZIP_EN, ZIP_EN.stat().st_size, package_hash, flush=True)


if __name__ == "__main__":
    main()
