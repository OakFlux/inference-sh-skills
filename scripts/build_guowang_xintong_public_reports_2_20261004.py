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

COMPANY = "国网信通"
CODE = "600131"
AS_OF = "2026-10-04"
ROOT = Path(f"{COMPANY}_{CODE}_券商研究报告_2份")
REPORT_DIR = ROOT / "01_券商研究报告"
VERIFY_DIR = Path("_verify_guowang_xintong_2")
ZIP_NAME = f"{COMPANY}_{CODE}_券商研究报告_2份_20261004.zip"

REPORTS = [
    {
        "info_code": "AP202412031641166898",
        "publish_date": "2024-12-03",
        "institution": "东吴证券",
        "analysts": "王紫敬",
        "rating": "买入",
        "title": "国网系能源IT龙头，电网国企改革前线",
        "expected_pages": 17,
        "category": "公司深度研究",
        "selection_note": "完整公司深度研究，覆盖能源IT业务、电网信息化投入、竞争壁垒及国企改革。",
    },
    {
        "info_code": "AP202406021635191154",
        "publish_date": "2024-06-02",
        "institution": "国信证券",
        "analysts": "熊莉、库宏垚",
        "rating": "增持（证券公司口径：优于大市）",
        "title": "一季度承压，电力体制改革推动数字化业务发展",
        "expected_pages": 11,
        "category": "较长篇公司覆盖报告",
        "selection_note": "完整11页公司研究，覆盖电力体制改革、电网数字化、目标价及盈利预测。",
    },
]

for d in (REPORT_DIR, VERIFY_DIR):
    d.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Referer": "https://data.eastmoney.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})


def get(url: str, **kwargs: Any) -> requests.Response:
    last: Exception | None = None
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
            if attempt == 5:
                break
            time.sleep(attempt * 2)
    raise RuntimeError(f"Request failed: {url}: {last}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_pdf_url(info_code: str) -> tuple[str, str]:
    detail_url = f"https://data.eastmoney.com/report/info/{info_code}.html"
    text = get(detail_url).text
    urls = re.findall(r'href=["\'](https?://[^"\']+\.pdf[^"\']*)["\']', text, re.I)
    if not urls:
        raise RuntimeError(f"No public PDF link found for {info_code}")
    return detail_url, urls[0].split("?", 1)[0]


def validate(path: Path, expected_pages: int) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages != expected_pages:
        raise RuntimeError(f"Page mismatch for {path.name}: actual={pages}, expected={expected_pages}")
    text = ""
    for idx in sorted(set([0, 1, pages - 1])):
        try:
            text += "\n" + (reader.pages[idx].extract_text() or "")
        except Exception:
            pass
    lowered = text.lower()
    if len(lowered.strip()) > 200 and not any(term in lowered for term in ("国网信通", "600131", "state grid information")):
        raise RuntimeError(f"Company identity not found in {path.name}")

    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=120)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {qpdf.stderr}")

    for page_num, suffix in ((1, "first"), (pages, "last")):
        base = VERIFY_DIR / f"{path.stem}_{suffix}"
        proc = subprocess.run([
            "pdftoppm", "-png", "-r", "72", "-f", str(page_num), "-l", str(page_num),
            "-singlefile", str(path), str(base)
        ], capture_output=True, text=True, timeout=180)
        png = Path(str(base) + ".png")
        if proc.returncode != 0 or not png.exists() or png.stat().st_size < 1000:
            raise RuntimeError(f"Render failed for {path.name} page {page_num}: {proc.stderr}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "first_last_page_rendered": True,
        "identity_text_verified_when_extractable": True,
    }


def main() -> None:
    records: list[dict[str, Any]] = []
    for item in REPORTS:
        detail_url, pdf_url = extract_pdf_url(item["info_code"])
        filename = f"{item['publish_date'].replace('-', '')}_{item['institution']}_{item['title']}.pdf"
        path = REPORT_DIR / filename
        response = get(pdf_url, headers={"Referer": detail_url, "Accept": "application/pdf,*/*"})
        if not response.content.startswith(b"%PDF"):
            raise RuntimeError(f"Not PDF: {pdf_url}")
        path.write_bytes(response.content)
        record = {
            "relative_path": path.relative_to(ROOT).as_posix(),
            "filename": filename,
            "company": COMPANY,
            "stock_code": CODE,
            "detail_url": detail_url,
            "pdf_url": pdf_url,
            "source": "东方财富研报中心公开PDF端点",
            **item,
            **validate(path, item["expected_pages"]),
        }
        records.append(record)
        print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

    if len(records) != 2 or len({r["sha256"] for r in records}) != 2:
        raise RuntimeError("Report count or duplicate check failed")

    readme = f"""国网信息通信股份有限公司（国网信通，{CODE}）券商研究报告文件包

整理日期：{AS_OF}

本包收录2份来源可核验、可公开直接下载的完整PDF：
1. 东吴证券17页公司深度研究；
2. 国信证券11页较长篇公司覆盖报告。

检索说明：另检索到西部证券、中泰证券和中信证券的长篇深度报告，但公开页面要求登录、会员或付费后下载。本包未绕过访问限制，也未用预览页冒充完整报告。

报告版权归相应证券研究机构及作者所有，仅供个人研究参考，不构成投资建议。
"""
    (ROOT / "00_文件清单与来源说明.txt").write_text(readme, encoding="utf-8")

    with (ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["relative_path", "publish_date", "institution", "analysts", "rating", "category", "title", "pages", "bytes", "sha256", "detail_url", "pdf_url", "selection_note"]
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    (ROOT / "manifest.json").write_text(json.dumps({
        "company": COMPANY,
        "stock_code": CODE,
        "as_of": AS_OF,
        "documents": records,
        "access_limit_note": "Other long-form reports found only behind login/member/payment access and were not included.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "SHA256SUMS.txt").write_text("\n".join(f"{r['sha256']}  {r['relative_path']}" for r in records) + "\n", encoding="utf-8")

    zip_path = Path(ZIP_NAME)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=f"{ROOT.name}/{path.relative_to(ROOT).as_posix()}")
    with zipfile.ZipFile(zip_path, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")
        if sum(name.lower().endswith(".pdf") for name in zf.namelist()) != 2:
            raise RuntimeError("ZIP PDF count mismatch")

    print("FINAL_ZIP", zip_path.name, zip_path.stat().st_size, sha256(zip_path), flush=True)
    print("FINAL_RECORDS", json.dumps(records, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
