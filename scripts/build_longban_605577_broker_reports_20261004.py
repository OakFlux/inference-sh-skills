from __future__ import annotations

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

CHECK_DATE = "2026-10-04"
COMPANY = "龙版传媒"
CODE = "605577"
PACKAGE_NAME = f"龙版传媒_{CODE}_券商深度报告_公开原始PDF_截至{CHECK_DATE}"
ROOT = Path(PACKAGE_NAME)
REPORT_DIR = ROOT / "01_券商研究报告"
META_DIR = ROOT / "02_来源与校验"
WORK = Path("_longban_reports_work")
RENDER = WORK / "renders"
for d in (REPORT_DIR, META_DIR, WORK, RENDER):
    d.mkdir(parents=True, exist_ok=True)

S = requests.Session()
S.trust_env = False
S.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})

LIST2 = "https://reportapi.eastmoney.com/report/list2"
LIST = "https://reportapi.eastmoney.com/report/list"
PDF_TPL = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def request(method: str, url: str, **kwargs) -> requests.Response:
    errors: list[str] = []
    headers = {"Referer": "https://data.eastmoney.com/", **kwargs.pop("headers", {})}
    for attempt in range(1, 7):
        try:
            r = S.request(method, url, headers=headers, timeout=(20, 180), allow_redirects=True, **kwargs)
            print("HTTP", method, url, "attempt", attempt, "status", r.status_code,
                  "type", r.headers.get("content-type"), "length", r.headers.get("content-length"), flush=True)
            r.raise_for_status()
            return r
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            time.sleep(min(attempt * 2, 10))
    raise RuntimeError(f"request failed: {method} {url}: {errors}")


def parse_payload(r: requests.Response) -> dict[str, Any]:
    text = r.text.strip()
    try:
        return r.json()
    except Exception:
        m = re.search(r"^[^(]*\((.*)\)\s*;?$", text, re.S)
        if m:
            return json.loads(m.group(1))
        raise RuntimeError(f"unexpected API response: {text[:500]}")


def fetch_stock_reports() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(1, 8):
        body = {
            "pageSize": 100,
            "pageNo": page,
            "p": page,
            "pageNum": page,
            "pageNumber": page,
            "beginTime": "2020-01-01",
            "endTime": CHECK_DATE,
            "code": CODE,
            "industryCode": "*",
            "rating": None,
            "ratingChange": None,
            "orgCode": None,
            "rcode": "",
        }
        r = request("POST", LIST2, json=body, headers={"Content-Type": "application/json"})
        payload = parse_payload(r)
        r.close()
        data = payload.get("data") or []
        print("STOCK_PAGE", page, "hits", payload.get("hits"), "records", len(data), flush=True)
        if not data:
            break
        rows.extend(data)
        if len(data) < 100:
            break
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        info = str(row.get("infoCode") or "")
        if info:
            unique[info] = row
    result = list(unique.values())
    result.sort(key=lambda x: str(x.get("publishDate") or ""), reverse=True)
    print("STOCK_REPORTS", json.dumps(result, ensure_ascii=False, indent=2)[:30000], flush=True)
    return result


def fetch_industry_candidates() -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    target_phrases = (
        "关注央国企传媒标的的动态变化",
        "出版行业2025年报及2026年一季报业绩综述",
        "出版板块业绩分化",
        "出版行业在政策红利与AI浪潮共振下的价值重构",
        "数智赋能与内容焕新",
        "出版行业半年报总结",
        "克难奋进",
        "出版行业",
    )
    for page in range(1, 121):
        params = {
            "cb": f"datatable{int(time.time() * 1000)}",
            "industryCode": "*",
            "pageSize": "100",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": "2024-01-01",
            "endTime": CHECK_DATE,
            "pageNo": str(page),
            "fields": "",
            "qType": "1",
            "orgCode": "",
            "code": "*",
            "rcode": "",
            "p": str(page),
            "pageNum": str(page),
            "pageNumber": str(page),
        }
        r = request("GET", LIST, params=params)
        payload = parse_payload(r)
        r.close()
        data = payload.get("data") or []
        print("INDUSTRY_PAGE", page, "hits", payload.get("hits"), "records", len(data), flush=True)
        if not data:
            break
        for row in data:
            title = str(row.get("title") or "")
            if any(p in title for p in target_phrases):
                info = str(row.get("infoCode") or "")
                if info:
                    candidates[info] = row
        # API is newest-first. Once we have gone before 2024, stop.
        dates = [str(x.get("publishDate") or "")[:10] for x in data if x.get("publishDate")]
        if dates and min(dates) < "2024-01-01":
            break
        if len(data) < 100:
            break
    result = list(candidates.values())
    result.sort(key=lambda x: str(x.get("publishDate") or ""), reverse=True)
    print("INDUSTRY_CANDIDATES", json.dumps(result, ensure_ascii=False, indent=2)[:50000], flush=True)
    return result


def safe_filename(text: str, max_len: int = 96) -> str:
    text = re.sub(r"[\\/:*?\"<>|\r\n]+", "_", text).strip(" ._")
    text = re.sub(r"\s+", "", text)
    return text[:max_len] or "report"


def download_pdf(info_code: str, target: Path) -> str:
    url = PDF_TPL.format(info_code=info_code)
    temp = target.with_suffix(target.suffix + ".part")
    temp.unlink(missing_ok=True)
    r = request("GET", url, stream=True)
    try:
        with temp.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
        final_url = str(r.url)
    finally:
        r.close()
    head = temp.read_bytes()[:8]
    if temp.stat().st_size < 20_000 or not head.startswith(b"%PDF-"):
        raise RuntimeError(f"not a valid PDF: {url}, size={temp.stat().st_size}, head={head!r}")
    temp.replace(target)
    return final_url


def extract_text(path: Path) -> str:
    out = path.with_suffix(".txt")
    p = subprocess.run(["pdftotext", "-layout", str(path), str(out)], capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        print("PDFTOTEXT_WARNING", path.name, p.stderr[-1000:], flush=True)
        return ""
    text = out.read_text(encoding="utf-8", errors="ignore")
    out.unlink(missing_ok=True)
    return text


def render_check(path: Path, page: int, tag: str) -> None:
    prefix = RENDER / f"{hashlib.sha1(path.name.encode()).hexdigest()}_{tag}"
    p = subprocess.run([
        "pdftoppm", "-f", str(page), "-l", str(page), "-r", "90", "-png", "-singlefile",
        str(path), str(prefix)
    ], capture_output=True, text=True, timeout=300)
    image = Path(str(prefix) + ".png")
    if p.returncode != 0 or not image.exists() or image.stat().st_size < 1000:
        raise RuntimeError(f"render failed for {path.name} page {page}: {p.stderr[-1000:]}")
    image.unlink()


def validate_pdf(path: Path, must_mention_longban: bool) -> tuple[dict[str, Any], str]:
    q = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300)
    if q.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {q.stderr[-2000:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 2:
        raise RuntimeError(f"unexpected page count {pages}: {path.name}")
    render_check(path, 1, "first")
    render_check(path, pages, "last")
    text = extract_text(path)
    normalized = re.sub(r"\s+", "", text)
    if must_mention_longban and "龙版传媒" not in normalized and CODE not in normalized:
        raise RuntimeError(f"report does not mention 龙版传媒/605577: {path.name}")
    return ({
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": q.returncode,
        "first_and_last_page_rendered": True,
        "mentions_longban": ("龙版传媒" in normalized or CODE in normalized),
    }, text)


def report_score(row: dict[str, Any]) -> int:
    title = str(row.get("title") or "")
    score = 0
    if "关注央国企传媒标的的动态变化" in title:
        score += 1000
    if "出版行业2025年报及2026年一季报业绩综述" in title or "出版板块业绩分化" in title:
        score += 900
    if "出版行业在政策红利与AI浪潮共振下的价值重构" in title or "数智赋能与内容焕新" in title:
        score += 850
    if "出版行业半年报总结" in title:
        score += 800
    if "深度" in title or "专题" in title or "综述" in title or "半年报" in title:
        score += 150
    if "周报" in title or "周观点" in title:
        score -= 400
    pages = row.get("attachPages") or row.get("pageCount") or 0
    try:
        score += min(int(pages), 80)
    except Exception:
        pass
    date = str(row.get("publishDate") or "")[:10]
    if date >= "2026-01-01":
        score += 80
    elif date >= "2025-01-01":
        score += 40
    return score


def metadata_from_row(row: dict[str, Any], category: str) -> dict[str, Any]:
    return {
        "category": category,
        "title": row.get("title"),
        "institution": row.get("orgSName") or row.get("orgName"),
        "analysts": row.get("researcher") or row.get("researcherName"),
        "publish_date": str(row.get("publishDate") or "")[:10],
        "rating": row.get("emRatingName") or row.get("ratingName"),
        "stock_name": row.get("stockName"),
        "stock_code": row.get("stockCode"),
        "industry_name": row.get("industryName") or row.get("indvInduName"),
        "info_code": row.get("infoCode"),
        "api_attach_pages": row.get("attachPages") or row.get("pageCount"),
        "api_attach_size": row.get("attachSize"),
    }


def main() -> None:
    stock_rows = fetch_stock_reports()
    industry_rows = fetch_industry_candidates()

    selected_records: list[dict[str, Any]] = []
    selected_hashes: set[str] = set()

    # Include all valid company-specific reports, newest first, up to 3.
    for row in stock_rows:
        if len(selected_records) >= 3:
            break
        info = str(row.get("infoCode") or "")
        title = str(row.get("title") or "")
        institution = str(row.get("orgSName") or row.get("orgName") or "券商")
        date = str(row.get("publishDate") or "")[:10]
        filename = safe_filename(f"{date}_{institution}_{title}") + ".pdf"
        target = REPORT_DIR / filename
        try:
            source_url = download_pdf(info, target)
            checks, _ = validate_pdf(target, must_mention_longban=True)
        except Exception as exc:  # noqa: BLE001
            print("STOCK_REPORT_REJECTED", info, title, repr(exc), flush=True)
            target.unlink(missing_ok=True)
            continue
        if checks["sha256"] in selected_hashes:
            target.unlink(missing_ok=True)
            continue
        selected_hashes.add(checks["sha256"])
        meta = metadata_from_row(row, "龙版传媒公司专项报告")
        meta.update(checks)
        meta["file"] = target.relative_to(ROOT).as_posix()
        meta["source_pdf_url"] = source_url
        selected_records.append(meta)

    # Add industry deep reports that explicitly mention 龙版传媒 until total reaches 3.
    for row in sorted(industry_rows, key=report_score, reverse=True):
        if len(selected_records) >= 3:
            break
        info = str(row.get("infoCode") or "")
        title = str(row.get("title") or "")
        institution = str(row.get("orgSName") or row.get("orgName") or "券商")
        date = str(row.get("publishDate") or "")[:10]
        filename = safe_filename(f"{date}_{institution}_{title}") + ".pdf"
        target = REPORT_DIR / filename
        try:
            source_url = download_pdf(info, target)
            checks, text = validate_pdf(target, must_mention_longban=True)
        except Exception as exc:  # noqa: BLE001
            print("INDUSTRY_REPORT_REJECTED", info, title, repr(exc), flush=True)
            target.unlink(missing_ok=True)
            continue
        if checks["sha256"] in selected_hashes:
            target.unlink(missing_ok=True)
            continue
        # Exclude short market notes/weekly reports unless no deeper option exists.
        if checks["pages"] < 10 or "周报" in title:
            print("INDUSTRY_REPORT_TOO_SHALLOW", title, checks["pages"], flush=True)
            target.unlink(missing_ok=True)
            continue
        selected_hashes.add(checks["sha256"])
        meta = metadata_from_row(row, "出版/传媒行业深度报告（正文明确提及龙版传媒）")
        meta.update(checks)
        meta["file"] = target.relative_to(ROOT).as_posix()
        meta["source_pdf_url"] = source_url
        # Record a minimal context indicator without reproducing copyrighted text.
        normalized = re.sub(r"\s+", "", text)
        meta["longban_mention_count"] = normalized.count("龙版传媒") + normalized.count(CODE)
        selected_records.append(meta)

    if not selected_records:
        raise RuntimeError("No valid public broker report PDF could be obtained")

    # Re-number files in final presentation order.
    for idx, rec in enumerate(selected_records, start=1):
        old = ROOT / rec["file"]
        new = REPORT_DIR / f"{idx:02d}_{old.name}"
        old.rename(new)
        rec["file"] = new.relative_to(ROOT).as_posix()

    company_count = sum(1 for r in selected_records if r["category"].startswith("龙版传媒公司"))
    industry_count = len(selected_records) - company_count
    readme = [
        f"龙版传媒（{CODE}.SH）券商研究报告资料包",
        f"核对日期：{CHECK_DATE}",
        "",
        f"本包共收录 {len(selected_records)} 份完整券商原始 PDF。",
        f"其中公司专项报告 {company_count} 份，出版/传媒行业深度报告 {industry_count} 份。",
        "",
        "口径说明：",
        "1. 公开研报数据库中，龙版传媒公司专项覆盖数量较少。",
        "2. 为满足2-3份的资料需求，在公司专项报告之外，补充收录正文明确提及龙版传媒并进行行业比较的深度/专题报告。",
        "3. 文件从东方财富公开研报PDF地址取得，未修改正文、页面顺序或券商署名。版权归原券商及作者所有，仅供个人研究使用。",
        "4. 本资料不构成投资建议。",
        "",
        "文件清单：",
    ]
    for idx, rec in enumerate(selected_records, start=1):
        readme.extend([
            f"{idx}. [{rec['category']}] {rec.get('institution') or ''}《{rec.get('title') or ''}》",
            f"   日期：{rec.get('publish_date') or '未知'}",
            f"   分析师：{rec.get('analysts') or '公开接口未列出'}",
            f"   评级：{rec.get('rating') or '未标注/不适用'}",
            f"   页数：{rec['pages']}；大小：{rec['bytes']} bytes",
            f"   文件：{rec['file']}",
            f"   来源PDF：{rec['source_pdf_url']}",
            f"   SHA-256：{rec['sha256']}",
            "",
        ])

    (META_DIR / "README_文件清单与口径说明.txt").write_text("\n".join(readme), encoding="utf-8")
    (META_DIR / "manifest.json").write_text(json.dumps(selected_records, ensure_ascii=False, indent=2), encoding="utf-8")
    (META_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{r['sha256']}  {r['file']}" for r in selected_records) + "\n",
        encoding="utf-8",
    )

    final_zip = Path(PACKAGE_NAME + ".zip")
    final_zip.unlink(missing_ok=True)
    with zipfile.ZipFile(final_zip, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                zf.write(path, path.as_posix())
    with zipfile.ZipFile(final_zip, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP integrity error at {bad}")
    print("FINAL_ZIP", final_zip, final_zip.stat().st_size, flush=True)
    print("FINAL_MANIFEST", json.dumps(selected_records, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
