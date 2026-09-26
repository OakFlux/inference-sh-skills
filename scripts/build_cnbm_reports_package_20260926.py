from __future__ import annotations

import csv
import hashlib
import html as html_lib
import json
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

PACKAGE = "中国建材_03323_2020-2025年报_2026最新季报"
ROOT = Path(PACKAGE)
ANNUAL_DIR = ROOT / "01_年度报告"
LATEST_DIR = ROOT / "02_最新定期报告"
NOTE_DIR = ROOT / "03_说明与校验"
WORK = Path("_cnbm_work")
RENDER = WORK / "renders"
for d in (ANNUAL_DIR, LATEST_DIR, NOTE_DIR, RENDER):
    d.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def request(url: str, *, stream: bool = False, timeout=(15, 150), referer: str | None = None) -> requests.Response:
    errors = []
    urls = [url]
    if "www1.hkexnews.hk" in url:
        urls.append(url.replace("www1.hkexnews.hk", "www.hkexnews.hk"))
    elif "www.hkexnews.hk" in url:
        urls.append(url.replace("www.hkexnews.hk", "www1.hkexnews.hk"))
    for candidate in dict.fromkeys(urls):
        for attempt in range(1, 5):
            try:
                h = dict(HEADERS)
                if referer:
                    h["Referer"] = referer
                elif "cnbmltd.com" in candidate:
                    h["Referer"] = "https://www.cnbmltd.com/"
                elif "financial" in candidate:
                    h["Referer"] = "https://financialfilings.com/"
                else:
                    h["Referer"] = "https://www1.hkexnews.hk/"
                r = SESSION.get(candidate, headers=h, timeout=timeout, allow_redirects=True, stream=stream)
                print("GET", candidate, "attempt", attempt, "status", r.status_code,
                      "type", r.headers.get("content-type"), "length", r.headers.get("content-length"),
                      "final", r.url, flush=True)
                r.raise_for_status()
                return r
            except Exception as exc:
                errors.append(f"{candidate} attempt {attempt}: {exc!r}")
                time.sleep(min(2 * attempt, 6))
    raise RuntimeError(f"request failed for {url}: {errors[-8:]}")


def fetch_html(url: str) -> tuple[str, str]:
    r = request(url, stream=False, timeout=(15, 100))
    try:
        raw = r.content
        final = str(r.url)
        ctype = r.headers.get("content-type", "")
        enc = r.apparent_encoding or r.encoding or "utf-8"
    finally:
        r.close()
    if len(raw) < 300 or ("html" not in ctype.lower() and not raw.lstrip().startswith(b"<")):
        raise RuntimeError(f"not usable HTML: {url}; bytes={len(raw)}; type={ctype}")
    try:
        text = raw.decode(enc, errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")
    return final, text


def link_candidates(page_url: str, page_html: str, year: int) -> list[tuple[int, str, str]]:
    soup = BeautifulSoup(page_html, "html.parser")
    out: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    for node in soup.find_all(True):
        for attr in ("href", "src", "data-src", "data-url"):
            raw = node.get(attr)
            if not raw or raw.startswith(("javascript:", "#", "mailto:")):
                continue
            href = urljoin(page_url, html_lib.unescape(raw.strip()))
            low = href.lower()
            text = " ".join(node.get_text(" ", strip=True).split())
            if href in seen:
                continue
            if any(k in low for k in (".pdf", "download", "downfile", "attachment", "upload")):
                seen.add(href)
                score = 0
                if ".pdf" in low:
                    score += 25
                if str(year) in text or str(year) in low:
                    score += 50
                if "年度报告" in text or "annual report" in text.lower():
                    score += 60
                if re.search(r"20\d{2}", text) and str(year) not in text:
                    score -= 60
                if any(bad in text.lower() for bad in ("esg", "environmental", "业绩公告", "results announcement")):
                    score -= 80
                out.append((score, href, text))
    # Capture URLs embedded in scripts or JSON.
    for raw in re.findall(r"(?:https?:)?//[^\"'<>\s]+|/[A-Za-z0-9_./?=&%+-]+", page_html):
        candidate = html_lib.unescape(raw.replace("\\/", "/"))
        if not any(k in candidate.lower() for k in (".pdf", "downfile", "download", "attachment")):
            continue
        href = urljoin(page_url, candidate)
        if href in seen:
            continue
        seen.add(href)
        score = 25 + (50 if str(year) in href else 0)
        out.append((score, href, "embedded URL"))
    return sorted(out, key=lambda x: (-x[0], x[1]))


def article_links(page_url: str, page_html: str, year: int) -> list[str]:
    soup = BeautifulSoup(page_html, "html.parser")
    rows = []
    for a in soup.find_all("a", href=True):
        txt = " ".join(a.get_text(" ", strip=True).split())
        href = urljoin(page_url, a["href"])
        if str(year) in txt and ("年度报告" in txt or "annual report" in txt.lower()):
            rows.append(href)
    return list(dict.fromkeys(rows))


def download_pdf(url: str, dest: Path, *, referer: str | None = None, min_bytes: int = 30_000) -> str:
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.unlink(missing_ok=True)
    r = request(url, stream=True, timeout=(20, 240), referer=referer)
    try:
        with tmp.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
        final = str(r.url)
        ctype = r.headers.get("content-type", "")
    finally:
        r.close()
    size = tmp.stat().st_size
    head = tmp.read_bytes()[:8]
    if size < min_bytes or not head.startswith(b"%PDF-"):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"download is not a valid PDF: {url}; bytes={size}; head={head!r}; type={ctype}")
    tmp.replace(dest)
    return final


def try_article_source(article_url: str, year: int, dest: Path) -> tuple[str, str] | None:
    try:
        final_page, page_html = fetch_html(article_url)
    except Exception as exc:
        print("ARTICLE_FETCH_FAILED", year, article_url, repr(exc), flush=True)
        return None
    candidates = link_candidates(final_page, page_html, year)
    print("ARTICLE_CANDIDATES", year, final_page, json.dumps(candidates[:20], ensure_ascii=False), flush=True)
    for score, pdf_url, text in candidates:
        if score < 0:
            continue
        try:
            final_pdf = download_pdf(pdf_url, dest, referer=final_page, min_bytes=80_000)
            return final_pdf, f"中国建材股份有限公司官网文章页：{final_page}；附件文字：{text or '(无)'}"
        except Exception as exc:
            print("PDF_CANDIDATE_FAILED", year, score, pdf_url, repr(exc), flush=True)
    return None


def find_financialfilings_report(year: int) -> tuple[str, str]:
    release_year = year + 1
    archive_url = f"https://financialfilings.com/companies/china-national-building-material-company-limited/{release_year}/"
    final_archive, archive_html = fetch_html(archive_url)
    soup = BeautifulSoup(archive_html, "html.parser")
    details: list[str] = []
    exact = f"{year} Annual Report"
    for a in soup.find_all("a", href=True):
        txt = " ".join(a.get_text(" ", strip=True).split())
        href = urljoin(final_archive, a["href"])
        if txt.lower() == exact.lower() or (str(year) in txt and "annual report" in txt.lower() and "announcement" not in txt.lower()):
            details.append(href)
    # Known company-site English article may also provide a clean annual report PDF.
    details = list(dict.fromkeys(details))
    print("FINANCIALFILINGS_DETAILS", year, details, flush=True)
    for detail in details:
        try:
            final_detail, detail_html = fetch_html(detail)
        except Exception as exc:
            print("DETAIL_FETCH_FAILED", year, detail, repr(exc), flush=True)
            continue
        dsoup = BeautifulSoup(detail_html, "html.parser")
        candidates: list[str] = []
        for a in dsoup.find_all("a", href=True):
            href = urljoin(final_detail, a["href"])
            if ".pdf" in href.lower() and ("financialreports" in href.lower() or "cdn." in href.lower()):
                candidates.append(href)
        # Also inspect raw HTML for CDN PDF URLs.
        for m in re.findall(r"https?://[^\"'<>\s]+\.pdf(?:\?[^\"'<>\s]*)?", detail_html, flags=re.I):
            candidates.append(html_lib.unescape(m.replace("\\/", "/")))
        for pdf_url in dict.fromkeys(candidates):
            return pdf_url, f"港交所披露原件镜像索引：{final_detail}"
    raise RuntimeError(f"could not locate FinancialFilings annual report for {year}")


def validate_pdf(path: Path, *, min_pages: int) -> dict:
    if not path.exists() or path.stat().st_size < 20_000 or not path.read_bytes()[:8].startswith(b"%PDF-"):
        raise RuntimeError(f"invalid PDF file: {path}")
    q = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True)
    if q.returncode not in (0, 3):
        raise RuntimeError(f"qpdf validation failed for {path.name}: {q.stderr[-2000:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"too few pages for {path.name}: {pages}")
    for page_no in sorted(set([1, pages])):
        prefix = RENDER / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{page_no}"
        proc = subprocess.run([
            "pdftoppm", "-f", str(page_no), "-l", str(page_no), "-r", "72",
            "-png", "-singlefile", str(path), str(prefix)
        ], capture_output=True, text=True, timeout=180)
        png = Path(str(prefix) + ".png")
        if proc.returncode != 0 or not png.exists() or png.stat().st_size < 800 or not png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError(f"render validation failed for {path.name} page {page_no}: {proc.stderr[-1200:]}")
        png.unlink()
    text = ""
    try:
        sample_indices = list(range(min(7, pages))) + ([pages - 1] if pages > 7 else [])
        text = "\n".join((reader.pages[i].extract_text() or "") for i in sample_indices)
    except Exception as exc:
        print("TEXT_EXTRACTION_WARNING", path.name, repr(exc), flush=True)
    low = text.lower()
    identity = any(x in text for x in ("中国建材", "中國建材")) or "china national building material" in low or "03323" in text or "3323" in text
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_chars = len(re.findall(r"[A-Za-z]", text))
    language = "中文或中英双语" if chinese_chars > max(100, latin_chars * 0.12) else "英文"
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": q.returncode,
        "render_verified_first_and_last": True,
        "identity_text_verified_when_extractable": identity,
        "detected_language": language,
    }


records: list[dict] = []
seen_hashes: set[str] = set()

KNOWN_ARTICLES = {
    2020: ["https://www.cnbmltd.com/art/2021/4/8/art_1193_74772.html"],
    2021: ["https://www.cnbmltd.com/art/2023/1/30/art_1379_77616.html"],
    2022: ["https://www.cnbmltd.com/art/2023/4/4/art_1356_77764.html", "https://www.cnbmltd.com/art/2023/4/4/art_1379_77765.html"],
    2023: ["https://www.cnbmltd.com/art/2024/3/28/art_1356_78357.html", "https://www.cnbmltd.com/art/2024/4/1/art_1379_78361.html"],
    2024: ["https://www.cnbmltd.com/art/2025/4/9/art_1356_78731.html"],
    2025: ["https://www.cnbmltd.com/art/2026/3/31/art_1193_79450.html"],
}

# Discover additional article URLs from the company index and known pages.
seed_pages = [
    "https://www.cnbmltd.com/col/col1355/index.html",
    "https://www.cnbmltd.com/col/col1333/index.html",
    *[u for rows in KNOWN_ARTICLES.values() for u in rows],
]
for seed in seed_pages:
    try:
        final_seed, seed_html = fetch_html(seed)
    except Exception as exc:
        print("SEED_FAILED", seed, repr(exc), flush=True)
        continue
    for y in range(2020, 2026):
        for u in article_links(final_seed, seed_html, y):
            if u not in KNOWN_ARTICLES[y]:
                KNOWN_ARTICLES[y].append(u)

for year in range(2020, 2026):
    dest = ANNUAL_DIR / f"{year}_中国建材_年度报告.pdf"
    source_url = ""
    source_note = ""
    # Prefer the issuer's official website, trying Chinese pages before English pages.
    for article in KNOWN_ARTICLES[year]:
        result = try_article_source(article, year, dest)
        if result:
            source_url, source_note = result
            break
    if not source_url:
        mirror_url, source_note = find_financialfilings_report(year)
        source_url = download_pdf(mirror_url, dest, referer="https://financialfilings.com/", min_bytes=80_000)
    data = validate_pdf(dest, min_pages=30)
    if data["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate annual report detected: {year}")
    seen_hashes.add(data["sha256"])
    rec = {
        "relative_path": str(dest.relative_to(ROOT)),
        "filename": dest.name,
        "document_type": "年度报告",
        "fiscal_year": year,
        "source_url": source_url,
        "source_note": source_note,
        **data,
    }
    records.append(rec)
    print("ANNUAL_VALIDATED", json.dumps(rec, ensure_ascii=False), flush=True)

periodic = [
    {
        "filename": "2026_中国建材_第一季度报告.pdf",
        "title": "中国建材2026年第一季度报告",
        "type": "第一季度报告",
        "date": "2026-04-29",
        "url": "https://cdn.financialreports.eu/financialreports/media/filings/50813/2026/RNS/50813_rns_2026-04-29_fbc4bdb6-faa6-43ca-a296-2b1da9d860a4.pdf",
        "note": "港交所披露原件镜像；截至2026年9月26日最新正式季度报告",
        "min_pages": 8,
    },
    {
        "filename": "2026_中国建材_中期报告_补充.pdf",
        "title": "中国建材2026年中期报告",
        "type": "中期报告",
        "date": "2026-08-27",
        "url": "https://cdn.financialreports.eu/financialreports/media/filings/50813/2026/RNS/50813_rns_2026-08-27_6205455f-f997-4154-8cbf-cc9cba3c3524.pdf",
        "note": "港交所披露原件镜像；披露日期晚于第一季度报告，作为最新阶段性财务报告补充",
        "min_pages": 40,
    },
]
for item in periodic:
    dest = LATEST_DIR / item["filename"]
    final_url = download_pdf(item["url"], dest, referer="https://financialfilings.com/", min_bytes=40_000)
    data = validate_pdf(dest, min_pages=item["min_pages"])
    if data["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate periodic report: {item['filename']}")
    seen_hashes.add(data["sha256"])
    rec = {
        "relative_path": str(dest.relative_to(ROOT)),
        "filename": dest.name,
        "document_type": item["type"],
        "fiscal_year": 2026,
        "publication_date": item["date"],
        "source_url": final_url,
        "source_note": item["note"],
        **data,
    }
    records.append(rec)
    print("PERIODIC_VALIDATED", json.dumps(rec, ensure_ascii=False), flush=True)

manifest = {
    "package_name": PACKAGE,
    "issuer": "中国建材股份有限公司 / China National Building Material Company Limited",
    "stock_code": "03323.HK",
    "checked_as_of": "2026-09-26",
    "coverage": {
        "annual_reports": "2020—2025，每个会计年度一份完整年度报告",
        "latest_quarterly_report": "2026年第一季度报告（2026-04-29披露）",
        "supplemental_latest_periodic_report": "2026年中期报告（2026-08-27披露）",
    },
    "pdf_count": len(records),
    "records": records,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (ROOT / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["相对路径", "文件类型", "会计年度", "披露日期", "语言", "页数", "字节数", "SHA-256", "来源网址", "来源说明"])
    for r in records:
        w.writerow([
            r["relative_path"], r["document_type"], r.get("fiscal_year", ""), r.get("publication_date", ""),
            r["detected_language"], r["pages"], r["bytes"], r["sha256"], r["source_url"], r["source_note"],
        ])

readme = f"""中国建材股份有限公司（03323.HK）官方披露文件包

核对日期：2026年9月26日

收录内容
1. 2020—2025年度报告，共6份，每个会计年度一份完整年度报告。
2. 2026年第一季度报告：截至核对日的最新正式季度报告。
3. 2026年中期报告：披露时间晚于第一季度报告，作为最新阶段性财务信息补充收录。

来源口径
- 优先采用中国建材股份有限公司官网附件。
- 官网附件无法稳定取得时，采用从港交所原始披露抓取并保存的可核验镜像；每份文件的最终来源网址均记录于文件清单和manifest.json。

质量检查
- PDF数量：{len(records)}。
- 每份PDF均检查PDF文件头、页数、qpdf结构，并渲染首末页验证可读性。
- SHA256SUMS.txt可用于文件完整性核验。
- ZIP生成后执行CRC完整性检查。
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
print("PDF_COUNT", len(records), flush=True)
