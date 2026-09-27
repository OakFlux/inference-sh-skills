from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

PACKAGE = "中国能源建设_03996_601868_2020-2025年报_2026最新定期报告"
ROOT = Path(PACKAGE)
ANNUAL = ROOT / "01_年度报告"
LATEST = ROOT / "02_最新定期报告"
NOTES = ROOT / "03_说明与校验"
WORK = Path("_ceec_work")
RENDER = WORK / "renders"
for d in (ANNUAL, LATEST, NOTES, RENDER):
    d.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
SEARCH_URL = "https://www1.hkexnews.hk/search/titlesearch.xhtml"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def request(url: str, *, params: dict | None = None, stream: bool = False, timeout=(15, 180)) -> requests.Response:
    candidates = [url]
    if "www1.hkexnews.hk" in url:
        candidates.append(url.replace("www1.hkexnews.hk", "www.hkexnews.hk"))
    elif "www.hkexnews.hk" in url:
        candidates.append(url.replace("www.hkexnews.hk", "www1.hkexnews.hk"))
    errors: list[str] = []
    for candidate in dict.fromkeys(candidates):
        for attempt in range(1, 6):
            try:
                headers = dict(HEADERS)
                headers["Referer"] = "https://www1.hkexnews.hk/"
                r = SESSION.get(candidate, params=params, headers=headers, timeout=timeout, stream=stream, allow_redirects=True)
                print("GET", candidate, "attempt", attempt, "status", r.status_code, "type", r.headers.get("content-type"), "bytes", r.headers.get("content-length"), "final", r.url, flush=True)
                r.raise_for_status()
                return r
            except Exception as exc:
                errors.append(f"{candidate} attempt {attempt}: {exc!r}")
                time.sleep(min(attempt * 2, 8))
    raise RuntimeError(f"request failed for {url}: {errors[-8:]}")


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", text.lower())


def title_matches(text: str, kind: str, year: int) -> bool:
    n = normalize(text)
    if kind == "annual":
        patterns = [
            normalize(f"{year}年度報告"), normalize(f"{year}年度报告"),
            normalize(f"Annual Report {year}"), normalize(f"{year} Annual Report"),
        ]
        return any(p in n for p in patterns) and "resultsannouncement" not in n and "業績公告" not in n and "业绩公告" not in n
    if kind == "q1":
        patterns = [
            normalize(f"{year}年第一季度報告"), normalize(f"{year}年第一季度报告"),
            normalize(f"{year} First Quarterly Report"), normalize(f"First Quarterly Report {year}"),
        ]
        return any(p in n for p in patterns)
    if kind == "interim":
        patterns = [
            normalize(f"{year}年中期報告"), normalize(f"{year}年半年度報告"),
            normalize(f"{year} Interim Report"), normalize(f"Interim Report {year}"),
        ]
        return any(p in n for p in patterns) and "resultsannouncement" not in n and "業績公告" not in n and "业绩公告" not in n
    return False


def scrape_search(start: str, end: str, lang: str) -> tuple[str, list[dict]]:
    params = {
        "category": "0",
        "market": "SEHK",
        "stockId": "134401",
        "lang": lang,
        "from": start,
        "to": end,
    }
    r = request(SEARCH_URL, params=params, stream=False, timeout=(15, 120))
    try:
        html = r.text
        final_url = str(r.url)
    finally:
        r.close()
    soup = BeautifulSoup(html, "html.parser")
    links: list[dict] = []
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(" ", strip=True).split())
        if not text:
            continue
        href = urljoin(final_url, a["href"])
        if "hkexnews.hk" not in href:
            continue
        links.append({"text": text, "url": href})
    print("SEARCH", start, end, lang, "links", len(links), flush=True)
    for item in links:
        if any(k in normalize(item["text"]) for k in ("annualreport", "年度報告", "年度报告", "quarterlyreport", "季度報告", "季度报告", "interimreport", "中期報告", "半年度报告")):
            print("CANDIDATE", json.dumps(item, ensure_ascii=False), flush=True)
    return final_url, links


def discover(target: dict) -> dict:
    all_candidates: list[dict] = []
    search_urls: list[str] = []
    for lang in ("ZH", "EN"):
        search_url, links = scrape_search(target["from"], target["to"], lang)
        search_urls.append(search_url)
        for item in links:
            if title_matches(item["text"], target["kind"], target["year"]):
                entry = dict(item)
                entry["lang"] = lang
                all_candidates.append(entry)
        if all_candidates:
            break
    if not all_candidates:
        raise RuntimeError(f"No matching HKEX document for {target['label']} in {target['from']}..{target['to']}")
    # Prefer a direct PDF and Chinese-language title where available.
    all_candidates.sort(key=lambda x: (0 if x["url"].lower().split("?")[0].endswith(".pdf") else 1, 0 if x["lang"] == "ZH" else 1, len(x["text"])))
    chosen = all_candidates[0]
    chosen["search_urls"] = search_urls
    print("CHOSEN", target["label"], json.dumps(chosen, ensure_ascii=False), flush=True)
    return chosen


def resolve_pdf(url: str, title: str) -> str:
    if url.lower().split("?")[0].endswith(".pdf"):
        return url
    # Some HKEX multi-file landing pages contain a consolidated PDF; use it if present.
    r = request(url, stream=False, timeout=(15, 120))
    try:
        html = r.text
        final_url = str(r.url)
    finally:
        r.close()
    soup = BeautifulSoup(html, "html.parser")
    pdfs = []
    for a in soup.find_all("a", href=True):
        href = urljoin(final_url, a["href"])
        text = " ".join(a.get_text(" ", strip=True).split())
        if href.lower().split("?")[0].endswith(".pdf"):
            pdfs.append((text, href))
    if not pdfs:
        raise RuntimeError(f"Landing page has no PDF for {title}: {url}")
    # Prefer a link whose label resembles the report title, otherwise the largest-looking full-report link.
    pdfs.sort(key=lambda x: (0 if any(k in normalize(x[0]) for k in ("annualreport", "年度報告", "年度报告", "quarterlyreport", "季度報告", "interimreport", "中期報告")) else 1, len(x[0])))
    return pdfs[0][1]


def download_pdf(url: str, dest: Path) -> str:
    r = request(url, stream=True, timeout=(20, 300))
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with tmp.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
        final_url = str(r.url)
    finally:
        r.close()
    data = tmp.read_bytes()[:8]
    if tmp.stat().st_size < 30_000 or not data.startswith(b"%PDF-"):
        raise RuntimeError(f"Invalid PDF download for {dest}: size={tmp.stat().st_size}, head={data!r}")
    tmp.replace(dest)
    return final_url


def validate_pdf(path: Path, min_pages: int) -> dict:
    q = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True)
    if q.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {q.stderr[-2000:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"Unexpectedly short report {path.name}: {pages} pages")
    check_pages = [1] + ([pages] if pages > 1 else [])
    for page in check_pages:
        prefix = RENDER / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{page}"
        p = subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", "72", "-png", "-singlefile", str(path), str(prefix)], capture_output=True, text=True, timeout=180)
        png = Path(str(prefix) + ".png")
        if p.returncode != 0 or not png.exists() or png.stat().st_size < 800:
            raise RuntimeError(f"Render validation failed for {path.name} page {page}: {p.stderr[-1000:]}")
        png.unlink()
    sample = ""
    try:
        indices = list(range(min(5, pages)))
        if pages > 5:
            indices.append(pages - 1)
        sample = "\n".join((reader.pages[i].extract_text() or "") for i in indices)
    except Exception as exc:
        print("TEXT_EXTRACTION_WARNING", path.name, repr(exc), flush=True)
    identity = any(x.lower() in sample.lower() for x in ("中国能源建设", "中國能源建設", "China Energy Engineering", "601868", "03996"))
    if sample.strip() and not identity:
        raise RuntimeError(f"Issuer identity check failed for {path.name}")
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": q.returncode,
        "render_verified_first_and_last_page": True,
        "issuer_identity_verified_when_text_extractable": identity,
    }


TARGETS = [
    {"label": "2020年年度报告", "kind": "annual", "year": 2020, "from": "20210301", "to": "20210531", "dest": ANNUAL / "2020_中国能源建设_年度报告_港交所官方.pdf", "min_pages": 100},
    {"label": "2021年年度报告", "kind": "annual", "year": 2021, "from": "20220301", "to": "20220531", "dest": ANNUAL / "2021_中国能源建设_年度报告_港交所官方.pdf", "min_pages": 100},
    {"label": "2022年年度报告", "kind": "annual", "year": 2022, "from": "20230301", "to": "20230531", "dest": ANNUAL / "2022_中国能源建设_年度报告_港交所官方.pdf", "min_pages": 100},
    {"label": "2023年年度报告", "kind": "annual", "year": 2023, "from": "20240301", "to": "20240531", "dest": ANNUAL / "2023_中国能源建设_年度报告_港交所官方.pdf", "min_pages": 100},
    {"label": "2024年年度报告", "kind": "annual", "year": 2024, "from": "20250301", "to": "20250531", "dest": ANNUAL / "2024_中国能源建设_年度报告_港交所官方.pdf", "min_pages": 100},
    {"label": "2025年年度报告", "kind": "annual", "year": 2025, "from": "20260301", "to": "20260531", "dest": ANNUAL / "2025_中国能源建设_年度报告_港交所官方.pdf", "min_pages": 100},
    {"label": "2026年第一季度报告", "kind": "q1", "year": 2026, "from": "20260401", "to": "20260515", "dest": LATEST / "2026_中国能源建设_第一季度报告_港交所官方.pdf", "min_pages": 5},
    {"label": "2026年半年度报告", "kind": "interim", "year": 2026, "from": "20260801", "to": "20260927", "dest": LATEST / "2026_中国能源建设_半年度报告_港交所官方.pdf", "min_pages": 30},
]

records: list[dict] = []
seen_hashes: set[str] = set()
for target in TARGETS:
    found = discover(target)
    pdf_url = resolve_pdf(found["url"], target["label"])
    final_url = download_pdf(pdf_url, target["dest"])
    meta = validate_pdf(target["dest"], target["min_pages"])
    if meta["sha256"] in seen_hashes:
        raise RuntimeError(f"Duplicate report detected: {target['dest'].name}")
    seen_hashes.add(meta["sha256"])
    rec = {
        "label": target["label"],
        "document_type": "年度报告" if target["kind"] == "annual" else ("第一季度报告" if target["kind"] == "q1" else "半年度报告"),
        "fiscal_year": target["year"],
        "relative_path": str(target["dest"].relative_to(ROOT)),
        "title_on_hkex": found["text"],
        "language_index": found["lang"],
        "hkex_search_urls": found["search_urls"],
        "source_url": final_url,
        "source": "香港交易所披露易（HKEXnews）",
        **meta,
    }
    records.append(rec)
    print("VALIDATED", json.dumps(rec, ensure_ascii=False), flush=True)

manifest = {
    "package_name": PACKAGE,
    "issuer": "中国能源建设股份有限公司",
    "securities": {"A_share": "601868", "H_share": "03996"},
    "checked_as_of": "2026-09-27",
    "coverage": "2020—2025年度报告、2026年第一季度报告及披露时间更晚的2026年半年度报告",
    "report_count": len(records),
    "records": records,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (ROOT / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["文件", "类型", "年度", "页数", "字节数", "SHA-256", "来源网址"])
    for r in records:
        w.writerow([r["relative_path"], r["document_type"], r["fiscal_year"], r["pages"], r["bytes"], r["sha256"], r["source_url"]])

readme = f"""中国能源建设股份有限公司官方定期报告文件包

证券代码：A股601868；H股03996
核对日期：2026年9月27日

收录范围：
- 2020—2025年度报告，共6份；
- 2026年第一季度报告：截至核对日的最新季度报告；
- 2026年半年度报告：披露时间晚于第一季度报告，作为最新财务信息补充收录。

文件来源：香港交易所披露易（HKEXnews）正式披露PDF。
报告数量：{len(records)}份。

校验：
- 所有PDF均检查文件头、页数及qpdf结构；
- 所有PDF均完成首末页渲染检查；
- 文本可提取时，核验发行人名称或证券代码；
- manifest.json与文件清单.csv记录来源、页数、大小及SHA-256；
- SHA256SUMS.txt可用于完整性复核。
"""
(ROOT / "00_文件清单与范围说明.txt").write_text(readme, encoding="utf-8")

sums = []
for p in sorted(ROOT.rglob("*")):
    if p.is_file() and p.name != "SHA256SUMS.txt":
        sums.append(f"{sha256(p)}  {p.relative_to(ROOT)}")
(ROOT / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")

zip_path = Path(PACKAGE + ".zip")
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
    for p in sorted(ROOT.rglob("*")):
        if p.is_file():
            z.write(p, arcname=str(Path(PACKAGE) / p.relative_to(ROOT)))
with zipfile.ZipFile(zip_path, "r") as z:
    bad = z.testzip()
    if bad:
        raise RuntimeError(f"ZIP CRC failure: {bad}")
print("FINAL_ZIP", zip_path, zip_path.stat().st_size, sha256(zip_path), flush=True)
