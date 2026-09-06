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
import zipfile
from pathlib import Path

import requests
from pypdf import PdfReader

CURRENT_DATE = "2026-09-06"
COMPANY = "哈药股份"
STOCK_CODE = "600664"
PACKAGE_DIR = Path("哈药股份_券商深度及公司覆盖报告_2份")
WORK_DIR = Path("_work_hayao_reports")
PREVIEW_DIR = WORK_DIR / "preview"
ZIP_CN = Path("哈药股份_券商深度报告_2份.zip")
ZIP_EN = Path("Hayao_Broker_Deep_Reports_2_PDFs.zip")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"

SPECS = [
    {
        "sequence": 1,
        "date": "2024-06-12",
        "broker": "信达证券",
        "analysts": "唐爱金、章钟涛",
        "rating": "买入",
        "title": "公司深度报告：营销重塑&品牌产品上量，工业业务或可凤凰涅槃",
        "info_code": "AP202406121635997211",
        "url": "https://pdf.dfcfw.com/pdf/H3_AP202406121635997211_1.pdf",
        "filename": "01_信达证券_哈药股份_营销重塑与品牌产品上量_公司深度报告_2024-06-12_27页.pdf",
        "expected_pages": 27,
        "min_pages": 20,
        "category": "公司深度报告",
    },
    {
        "sequence": 2,
        "date": "2017-03-07",
        "broker": "西南证券",
        "analysts": "朱国广、施跃",
        "rating": "买入",
        "title": "国企改革先锋，未来业绩高成长",
        "info_code": "AP201703070389457853",
        "url": "https://pdf.dfcfw.com/pdf/H3_AP201703070389457853_1.pdf",
        "filename": "02_西南证券_哈药股份_国企改革先锋未来业绩高成长_公司覆盖报告_2017-03-07_6页.pdf",
        "expected_pages": 6,
        "min_pages": 6,
        "category": "公司覆盖报告",
    },
]

PACKAGE_DIR.mkdir(exist_ok=True)
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.headers.update({
    "User-Agent": UA,
    "Referer": "https://data.eastmoney.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "").upper()


def download_pdf(url: str) -> tuple[bytes, str]:
    errors: list[str] = []
    candidates = [url, f"{url}?download={int(time.time())}"]
    for attempt in range(1, 4):
        for candidate in candidates:
            try:
                response = session.get(
                    candidate,
                    headers={
                        "User-Agent": UA,
                        "Referer": "https://data.eastmoney.com/report/",
                        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
                    },
                    timeout=(30, 600),
                    allow_redirects=True,
                )
                print("GET", response.status_code, len(response.content), response.headers.get("content-type"), candidate, flush=True)
                if response.status_code == 200 and response.content.startswith(b"%PDF-"):
                    return response.content, response.url
                errors.append(f"{candidate}: {response.status_code}/{len(response.content)}")
            except Exception as exc:
                errors.append(f"{candidate}: {exc!r}")
        time.sleep(attempt * 2)
    raise RuntimeError("PDF download failed: " + "; ".join(errors[-8:]))


def extract_text(path: Path, page_count: int) -> str:
    reader = PdfReader(str(path))
    chunks: list[str] = []
    for index in range(min(page_count, 35)):
        try:
            chunks.append(reader.pages[index].extract_text() or "")
        except Exception as exc:
            print("TEXT WARNING", path.name, index, repr(exc), flush=True)
    text = "\n".join(chunks)
    if len(compact(text)) < 500:
        result = subprocess.run(
            ["pdftotext", "-f", "1", "-l", str(min(page_count, 40)), str(path), "-"],
            capture_output=True,
            check=False,
        )
        text += "\n" + result.stdout.decode("utf-8", errors="ignore")
    return text


def validate(path: Path, spec: dict) -> dict:
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise RuntimeError("PDF signature missing")

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise RuntimeError("PDF is encrypted") from exc

    pages = len(reader.pages)
    if pages < spec["min_pages"]:
        raise RuntimeError(f"Only {pages} pages")
    if abs(pages - spec["expected_pages"]) > 1:
        raise RuntimeError(f"Unexpected page count: expected {spec['expected_pages']}, got {pages}")

    structural = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True)
    if structural.returncode not in (0, 3):
        raise RuntimeError("qpdf structure check failed: " + structural.stderr[-500:])

    for label, page_number in (("first", 1), ("last", pages)):
        prefix = PREVIEW_DIR / f"{path.stem}_{label}"
        subprocess.run(
            [
                "pdftoppm", "-f", str(page_number), "-l", str(page_number),
                "-singlefile", "-png", "-r", "90", str(path), str(prefix),
            ],
            check=True,
            capture_output=True,
        )
        rendered = Path(str(prefix) + ".png")
        if not rendered.exists() or rendered.stat().st_size < 1000:
            raise RuntimeError(f"Failed to render {label} page")

    text = extract_text(path, pages)
    normalized = compact(text)
    company_ok = compact(COMPANY) in normalized or STOCK_CODE in normalized
    broker_ok = compact(spec["broker"]) in normalized
    title_tokens = [token for token in re.split(r"[：:，,、&\s]+", spec["title"]) if len(token) >= 4]
    title_ok = any(compact(token) in normalized for token in title_tokens)

    if not company_ok:
        raise RuntimeError("Company name or stock code not found in PDF")
    if not broker_ok:
        raise RuntimeError("Broker name not found in PDF")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "company_verified": company_ok,
        "broker_verified": broker_ok,
        "title_verified": title_ok,
        "qpdf_status": structural.returncode,
    }


def main() -> None:
    records: list[dict] = []
    for spec in SPECS:
        data, resolved_url = download_pdf(spec["url"])
        temp = WORK_DIR / f"{spec['sequence']:02d}.pdf"
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_bytes(data)
        metadata = validate(temp, spec)
        destination = PACKAGE_DIR / spec["filename"]
        shutil.copy2(temp, destination)

        record = {
            **spec,
            "resolved_url": resolved_url,
            "source_page": f"https://data.eastmoney.com/report/info/{spec['info_code']}.html",
            **metadata,
        }
        records.append(record)
        print("VERIFIED", json.dumps(record, ensure_ascii=False), flush=True)

    if len(records) != 2:
        raise RuntimeError(f"Expected 2 reports, got {len(records)}")
    if len({record["sha256"] for record in records}) != len(records):
        raise RuntimeError("Duplicate report detected")

    csv_path = PACKAGE_DIR / "来源与校验清单.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = [
            "序号", "文件名", "类别", "券商", "报告日期", "报告标题", "分析师", "评级",
            "页数", "文件大小_字节", "SHA256", "公司校验", "券商校验", "标题校验",
            "研报信息页", "PDF下载地址",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({
                "序号": record["sequence"],
                "文件名": record["filename"],
                "类别": record["category"],
                "券商": record["broker"],
                "报告日期": record["date"],
                "报告标题": record["title"],
                "分析师": record["analysts"],
                "评级": record["rating"],
                "页数": record["pages"],
                "文件大小_字节": record["bytes"],
                "SHA256": record["sha256"],
                "公司校验": record["company_verified"],
                "券商校验": record["broker_verified"],
                "标题校验": record["title_verified"],
                "研报信息页": record["source_page"],
                "PDF下载地址": record["resolved_url"],
            })

    readme = [
        "哈药集团股份有限公司（600664.SH）券商深度及公司覆盖报告包",
        f"整理日期：{CURRENT_DATE}",
        "",
        "筛选口径：",
        "1. 优先完整公司深度、首次覆盖或系统性公司研究报告。",
        "2. 排除付费预览、缺页文件和无法核验的转载版本。",
        "3. 公开渠道可直接下载并完成结构核验的高质量文件共两份，已满足用户要求的2—3份范围。",
        "4. 2025年华泰证券《新班子，新气象，新作为》虽为约36页首次覆盖报告，但公开页面仅提供付费预览，因此未收入本包。",
        "",
        "文件清单：",
    ]
    for record in records:
        readme.append(
            f"{record['sequence']}. {record['filename']}｜{record['category']}｜{record['pages']}页｜"
            f"{record['broker']}｜{record['date']}｜SHA-256：{record['sha256']}"
        )
    readme += [
        "",
        "校验说明：",
        "逐份检查PDF文件头、加密状态、实际页数、公司名称或证券代码、券商署名和qpdf结构完整性，并渲染首尾页确认可正常显示。",
        "详细来源与哈希见《来源与校验清单.csv》。",
    ]
    (PACKAGE_DIR / "README_文件说明.txt").write_text("\n".join(readme), encoding="utf-8")

    for zip_path in (ZIP_CN, ZIP_EN):
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(PACKAGE_DIR.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=str(path))
        with zipfile.ZipFile(zip_path, "r") as archive:
            bad = archive.testzip()
            if bad:
                raise RuntimeError(f"ZIP CRC failure: {bad}")

    package_hash = sha256(ZIP_EN)
    Path("PACKAGE_SHA256.txt").write_text(f"{package_hash}  {ZIP_EN.name}\n", encoding="utf-8")
    print("PACKAGE READY", ZIP_EN, ZIP_EN.stat().st_size, package_hash, flush=True)


if __name__ == "__main__":
    main()
