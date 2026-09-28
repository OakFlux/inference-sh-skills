from __future__ import annotations

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

CHECKED_AS_OF = "2026-09-28"
COMPANY_ZH = "巨星傳奇集團有限公司"
COMPANY_EN = "STAR PLUS LEGEND HOLDINGS LIMITED"
STOCK_CODE = "06683"
HKEX_STOCK_ID = "1000190606"
PACKAGE_NAME = "巨星传奇_06683_全部年报_招股说明书_2026最新定期报告"
ROOT = Path(PACKAGE_NAME)
IPO_DIR = ROOT / "01_招股说明书"
ANNUAL_DIR = ROOT / "02_年度报告"
LATEST_DIR = ROOT / "03_最新定期报告"
VERIFY_DIR = ROOT / "04_来源与校验"
WORK_DIR = Path("_starplus_06683_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (IPO_DIR, ANNUAL_DIR, LATEST_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/json,text/html,application/pdf,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www1.hkexnews.hk/",
}

STATIC_DOCUMENTS: list[dict[str, Any]] = [
    {
        "label": "中文招股章程",
        "document_type": "招股章程",
        "relative_path": "01_招股说明书/01_巨星传奇_06683_招股章程_中文版_2023-06-30.pdf",
        "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2023/0630/2023063000038_c.pdf",
        "min_pages": 100,
    },
    {
        "label": "English Prospectus",
        "document_type": "Prospectus",
        "relative_path": "01_招股说明书/02_STAR_PLUS_LEGEND_06683_Prospectus_English_2023-06-30.pdf",
        "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2023/0630/2023063000037.pdf",
        "min_pages": 100,
    },
    {
        "label": "2023年年度报告",
        "document_type": "年度报告",
        "fiscal_year": 2023,
        "relative_path": "02_年度报告/03_巨星传奇_06683_2023年年度报告.pdf",
        "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2024/0429/2024042900065.pdf",
        "min_pages": 80,
    },
    {
        "label": "2024年年度报告",
        "document_type": "年度报告",
        "fiscal_year": 2024,
        "relative_path": "02_年度报告/04_巨星传奇_06683_2024年年度报告.pdf",
        "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0429/2025042900817.pdf",
        "min_pages": 80,
    },
    {
        "label": "2025年年度报告",
        "document_type": "年度报告",
        "fiscal_year": 2025,
        "relative_path": "02_年度报告/05_巨星传奇_06683_2025年年度报告.pdf",
        "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0428/2026042800516.pdf",
        "min_pages": 80,
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request(method: str, url: str, *, stream: bool = False, timeout: tuple[int, int] = (25, 600)) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        try:
            response = SESSION.request(
                method,
                url,
                headers=HEADERS,
                timeout=timeout,
                stream=stream,
                allow_redirects=True,
            )
            print(
                "HTTP", method, url, "attempt", attempt, "status", response.status_code,
                "type", response.headers.get("content-type"),
                "length", response.headers.get("content-length"),
                "final", response.url,
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"request failed for {url}: {errors[-6:]}")


def flatten(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from flatten(item)
    elif isinstance(value, list):
        for item in value:
            yield from flatten(item)


def pick(mapping: dict[str, Any], *keys: str) -> str:
    lower = {str(key).lower(): value for key, value in mapping.items()}
    for key in keys:
        value = mapping.get(key)
        if value is None:
            value = lower.get(key.lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def normalize_title(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", "", value).upper()


def score_latest(title: str, date_text: str) -> int:
    normalized = normalize_title(title)
    score = 0
    if any(token in normalized for token in ("INTERIMREPORT", "中期報告", "中期报告")):
        score += 500
    if any(token in normalized for token in ("INTERIMRESULTS", "中期業績", "中期业绩")):
        score += 350
    if any(token in normalized for token in ("SIXMONTHSENDED30JUNE2026", "截至2026年6月30日止六個月", "截至2026年6月30日止六个月")):
        score += 120
    if any(token in normalized for token in ("2026", "二零二六")):
        score += 60
    if any(token in normalized for token in ("SUPPLEMENTALINFORMATION", "補充資料", "补充资料")):
        score += 10
    if any(token in normalized for token in ("BOARDMEETING", "董事會會議", "董事会会议", "PROFITWARNING", "盈利警告")):
        score -= 500
    if "31/08/2026" in date_text or "2026-08-31" in date_text:
        score += 20
    return score


def query_hkex_latest() -> list[dict[str, str]]:
    candidates: dict[str, dict[str, str]] = {}
    for language in ("ZH", "EN"):
        params = {
            "sortDir": "0",
            "sortByOptions": "DateTime",
            "category": "0",
            "market": "SEHK",
            "stockId": HKEX_STOCK_ID,
            "documentType": "-1",
            "fromDate": "20260701",
            "toDate": CHECKED_AS_OF.replace("-", ""),
            "title": "",
            "searchType": "1",
            "t1code": "-2",
            "t2Gcode": "-2",
            "t2code": "-2",
            "rowRange": "200",
            "lang": language,
        }
        prepared = requests.Request(
            "GET", "https://www1.hkexnews.hk/search/titleSearchServlet.do", params=params
        ).prepare().url
        if not prepared:
            continue
        response = request("GET", prepared, timeout=(25, 180))
        try:
            outer = response.json()
        finally:
            response.close()
        payload: Any = outer
        if isinstance(outer, dict) and isinstance(outer.get("result"), str):
            payload = json.loads(outer["result"])
        elif isinstance(outer, dict) and outer.get("result") is not None:
            payload = outer["result"]
        for row in flatten(payload):
            link = pick(row, "FILE_LINK", "fileLink", "file_link", "url")
            if ".pdf" not in link.lower():
                continue
            title = pick(row, "TITLE", "title", "announcementTitle")
            date_text = pick(row, "DATE_TIME", "dateTime", "date_time", "display_time")
            score = score_latest(title, date_text)
            if score < 300:
                continue
            if link.startswith("/"):
                link = "https://www1.hkexnews.hk" + link
            current = candidates.get(link)
            item = {"title": title, "date": date_text, "url": link, "language": language, "score": str(score)}
            if current is None or int(item["score"]) > int(current["score"]):
                candidates[link] = item
    ordered = sorted(candidates.values(), key=lambda item: (int(item["score"]), item["date"]), reverse=True)
    print("HKEX_RELEVANT_CANDIDATES", json.dumps(ordered, ensure_ascii=False, indent=2), flush=True)
    return ordered


def query_eastmoney_fallback() -> dict[str, str] | None:
    params = {
        "sr": "-1",
        "page_size": "100",
        "page_index": "1",
        "ann_type": "H",
        "client_source": "web",
        "stock_list": STOCK_CODE,
        "f_node": "0",
        "s_node": "0",
    }
    prepared = requests.Request(
        "GET", "https://np-anotice-stock.eastmoney.com/api/security/ann", params=params
    ).prepare().url
    if not prepared:
        return None
    response = request("GET", prepared, timeout=(25, 180))
    try:
        payload = response.json()
    finally:
        response.close()
    rows: list[dict[str, str]] = []
    for row in flatten(payload.get("data", {}) if isinstance(payload, dict) else payload):
        code = pick(row, "art_code", "artCode", "announcementId")
        title = pick(row, "title_ch", "title", "announcementTitle")
        date_text = pick(row, "display_time", "notice_date", "date")
        if not re.fullmatch(r"AN\d+", code, re.IGNORECASE):
            continue
        score = score_latest(title, date_text)
        if score < 300:
            continue
        rows.append({
            "title": title,
            "date": date_text,
            "url": f"https://pdf.dfcfw.com/pdf/H2_{code.upper()}_1.pdf",
            "language": "ZH-mirror",
            "score": str(score),
        })
    rows.sort(key=lambda item: (int(item["score"]), item["date"]), reverse=True)
    print("EASTMONEY_RELEVANT_CANDIDATES", json.dumps(rows, ensure_ascii=False, indent=2), flush=True)
    return rows[0] if rows else None


def discover_latest_documents() -> list[dict[str, Any]]:
    try:
        candidates = query_hkex_latest()
    except Exception as exc:  # noqa: BLE001
        print("HKEX_DISCOVERY_ERROR", repr(exc), flush=True)
        candidates = []
    selected: list[dict[str, str]] = []
    full_reports = [item for item in candidates if any(token in normalize_title(item["title"]) for token in ("INTERIMREPORT", "中期報告", "中期报告"))]
    result_announcements = [item for item in candidates if any(token in normalize_title(item["title"]) for token in ("INTERIMRESULTS", "中期業績", "中期业绩"))]
    if full_reports:
        selected.append(full_reports[0])
    if result_announcements and (not selected or result_announcements[0]["url"] != selected[0]["url"]):
        selected.append(result_announcements[0])
    if not selected:
        fallback = query_eastmoney_fallback()
        if fallback:
            selected.append(fallback)
    if not selected:
        raise RuntimeError("No 2026 interim financial filing could be discovered from HKEX or the public mirror")

    documents: list[dict[str, Any]] = []
    for index, item in enumerate(selected, start=1):
        normalized = normalize_title(item["title"])
        is_full = any(token in normalized for token in ("INTERIMREPORT", "中期報告", "中期报告"))
        suffix = "中期报告" if is_full else "中期业绩公告"
        documents.append({
            "label": f"2026年{suffix}",
            "document_type": suffix,
            "relative_path": f"03_最新定期报告/{5 + index:02d}_巨星传奇_06683_2026年{suffix}.pdf",
            "url": item["url"],
            "disclosed_title": item["title"],
            "disclosed_date": item["date"],
            "source_language": item["language"],
            "min_pages": 8 if not is_full else 30,
        })
    return documents


def download_pdf(url: str, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".part")
    temp.unlink(missing_ok=True)
    response = request("GET", url, stream=True, timeout=(30, 900))
    try:
        with temp.open("wb") as handle:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    handle.write(chunk)
        final_url = str(response.url)
    finally:
        response.close()
    size = temp.stat().st_size
    head = temp.read_bytes()[:8]
    if size < 40_000 or not head.startswith(b"%PDF-"):
        raise RuntimeError(f"invalid PDF for {destination.name}: bytes={size}, head={head!r}")
    temp.replace(destination)
    print("DOWNLOADED", destination, size, final_url, flush=True)
    return final_url


def render_page(path: Path, page_number: int, tag: str) -> None:
    prefix = RENDER_DIR / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{tag}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number), "-r", "72",
            "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    image = Path(str(prefix) + ".png")
    valid = process.returncode == 0 and image.exists() and image.stat().st_size > 1000
    if not valid:
        raise RuntimeError(f"render validation failed for {path.name} page {page_number}: {process.stderr[-1200:]}")
    image.unlink()


def validate_pdf(path: Path, min_pages: int) -> dict[str, Any]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=600)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-2500:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"unexpectedly short PDF {path.name}: {pages} pages, expected >= {min_pages}")
    render_page(path, 1, "first")
    if pages > 1:
        render_page(path, pages, "last")
    sampled_text = "\n".join((reader.pages[index].extract_text() or "") for index in range(min(12, pages)))
    normalized = re.sub(r"\s+", "", sampled_text).upper()
    identity_ok = any(token in normalized for token in ("巨星傳奇", "巨星传奇", "STARPLUSLEGEND", "STOCKCODE6683", "股份代號6683"))
    if sampled_text.strip() and not identity_ok:
        raise RuntimeError(f"issuer identity not found in sampled text for {path.name}")
    return {
        "bytes": path.stat().st_size,
        "pages": pages,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "first_and_last_pages_rendered": True,
        "issuer_identity_verified_when_text_extractable": identity_ok,
    }


def main() -> None:
    latest_documents = discover_latest_documents()
    documents = STATIC_DOCUMENTS + latest_documents
    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for document in documents:
        destination = ROOT / document["relative_path"]
        final_url = download_pdf(document["url"], destination)
        metadata = validate_pdf(destination, int(document["min_pages"]))
        if metadata["sha256"] in seen_hashes:
            raise RuntimeError(f"duplicate document detected: {destination.name}")
        seen_hashes.add(metadata["sha256"])
        record = dict(document)
        record.pop("min_pages", None)
        record["source_url"] = final_url
        record.update(metadata)
        records.append(record)

    readme_lines = [
        "巨星传奇集团有限公司（06683.HK）公开披露文件资料包",
        f"核对日期：{CHECKED_AS_OF}",
        "",
        "收录口径：",
        "1. 港交所中文版及英文版招股章程。",
        "2. 公司上市后全部完整年度报告：2023、2024、2025年。",
        "3. 截至核对日最新阶段性财务文件：2026年中期报告（如已发布）及/或2026年中期业绩公告。",
        "4. 港股主板公司通常不按A股格式发布季度报告，因此以最新中期财务披露作为“最新季报”口径。",
        "",
        "文件均从香港交易所披露易原始PDF地址下载；仅统一文件名与目录，不改写PDF正文或页面顺序。",
        "",
        "文件清单：",
    ]
    for index, record in enumerate(records, start=1):
        readme_lines.extend([
            f"{index}. {record['label']}",
            f"   文件：{record['relative_path']}",
            f"   页数：{record['pages']}",
            f"   大小：{record['bytes']} bytes",
            f"   SHA-256：{record['sha256']}",
            f"   来源：{record['source_url']}",
        ])
        if record.get("disclosed_title"):
            readme_lines.append(f"   港交所标题：{record['disclosed_title']}")
        if record.get("disclosed_date"):
            readme_lines.append(f"   披露时间：{record['disclosed_date']}")
        readme_lines.append("")

    (VERIFY_DIR / "README_文件清单与来源说明.txt").write_text("\n".join(readme_lines), encoding="utf-8")
    (VERIFY_DIR / "manifest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    checksum_lines = [f"{record['sha256']}  {record['relative_path']}" for record in records]
    (VERIFY_DIR / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    final_zip = Path(PACKAGE_NAME + ".zip")
    final_zip.unlink(missing_ok=True)
    with zipfile.ZipFile(final_zip, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.as_posix())
    with zipfile.ZipFile(final_zip, "r") as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP integrity test failed at {bad}")
    print("FINAL_ZIP", final_zip, final_zip.stat().st_size, flush=True)
    print("MANIFEST", json.dumps(records, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
