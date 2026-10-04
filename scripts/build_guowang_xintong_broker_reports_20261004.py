from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import subprocess
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

COMPANY = "国网信通"
CODE = "600131"
AS_OF = "2026-10-04"
ROOT = Path(f"{COMPANY}_{CODE}_券商深度报告_3份")
REPORT_DIR = ROOT / "01_券商深度报告"
VERIFY_DIR = Path("_verify_guowang_xintong")
ZIP_NAME = f"{COMPANY}_{CODE}_券商深度报告_3份_20261004.zip"

for directory in (REPORT_DIR, VERIFY_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Referer": "https://data.eastmoney.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})

PREFERRED = [
    {
        "title_contains": "电力数字化行业龙头，有望受益于算力集群电能需求",
        "institution": "西部证券",
        "date": "2024-06-05",
        "note": "首次覆盖长篇报告，系统分析电力数字化业务、算力集群电能需求、盈利预测与估值。",
    },
    {
        "title_contains": "国网系能源IT龙头，电网国企改革前线",
        "institution": "东吴证券",
        "date": "2024-12-03",
        "note": "公司深度研究，覆盖能源IT业务、信息化投入、核心壁垒及国企改革逻辑。",
    },
    {
        "title_contains": "电网数字化建设核心受益，能源互联网打造第二增长极",
        "institution": "中泰证券",
        "date": "2024-12-11",
        "note": "首次覆盖公司深度报告，分析电网数字化、能源互联网第二增长曲线与估值。",
    },
]


def request_with_retry(url: str, **kwargs: Any) -> requests.Response:
    last: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = SESSION.get(url, timeout=(20, 180), allow_redirects=True, **kwargs)
            print("HTTP", attempt, response.status_code, response.headers.get("content-type"), len(response.content), response.url, flush=True)
            if response.status_code in {429, 500, 502, 503, 504}:
                time.sleep(attempt * 2)
                continue
            response.raise_for_status()
            return response
        except Exception as exc:
            last = exc
            if attempt == 5:
                break
            time.sleep(attempt * 2)
    raise RuntimeError(f"Request failed: {url}: {last}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value or "")
    value = html.unescape(value)
    return re.sub(r"\s+", "", value)


def query_reports() -> list[dict[str, Any]]:
    url = "https://reportapi.eastmoney.com/report/list"
    params = {
        "industryCode": "*",
        "pageSize": 100,
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": "2020-01-01",
        "endTime": AS_OF,
        "pageNo": 1,
        "fields": "",
        "qType": 0,
        "orgCode": "",
        "code": CODE,
        "rcode": "",
        "p": 1,
        "pageNum": 1,
        "pageNumber": 1,
    }
    response = request_with_retry(url, params=params, headers={"Referer": f"https://data.eastmoney.com/report/{CODE}.html"})
    data = response.json()
    rows = data.get("data") or []
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("list") or []
    rows = list(rows)
    print("REPORT_COUNT", len(rows), flush=True)
    for row in rows:
        print("REPORT_META", json.dumps(row, ensure_ascii=False), flush=True)
    return rows


def extract_detail(info_code: str) -> dict[str, str]:
    detail_url = f"https://data.eastmoney.com/report/info/{info_code}.html"
    response = request_with_retry(detail_url)
    text = response.text
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S | re.I)
    title = clean_text(title_match.group(1)) if title_match else ""
    spans = [clean_text(item) for item in re.findall(r"<span[^>]*>(.*?)</span>", text, re.S | re.I)]
    pdfs = re.findall(r'href=["\'](https?://[^"\']+\.pdf[^"\']*)["\']', text, re.I)
    if not pdfs:
        raise RuntimeError(f"No PDF link on detail page: {info_code}")
    pdf_url = pdfs[0].split("?", 1)[0]
    return {"detail_url": detail_url, "pdf_url": pdf_url, "page_title": title, "spans": " | ".join(spans[:30])}


def choose_reports(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    for preferred in PREFERRED:
        matches = []
        for row in rows:
            title = clean_text(str(row.get("title") or ""))
            institution = clean_text(str(row.get("orgSName") or row.get("orgName") or ""))
            publish_date = str(row.get("publishDate") or "")[:10]
            if clean_text(preferred["title_contains"]) in title:
                matches.append(row)
            elif preferred["institution"] in institution and publish_date == preferred["date"]:
                matches.append(row)
        if not matches:
            raise RuntimeError(f"Preferred report not found: {preferred}")
        matches.sort(key=lambda row: int(row.get("attachPages") or 0), reverse=True)
        item = dict(matches[0])
        item["selection_note"] = preferred["note"]
        chosen.append(item)
    return chosen


def validate_pdf(path: Path, expected_pages: int | None = None) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 10:
        raise RuntimeError(f"Not a deep/long report: {path.name}, pages={pages}")
    if expected_pages and abs(pages - expected_pages) > 1:
        raise RuntimeError(f"Page mismatch: {path.name}, actual={pages}, indexed={expected_pages}")

    sampled = []
    for idx in sorted(set([0, 1, min(2, pages - 1), pages - 1])):
        try:
            sampled.append(reader.pages[idx].extract_text() or "")
        except Exception:
            pass
    sample_text = "\n".join(sampled).lower()
    if len(sample_text.strip()) > 200 and not any(term in sample_text for term in ("国网信通", "600131", "state grid information", "sgitic")):
        raise RuntimeError(f"Company identity not found in PDF sample: {path.name}")

    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=120)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed: {path.name}\n{qpdf.stdout}\n{qpdf.stderr}")

    for page_num, suffix in ((1, "first"), (pages, "last")):
        base = VERIFY_DIR / f"{path.stem}_{suffix}"
        result = subprocess.run([
            "pdftoppm", "-png", "-r", "72", "-f", str(page_num), "-l", str(page_num),
            "-singlefile", str(path), str(base)
        ], capture_output=True, text=True, timeout=180)
        png = Path(str(base) + ".png")
        if result.returncode != 0 or not png.exists() or png.stat().st_size < 1000:
            raise RuntimeError(f"Render failed: {path.name} page {page_num}: {result.stderr}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "first_last_page_rendered": True,
        "identity_text_verified_when_extractable": True,
    }


def safe_filename(value: str) -> str:
    value = value.replace("/", "_").replace("\\", "_").replace(":", "：")
    return re.sub(r"[\x00-\x1f]", "", value).strip()


def main() -> None:
    rows = query_reports()
    selected = choose_reports(rows)
    records: list[dict[str, Any]] = []

    for row in selected:
        info_code = str(row.get("infoCode") or "")
        if not info_code:
            raise RuntimeError(f"Missing infoCode: {row}")
        detail = extract_detail(info_code)
        title = clean_text(str(row.get("title") or detail["page_title"]))
        institution = clean_text(str(row.get("orgSName") or row.get("orgName") or "未知机构"))
        publish_date = str(row.get("publishDate") or "")[:10]
        analysts = str(row.get("researcher") or "").replace(",", "、")
        rating = str(row.get("emRatingName") or row.get("sRatingName") or "未列示")
        filename = safe_filename(f"{publish_date.replace('-', '')}_{institution}_{title}.pdf")
        destination = REPORT_DIR / filename

        response = request_with_retry(detail["pdf_url"], headers={"Referer": detail["detail_url"], "Accept": "application/pdf,*/*"})
        if not response.content.startswith(b"%PDF"):
            raise RuntimeError(f"Not a PDF: {detail['pdf_url']}")
        destination.write_bytes(response.content)
        validation = validate_pdf(destination, int(row.get("attachPages") or 0) or None)

        record = {
            "relative_path": destination.relative_to(ROOT).as_posix(),
            "filename": filename,
            "company": COMPANY,
            "stock_code": CODE,
            "publish_date": publish_date,
            "institution": institution,
            "analysts": analysts,
            "rating": rating,
            "title": title,
            "info_code": info_code,
            "detail_url": detail["detail_url"],
            "pdf_url": detail["pdf_url"],
            "indexed_pages": int(row.get("attachPages") or 0),
            "selection_note": row["selection_note"],
            "source": "东方财富研报中心公开PDF端点",
            **validation,
        }
        records.append(record)
        print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

    if len(records) != 3:
        raise RuntimeError(f"Expected 3 reports, got {len(records)}")
    if len({r["sha256"] for r in records}) != 3:
        raise RuntimeError("Duplicate report files detected")

    readme = f"""国网信息通信股份有限公司（国网信通，{CODE}）券商深度报告文件包

资料整理日期：{AS_OF}

收录范围：公开可直接下载、来源可核验、篇幅达到10页以上的公司深度或首次覆盖报告，共3份。
来源：东方财富研报中心公开PDF端点。未绕过登录、会员或付费限制。
用途：仅供个人研究参考，版权归报告出具机构及作者所有，不构成投资建议。

文件列表：
""" + "\n".join(
        f"{idx}. {r['publish_date']}｜{r['institution']}｜{r['title']}｜{r['pages']}页｜{r['rating']}"
        for idx, r in enumerate(records, start=1)
    ) + "\n"
    (ROOT / "00_文件清单与来源说明.txt").write_text(readme, encoding="utf-8")

    with (ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["relative_path", "publish_date", "institution", "analysts", "rating", "title", "pages", "bytes", "sha256", "detail_url", "pdf_url", "selection_note"]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    (ROOT / "manifest.json").write_text(json.dumps({
        "company": COMPANY,
        "stock_code": CODE,
        "as_of": AS_OF,
        "document_count": len(records),
        "documents": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "SHA256SUMS.txt").write_text("\n".join(f"{r['sha256']}  {r['relative_path']}" for r in records) + "\n", encoding="utf-8")

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


if __name__ == "__main__":
    main()
