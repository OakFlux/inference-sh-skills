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
WORK = Path("_ceec_v2_work")
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


def request(url: str, *, params: dict | None = None, stream: bool = False, timeout=(15, 240)) -> requests.Response:
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
                time.sleep(min(2 * attempt, 8))
    raise RuntimeError(f"request failed for {url}: {errors[-8:]}")


def download_pdf(url: str, dest: Path) -> str:
    r = request(url, stream=True, timeout=(20, 360))
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.unlink(missing_ok=True)
    try:
        with tmp.open("wb") as fh:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    fh.write(chunk)
        final_url = str(r.url)
    finally:
        r.close()
    head = tmp.read_bytes()[:8]
    if tmp.stat().st_size < 30_000 or not head.startswith(b"%PDF-"):
        raise RuntimeError(f"invalid PDF for {dest.name}: size={tmp.stat().st_size}, head={head!r}")
    tmp.replace(dest)
    return final_url


def validate_pdf(path: Path, min_pages: int) -> dict:
    q = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True)
    if q.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {q.stderr[-2000:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"unexpectedly short report {path.name}: {pages} pages")
    for page in [1] + ([pages] if pages > 1 else []):
        prefix = RENDER / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{page}"
        proc = subprocess.run(
            ["pdftoppm", "-f", str(page), "-l", str(page), "-r", "72", "-png", "-singlefile", str(path), str(prefix)],
            capture_output=True, text=True, timeout=180,
        )
        png = Path(str(prefix) + ".png")
        if proc.returncode != 0 or not png.exists() or png.stat().st_size < 800 or not png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError(f"render validation failed for {path.name} page {page}: {proc.stderr[-1000:]}")
        png.unlink()
    sample = ""
    try:
        idx = list(range(min(6, pages)))
        if pages > 6:
            idx.append(pages - 1)
        sample = "\n".join((reader.pages[i].extract_text() or "") for i in idx)
    except Exception as exc:
        print("TEXT_EXTRACTION_WARNING", path.name, repr(exc), flush=True)
    identity = any(x.lower() in sample.lower() for x in ("中国能源建设", "中國能源建設", "China Energy Engineering", "601868", "03996"))
    if sample.strip() and not identity:
        raise RuntimeError(f"issuer identity check failed for {path.name}")
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": q.returncode,
        "render_verified_first_and_last_page": True,
        "issuer_identity_verified_when_text_extractable": identity,
    }


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", text.lower())


def discover_2026_interim() -> dict:
    candidates: list[dict] = []
    search_urls: list[str] = []
    for lang in ("ZH", "EN"):
        params = {
            "category": "0",
            "market": "SEHK",
            "stockId": "134401",
            "lang": lang,
            "from": "20260801",
            "to": "20260927",
        }
        r = request(SEARCH_URL, params=params, stream=False, timeout=(15, 120))
        try:
            html = r.text
            final_url = str(r.url)
        finally:
            r.close()
        search_urls.append(final_url)
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            text = " ".join(a.get_text(" ", strip=True).split())
            href = urljoin(final_url, a["href"])
            n = normalize(text)
            if "hkexnews.hk" not in href:
                continue
            is_interim = ("中期報告" in text or "中期报告" in text or "半年度報告" in text or "半年度报告" in text or "interimreport" in n)
            is_results = any(term in n for term in ("resultsannouncement", "interimresults", "業績公告", "业绩公告"))
            if is_interim and not is_results:
                candidates.append({"title": text, "url": href, "language_index": lang})
                print("INTERIM_CANDIDATE", json.dumps(candidates[-1], ensure_ascii=False), flush=True)
    if not candidates:
        raise RuntimeError("No 2026 interim report found in HKEX title search")
    # Prefer Chinese direct PDF, then English direct PDF.
    candidates.sort(key=lambda x: (0 if x["language_index"] == "ZH" else 1, 0 if x["url"].lower().split("?")[0].endswith(".pdf") else 1, len(x["title"])))
    chosen = candidates[0]
    chosen["search_urls"] = search_urls
    if not chosen["url"].lower().split("?")[0].endswith(".pdf"):
        r = request(chosen["url"], stream=False, timeout=(15, 120))
        try:
            html = r.text
            final_url = str(r.url)
        finally:
            r.close()
        soup = BeautifulSoup(html, "html.parser")
        pdf_links = [urljoin(final_url, a["href"]) for a in soup.find_all("a", href=True) if urljoin(final_url, a["href"]).lower().split("?")[0].endswith(".pdf")]
        if not pdf_links:
            raise RuntimeError(f"interim report landing page has no PDF: {chosen['url']}")
        chosen["url"] = pdf_links[0]
    print("INTERIM_CHOSEN", json.dumps(chosen, ensure_ascii=False), flush=True)
    return chosen


# Direct official HKEX URLs identified from the issuer-filtered title search.
TARGETS = [
    {"label": "2020年年度报告", "type": "年度报告", "year": 2020, "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2021/0420/2021042000454_c.pdf", "dest": ANNUAL / "2020_中国能源建设_年度报告_港交所官方.pdf", "min_pages": 100},
    {"label": "2021年年度报告", "type": "年度报告", "year": 2021, "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2022/0413/2022041301325_c.pdf", "dest": ANNUAL / "2021_中国能源建设_年度报告_港交所官方.pdf", "min_pages": 100},
    {"label": "2022年年度报告", "type": "年度报告", "year": 2022, "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2023/0406/2023040601567_c.pdf", "dest": ANNUAL / "2022_中国能源建设_年度报告_港交所官方.pdf", "min_pages": 100},
    {"label": "2023年年度报告", "type": "年度报告", "year": 2023, "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2024/0411/2024041100832_c.pdf", "dest": ANNUAL / "2023_中国能源建设_年度报告_港交所官方.pdf", "min_pages": 100},
    {"label": "2024年年度报告", "type": "年度报告", "year": 2024, "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0416/2025041601261_c.pdf", "dest": ANNUAL / "2024_中国能源建设_年度报告_港交所官方.pdf", "min_pages": 100},
    {"label": "2025年年度报告", "type": "年度报告", "year": 2025, "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0417/2026041701962_c.pdf", "dest": ANNUAL / "2025_中国能源建设_年度报告_港交所官方.pdf", "min_pages": 100},
    {"label": "2026年第一季度报告", "type": "第一季度报告", "year": 2026, "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0429/2026042905209_c.pdf", "dest": LATEST / "2026_中国能源建设_第一季度报告_港交所官方.pdf", "min_pages": 5},
]

records: list[dict] = []
seen_hashes: set[str] = set()
for target in TARGETS:
    final_url = download_pdf(target["url"], target["dest"])
    meta = validate_pdf(target["dest"], target["min_pages"])
    if meta["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate report detected: {target['dest'].name}")
    seen_hashes.add(meta["sha256"])
    rec = {
        "label": target["label"],
        "document_type": target["type"],
        "fiscal_year": target["year"],
        "relative_path": str(target["dest"].relative_to(ROOT)),
        "source": "香港交易所披露易（HKEXnews）",
        "source_url": final_url,
        **meta,
    }
    records.append(rec)
    print("VALIDATED", json.dumps(rec, ensure_ascii=False), flush=True)

interim_info = discover_2026_interim()
interim_dest = LATEST / "2026_中国能源建设_半年度报告_港交所官方.pdf"
interim_final_url = download_pdf(interim_info["url"], interim_dest)
interim_meta = validate_pdf(interim_dest, 30)
if interim_meta["sha256"] in seen_hashes:
    raise RuntimeError("duplicate interim report detected")
seen_hashes.add(interim_meta["sha256"])
records.append({
    "label": "2026年半年度报告",
    "document_type": "半年度报告",
    "fiscal_year": 2026,
    "relative_path": str(interim_dest.relative_to(ROOT)),
    "title_on_hkex": interim_info["title"],
    "language_index": interim_info["language_index"],
    "hkex_search_urls": interim_info["search_urls"],
    "source": "香港交易所披露易（HKEXnews）",
    "source_url": interim_final_url,
    **interim_meta,
})

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
print("REPORT_COUNT", len(records), flush=True)
