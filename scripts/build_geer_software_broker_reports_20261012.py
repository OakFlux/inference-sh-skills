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

COMPANY = "格尔软件"
CODE = "603232"
AS_OF = "2026-10-12"
ROOT = Path(f"{COMPANY}_{CODE}_券商研究报告")
REPORT_DIR = ROOT / "01_券商研究报告"
VERIFY_DIR = Path("_verify_geer_broker_reports")
TEMP_DIR = Path("_geer_broker_candidate_pdfs")
for directory in (REPORT_DIR, VERIFY_DIR, TEMP_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/155.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://data.eastmoney.com/",
})

PREFERRED = {
    "AP202103011466634572": 500,
    "AP202205041563510402": 280,
    "AP202110311526086255": 80,
    "AP202109061514608895": 80,
    "AP202010291424532783": 60,
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def get(url: str, *, params: dict[str, Any] | None = None, referer: str | None = None) -> requests.Response:
    last: Exception | None = None
    headers = {"Referer": referer} if referer else None
    for attempt in range(1, 6):
        try:
            r = SESSION.get(url, params=params, headers=headers, timeout=(20, 180), allow_redirects=True)
            print("HTTP", attempt, r.status_code, r.headers.get("content-type"), len(r.content), r.url, flush=True)
            if r.status_code in {429, 500, 502, 503, 504}:
                time.sleep(attempt * 2)
                continue
            return r
        except Exception as exc:
            last = exc
            if attempt < 5:
                time.sleep(attempt * 2)
    raise RuntimeError(f"GET failed: {url}: {last}")


def as_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except Exception:
        return 0


def date_only(value: Any) -> str:
    text = str(value or "")
    match = re.search(r"20\d{2}-\d{2}-\d{2}", text)
    return match.group(0) if match else text[:10]


def fetch_reports() -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(1, 6):
        params = {
            "industryCode": "*", "pageSize": "100", "industry": "*",
            "rating": "*", "ratingChange": "*", "beginTime": "2017-01-01",
            "endTime": AS_OF, "pageNo": str(page), "fields": "", "qType": "0",
            "orgCode": "", "code": CODE, "rcode": "", "p": str(page),
            "pageNum": str(page), "pageNumber": str(page),
        }
        r = get("https://reportapi.eastmoney.com/report/list", params=params)
        r.raise_for_status()
        payload = r.json()
        rows = payload.get("data") or payload.get("Data") or []
        print("REPORT_PAGE", page, len(rows), payload.get("hits"), payload.get("TotalPage"), flush=True)
        if not rows:
            break
        for row in rows:
            code = str(row.get("infoCode") or row.get("info_code") or "")
            if not code or code in seen:
                continue
            seen.add(code)
            report = {
                "info_code": code,
                "title": str(row.get("title") or "").strip(),
                "publish_date": date_only(row.get("publishDate") or row.get("publish_date")),
                "institution": str(row.get("orgSName") or row.get("orgName") or row.get("org_name") or "").strip(),
                "analyst": str(row.get("researcher") or row.get("researcherName") or row.get("author") or "").strip(),
                "rating": str(row.get("emRatingName") or row.get("rating") or "").strip(),
                "attach_pages": as_int(row.get("attachPages") or row.get("attach_pages")),
                "attach_size": as_int(row.get("attachSize") or row.get("attach_size")),
            }
            reports.append(report)
            print("META", json.dumps(report, ensure_ascii=False), flush=True)
        if len(rows) < 100:
            break
        time.sleep(0.6)
    if not reports:
        raise RuntimeError("No report metadata returned")
    return reports


def score(report: dict[str, Any]) -> int:
    title = report["title"]
    pages = int(report.get("attach_pages") or 0)
    value = pages * 8 + PREFERRED.get(report["info_code"], 0)
    if any(k in title for k in ("深度", "首次覆盖", "新股", "公司研究", "投资价值")):
        value += 350
    if any(k in title for k in ("PKI霸主", "PKI龙头", "成长空间", "增长动力")):
        value += 180
    if pages >= 20:
        value += 220
    elif pages >= 12:
        value += 100
    if any(k in title for k in ("季报", "年报点评", "中报点评", "业绩点评", "快报", "简评")):
        value -= 180
    return value


def safe_name(text: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]", "_", text)
    return re.sub(r"\s+", "", text)[:110].strip("._")


def download_pdf(report: dict[str, Any]) -> tuple[Path, str, str]:
    info = report["info_code"]
    detail_url = f"https://data.eastmoney.com/report/info/{info}.html"
    detail = get(detail_url)
    detail.raise_for_status()
    if COMPANY not in detail.text or CODE not in detail.text:
        raise RuntimeError(f"Detail identity failed: {info}")
    if report["institution"] and report["institution"] not in detail.text:
        raise RuntimeError(f"Institution identity failed: {info}")

    explicit = re.findall(r"https?://[^\"']+\.pdf(?:\?[^\"']*)?", detail.text, flags=re.I)
    generated = [
        f"https://pdf.dfcfw.com/pdf/{prefix}_{info}{suffix}"
        for prefix in ("H3", "H1", "H2", "H4", "H5", "H0")
        for suffix in ("_1.pdf", "_2.pdf", "_0.pdf")
    ]
    urls: list[str] = []
    for url in explicit + generated:
        if url not in urls:
            urls.append(url)
    for url in urls:
        r = get(url, referer=detail_url)
        if r.status_code == 200 and r.content.startswith(b"%PDF") and len(r.content) > 100_000:
            path = TEMP_DIR / f"{info}.pdf"
            path.write_bytes(r.content)
            return path, r.url, detail_url
    raise RuntimeError(f"No public PDF: {info}")


def inspect(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 8:
        raise RuntimeError(f"Too short: {pages} pages")
    texts: list[str] = []
    for index in sorted(set([0, 1, min(2, pages - 1), pages - 1])):
        try:
            texts.append(reader.pages[index].extract_text() or "")
        except Exception:
            pass
    sample = "\n".join(texts)
    company_ok = COMPANY in sample or CODE in sample
    institution_ok = not report["institution"] or report["institution"] in sample
    if len(sample.strip()) > 300 and not company_ok:
        raise RuntimeError("Company text absent")
    if len(sample.strip()) > 300 and not institution_ok:
        raise RuntimeError("Institution text absent")

    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=180)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed: {qpdf.stderr}")
    for page_no, label in ((1, "first"), (pages, "last")):
        base = VERIFY_DIR / f"{path.stem}_{label}"
        result = subprocess.run([
            "pdftoppm", "-png", "-r", "72", "-f", str(page_no), "-l", str(page_no),
            "-singlefile", str(path), str(base),
        ], capture_output=True, text=True, timeout=180)
        png = Path(str(base) + ".png")
        if result.returncode != 0 or not png.exists() or png.stat().st_size < 1000:
            raise RuntimeError(f"Render failed: page {page_no}")
    return {
        "pages": pages, "bytes": path.stat().st_size, "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode, "first_last_page_rendered": True,
        "company_text_verified_when_extractable": bool(company_ok or len(sample.strip()) <= 300),
        "institution_text_verified_when_extractable": bool(institution_ok or len(sample.strip()) <= 300),
    }


def select(valid: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid.sort(key=lambda x: (score(x), int(x["pages"]), x["publish_date"]), reverse=True)
    selected: list[dict[str, Any]] = []
    institutions: set[str] = set()
    for item in valid:
        institution = item["institution"] or "未知机构"
        if institution in institutions:
            continue
        selected.append(item)
        institutions.add(institution)
        if len(selected) == 3:
            break
    for item in valid:
        if len(selected) == 3:
            break
        if item["info_code"] not in {x["info_code"] for x in selected}:
            selected.append(item)
    if len(selected) < 2:
        raise RuntimeError(f"Only {len(selected)} qualifying reports")
    return selected


def main() -> None:
    reports = fetch_reports()
    ranked = sorted(reports, key=score, reverse=True)
    pool: list[dict[str, Any]] = []
    for report in [r for r in reports if r["info_code"] in PREFERRED] + ranked[:20]:
        if report["info_code"] not in {x["info_code"] for x in pool}:
            pool.append(report)

    valid: list[dict[str, Any]] = []
    for report in pool:
        try:
            path, pdf_url, detail_url = download_pdf(report)
            metadata = inspect(path, report)
            item = {**report, **metadata, "temp_path": path, "pdf_url": pdf_url, "detail_url": detail_url}
            valid.append(item)
            print("VALID", json.dumps(item, ensure_ascii=False, default=str), flush=True)
        except Exception as exc:
            print("FAILED", report["info_code"], repr(exc), flush=True)
        if len(valid) >= 10:
            break

    chosen = select(valid)
    records: list[dict[str, Any]] = []
    for rank, item in enumerate(chosen, 1):
        filename = f"{rank:02d}_{item['publish_date'].replace('-', '')}_{item['institution']}_{safe_name(item['title'])}.pdf"
        destination = REPORT_DIR / filename
        shutil.copy2(item["temp_path"], destination)
        records.append({
            "relative_path": destination.relative_to(ROOT).as_posix(),
            "filename": destination.name, "company": COMPANY, "stock_code": CODE,
            "publish_date": item["publish_date"], "institution": item["institution"],
            "analyst": item["analyst"], "title": item["title"], "rating": item["rating"],
            "info_code": item["info_code"], "detail_url": item["detail_url"],
            "pdf_url": item["pdf_url"], "source": "东方财富研报中心公开历史档案及公开PDF端点",
            "pages": item["pages"], "bytes": destination.stat().st_size,
            "sha256": sha256_file(destination), "qpdf_return_code": item["qpdf_return_code"],
            "first_last_page_rendered": True,
        })

    lines = [
        f"{COMPANY}（{CODE}）券商研究报告精选包", "", f"资料整理日期：{AS_OF}", "",
        "仅收录可公开取得的完整PDF；优先选取首次覆盖、公司深度或篇幅较长、分析框架完整的报告。", "",
        "收录文件：",
    ]
    lines += [f"- {r['publish_date']}｜{r['institution']}｜{r['title']}｜{r['pages']}页" for r in records]
    lines += ["", "已校验PDF文件头、实际页数、公司及券商身份、qpdf结构、首末页渲染和ZIP CRC。",
              "报告版权归相应证券研究机构及作者所有，仅供个人研究参考，不构成投资建议。"]
    (ROOT / "00_文件清单与来源说明.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    with (ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["relative_path", "publish_date", "institution", "analyst", "title", "rating", "pages", "bytes", "sha256", "info_code", "detail_url", "pdf_url", "source"]
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(records)

    (ROOT / "manifest.json").write_text(json.dumps({
        "company": COMPANY, "stock_code": CODE, "as_of": AS_OF,
        "selection_method": "公开完整PDF中按深度适配、页数、机构差异和日期精选2至3份",
        "documents": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "SHA256SUMS.txt").write_text("\n".join(f"{r['sha256']}  {r['relative_path']}" for r in records) + "\n", encoding="utf-8")

    count = len(records)
    zip_path = Path(f"{COMPANY}_{CODE}_券商研究报告_{count}份_20261012.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=f"{ROOT.name}/{path.relative_to(ROOT).as_posix()}")
    with zipfile.ZipFile(zip_path, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failed: {bad}")
        if sum(name.lower().endswith(".pdf") for name in archive.namelist()) != count:
            raise RuntimeError("ZIP PDF count mismatch")
    print("FINAL_ZIP", zip_path.name, zip_path.stat().st_size, sha256_file(zip_path), flush=True)
    print("FINAL_RECORDS", json.dumps(records, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
