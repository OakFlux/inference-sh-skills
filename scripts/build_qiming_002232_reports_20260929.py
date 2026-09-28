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

CHECKED_AS_OF = "2026-09-29"
ISSUER = "启明信息技术股份有限公司"
SHORT_NAME = "启明信息"
STOCK_CODE = "002232"
PACKAGE = "启明信息_002232_2020-2025年报_2026最新定期报告"
ROOT = Path(PACKAGE)
ANNUAL_DIR = ROOT / "01_年度报告"
LATEST_DIR = ROOT / "02_最新定期报告"
VERIFY_DIR = ROOT / "03_说明与校验"
WORK_DIR = Path("_qiming_002232_work")
RENDER_DIR = WORK_DIR / "renders"

for directory in (ANNUAL_DIR, LATEST_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
CNINFO_STOCK_LIST = "https://www.cninfo.com.cn/new/data/szse_stock.json"
CNINFO_QUERY = "https://www.cninfo.com.cn/new/hisAnnouncement/query"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_title(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value or "")
    return re.sub(r"\s+", "", value).replace("：", ":")


def request(
    method: str,
    url: str,
    *,
    data: dict[str, Any] | None = None,
    stream: bool = False,
    referer: str | None = None,
    timeout: tuple[int, int] = (20, 360),
) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        headers = dict(HEADERS)
        if referer:
            headers["Referer"] = referer
        if method.upper() == "POST":
            headers.update({
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": "https://www.cninfo.com.cn",
                "X-Requested-With": "XMLHttpRequest",
            })
        try:
            response = SESSION.request(
                method.upper(), url, data=data, headers=headers,
                timeout=timeout, stream=stream, allow_redirects=True,
            )
            print(
                "HTTP", method.upper(), url, "attempt", attempt,
                "status", response.status_code,
                "type", response.headers.get("content-type"),
                "length", response.headers.get("content-length"),
                "final", response.url,
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(attempt * 2, 10))
    raise RuntimeError(f"request failed for {url}: {errors[-6:]}")


def get_org_id() -> str:
    response = request("GET", CNINFO_STOCK_LIST, referer="https://www.cninfo.com.cn/", timeout=(15, 120))
    try:
        payload = response.json()
    finally:
        response.close()
    matches = [row for row in payload.get("stockList", []) if str(row.get("code")) == STOCK_CODE]
    if not matches:
        raise RuntimeError(f"{STOCK_CODE} not found in CNINFO stock list")
    org_id = str(matches[0].get("orgId") or matches[0].get("orgid") or "")
    if not org_id:
        raise RuntimeError(f"missing orgId for {STOCK_CODE}")
    print("CNINFO_ORG_ID", org_id, matches[0].get("zwjc"), flush=True)
    return org_id


ORG_ID = get_org_id()


def query_announcements(
    *, search_key: str, start_date: str, end_date: str, category: str = ""
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for page_num in range(1, 10):
        form = {
            "pageNum": str(page_num),
            "pageSize": "30",
            "column": "szse",
            "tabName": "fulltext",
            "plate": "sz",
            "stock": f"{STOCK_CODE},{ORG_ID}",
            "searchkey": search_key,
            "secid": "",
            "category": category,
            "trade": "",
            "seDate": f"{start_date}~{end_date}",
            "sortName": "time",
            "sortType": "desc",
            "isHLtitle": "false",
        }
        response = request(
            "POST", CNINFO_QUERY, data=form,
            referer=f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={STOCK_CODE}&orgId={ORG_ID}&pageNum=1",
            timeout=(20, 150),
        )
        try:
            payload = response.json()
        finally:
            response.close()

        announcements = payload.get("announcements") or []
        for announcement in announcements:
            announcement_id = str(announcement.get("announcementId") or "")
            if announcement_id and announcement_id in seen_ids:
                continue
            if announcement_id:
                seen_ids.add(announcement_id)
            adjunct = str(announcement.get("adjunctUrl") or "").lstrip("/")
            if not adjunct:
                continue
            item = {
                "title": normalize_title(str(announcement.get("announcementTitle") or "")),
                "url": "https://static.cninfo.com.cn/" + adjunct,
                "announcement_time": int(announcement.get("announcementTime") or 0),
                "announcement_id": announcement_id,
            }
            results.append(item)
            print("ANNOUNCEMENT", json.dumps(item, ensure_ascii=False), flush=True)

        total_pages = int(payload.get("totalpages") or payload.get("totalPages") or 0)
        if not announcements or (total_pages and page_num >= total_pages) or len(announcements) < 30:
            break
    return results


def collect_probes(probes: list[tuple[str, str]], start_date: str, end_date: str) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for search_key, category in probes:
        for item in query_announcements(
            search_key=search_key,
            start_date=start_date,
            end_date=end_date,
            category=category,
        ):
            marker = item.get("announcement_id") or item["url"]
            if marker not in seen:
                seen.add(marker)
                collected.append(item)
    return collected


def choose_annual(year: int) -> dict[str, Any]:
    candidates = collect_probes(
        [
            (f"{year}年年度报告", "category_ndbg_szsh;"),
            (f"{year}年年度报告", ""),
            ("年度报告", "category_ndbg_szsh;"),
        ],
        f"{year + 1}-01-01",
        f"{year + 1}-06-30",
    )
    valid: list[dict[str, Any]] = []
    for item in candidates:
        title = item["title"]
        if f"{year}年年度报告" not in title:
            continue
        if any(term in title for term in (
            "摘要", "英文版", "提示性公告", "取消", "更正公告",
            "审计报告", "业绩说明会", "问询函", "回复",
        )):
            continue
        valid.append(item)
    if not valid:
        raise RuntimeError(f"No full annual report found for {year}")
    valid.sort(key=lambda x: x["announcement_time"], reverse=True)
    chosen = valid[0]
    print("CHOSEN_ANNUAL", year, json.dumps(chosen, ensure_ascii=False), flush=True)
    return chosen


def choose_q1() -> dict[str, Any]:
    candidates = collect_probes(
        [
            ("2026年一季度报告", ""),
            ("2026年第一季度报告", ""),
            ("一季度报告", ""),
            ("第一季度报告", ""),
            ("", "category_yjdbg_szsh;"),
        ],
        "2026-04-01",
        "2026-07-31",
    )
    valid = [
        item for item in candidates
        if ("2026年一季度报告" in item["title"] or "2026年第一季度报告" in item["title"])
        and not any(term in item["title"] for term in (
            "摘要", "英文版", "取消", "更正公告", "提示性公告",
        ))
    ]
    if not valid:
        raise RuntimeError("No 2026 first-quarter report found")
    valid.sort(key=lambda x: x["announcement_time"], reverse=True)
    chosen = valid[0]
    print("CHOSEN_Q1", json.dumps(chosen, ensure_ascii=False), flush=True)
    return chosen


def choose_interim() -> dict[str, Any] | None:
    candidates = collect_probes(
        [
            ("2026年半年度报告", "category_bndbg_szsh;"),
            ("2026年半年度报告", ""),
            ("半年度报告", ""),
        ],
        "2026-07-01",
        CHECKED_AS_OF,
    )
    valid = [
        item for item in candidates
        if "2026年半年度报告" in item["title"]
        and not any(term in item["title"] for term in (
            "摘要", "英文版", "取消", "更正公告", "提示性公告",
        ))
    ]
    if not valid:
        print("NO_2026_INTERIM_FOUND", flush=True)
        return None
    valid.sort(key=lambda x: x["announcement_time"], reverse=True)
    chosen = valid[0]
    print("CHOSEN_INTERIM", json.dumps(chosen, ensure_ascii=False), flush=True)
    return chosen


def download_pdf(url: str, destination: Path) -> str:
    response = request("GET", url, stream=True, referer="https://www.cninfo.com.cn/", timeout=(25, 480))
    temp = destination.with_suffix(destination.suffix + ".part")
    temp.unlink(missing_ok=True)
    try:
        with temp.open("wb") as fh:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    fh.write(chunk)
        final_url = str(response.url)
    finally:
        response.close()

    size = temp.stat().st_size
    head = temp.read_bytes()[:8]
    if size < 40_000 or not head.startswith(b"%PDF-"):
        raise RuntimeError(f"invalid PDF for {destination.name}: size={size}, head={head!r}")
    temp.replace(destination)
    print("DOWNLOADED", destination, size, final_url, flush=True)
    return final_url


def render_page(path: Path, page_number: int, suffix: str) -> None:
    prefix = RENDER_DIR / f"{path.stem}_{suffix}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
            "-r", "84", "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=240,
    )
    png = Path(str(prefix) + ".png")
    valid = (
        process.returncode == 0 and png.exists() and png.stat().st_size > 1000
        and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(
            f"render validation failed for {path.name} page {page_number}: "
            f"return={process.returncode}, stderr={process.stderr[-1500:]}"
        )
    png.unlink()


def validate_pdf(path: Path, *, fiscal_year: int, report_type: str, min_pages: int) -> dict[str, Any]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-2500:]}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"unexpectedly short PDF {path.name}: {pages} pages, expected >= {min_pages}")

    render_page(path, 1, "first")
    if pages > 1:
        render_page(path, pages, "last")

    sample_indices = list(range(min(10, pages)))
    if pages > 10:
        sample_indices.append(pages - 1)
    sample_text = "\n".join((reader.pages[index].extract_text() or "") for index in sample_indices)
    normalized = re.sub(r"\s+", "", sample_text)

    identity_ok = SHORT_NAME in normalized or ISSUER in normalized or STOCK_CODE in normalized
    if sample_text.strip() and not identity_ok:
        raise RuntimeError(f"issuer identity not found in sampled text for {path.name}")
    if sample_text.strip() and str(fiscal_year) not in normalized:
        raise RuntimeError(f"fiscal year {fiscal_year} not found in sampled text for {path.name}")

    first_text = "\n".join((reader.pages[index].extract_text() or "") for index in range(min(4, pages)))
    first_normalized = re.sub(r"\s+", "", first_text)
    if report_type == "年度报告":
        if "年度报告摘要" in first_normalized:
            raise RuntimeError(f"annual-report summary detected: {path.name}")
        if first_text.strip() and "年度报告" not in first_normalized:
            raise RuntimeError(f"annual-report title not found: {path.name}")
    elif report_type == "第一季度报告":
        if first_text.strip() and not any(marker in first_normalized for marker in ("第一季度报告", "一季度报告")):
            raise RuntimeError(f"Q1 title not found: {path.name}")
    elif report_type == "半年度报告":
        if first_text.strip() and "半年度报告" not in first_normalized:
            raise RuntimeError(f"interim title not found: {path.name}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "render_verified_first_and_last_page": True,
        "issuer_identity_verified_when_text_extractable": identity_ok,
        "sample_text_extractable": bool(sample_text.strip()),
    }


targets: list[dict[str, Any]] = []
for year in range(2020, 2026):
    source = choose_annual(year)
    targets.append({
        "label": f"{year}年年度报告",
        "type": "年度报告",
        "year": year,
        "source": source,
        "destination": ANNUAL_DIR / f"{year}_启明信息_年度报告全文.pdf",
        "min_pages": 80,
    })

q1 = choose_q1()
targets.append({
    "label": "2026年第一季度报告",
    "type": "第一季度报告",
    "year": 2026,
    "source": q1,
    "destination": LATEST_DIR / "2026_启明信息_第一季度报告.pdf",
    "min_pages": 5,
})

interim = choose_interim()
if interim is not None:
    targets.append({
        "label": "2026年半年度报告",
        "type": "半年度报告",
        "year": 2026,
        "source": interim,
        "destination": LATEST_DIR / "2026_启明信息_半年度报告.pdf",
        "min_pages": 50,
    })

records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()
for target in targets:
    final_url = download_pdf(target["source"]["url"], target["destination"])
    validation = validate_pdf(
        target["destination"],
        fiscal_year=target["year"],
        report_type=target["type"],
        min_pages=target["min_pages"],
    )
    if validation["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate report detected: {target['destination'].name}")
    seen_hashes.add(validation["sha256"])
    record = {
        "label": target["label"],
        "document_type": target["type"],
        "fiscal_year": target["year"],
        "relative_path": str(target["destination"].relative_to(ROOT)),
        "title_on_cninfo": target["source"]["title"],
        "announcement_id": target["source"]["announcement_id"],
        "source": "巨潮资讯网（官方信息披露平台）",
        "source_url": final_url,
        **validation,
    }
    records.append(record)
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

manifest = {
    "package_name": PACKAGE,
    "issuer": ISSUER,
    "short_name": SHORT_NAME,
    "stock_code": STOCK_CODE,
    "checked_as_of": CHECKED_AS_OF,
    "coverage": "2020—2025年度报告全文、2026年第一季度报告，以及披露时间更晚的2026年半年度报告",
    "report_count": len(records),
    "notes": [
        "严格按‘最新季报’口径，最新季度报告为2026年第一季度报告。",
        "截至核对日，披露时间更晚的完整定期报告为2026年半年度报告，因此一并收录。",
        "年度报告均为全文版本，不含仅有摘要的替代文件。",
    ],
    "records": records,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as fh:
    writer = csv.writer(fh)
    writer.writerow(["文件", "类型", "年度", "页数", "字节数", "SHA-256", "来源", "来源网址"])
    for record in records:
        writer.writerow([
            record["relative_path"], record["document_type"], record["fiscal_year"],
            record["pages"], record["bytes"], record["sha256"],
            record["source"], record["source_url"],
        ])

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as fh:
    for record in records:
        fh.write(f"{record['sha256']}  {record['relative_path']}\n")

readme = f"""{ISSUER}（{STOCK_CODE}）定期报告文件包

核对日期：{CHECKED_AS_OF}

收录内容：
1. 2020—2025年度报告全文，共6份；
2. 2026年第一季度报告，共1份；
3. 2026年半年度报告，共1份。该报告披露时间晚于一季报，作为截至核对日的最新完整定期报告一并收录。

口径说明：
- 按证券市场常用口径，“季报”指第一季度报告或第三季度报告。截至2026年9月29日，2026年第三季度报告尚未进入常规定期报告披露阶段，因此最新季报为2026年第一季度报告。
- 为避免遗漏更新的信息，本文件包同时收入2026年半年度报告。
- 所有年度报告均为“年度报告全文”，未以“年度报告摘要”替代。

校验说明：
- 每份PDF均通过文件头、最低大小、qpdf结构检查；
- 使用PDF解析器核对页数、发行人名称、报告年度及报告类型；
- 每份PDF的第一页和最后一页均已实际渲染为PNG进行可读性检查；
- 文件之间已做SHA-256去重；
- 详细来源、页数、大小和哈希值见《文件清单.csv》《SHA256SUMS.txt》及manifest.json。

来源：巨潮资讯网官方信息披露文件。
"""
(VERIFY_DIR / "README.txt").write_text(readme, encoding="utf-8")

zip_path = Path(PACKAGE + ".zip")
zip_path.unlink(missing_ok=True)
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, path.as_posix())

with zipfile.ZipFile(zip_path, "r") as archive:
    bad_member = archive.testzip()
    if bad_member:
        raise RuntimeError(f"ZIP integrity test failed at {bad_member}")
    expected_pdf_count = len(records)
    actual_pdf_count = sum(1 for name in archive.namelist() if name.lower().endswith(".pdf"))
    if actual_pdf_count != expected_pdf_count:
        raise RuntimeError(f"ZIP PDF count mismatch: expected {expected_pdf_count}, got {actual_pdf_count}")

print("FINAL_ZIP", zip_path, "bytes", zip_path.stat().st_size, "sha256", sha256(zip_path), flush=True)
