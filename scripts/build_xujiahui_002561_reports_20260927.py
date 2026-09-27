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

CHECKED_AS_OF = "2026-09-27"
ISSUER = "上海徐家汇商城股份有限公司"
SHORT_NAME = "徐家汇"
STOCK_CODE = "002561"
PACKAGE = "徐家汇_002561_2020-2025年报_2026最新定期报告"
ROOT = Path(PACKAGE)
ANNUAL_DIR = ROOT / "01_年度报告"
LATEST_DIR = ROOT / "02_最新定期报告"
VERIFY_DIR = ROOT / "03_说明与校验"
WORK_DIR = Path("_xujiahui_002561_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (ANNUAL_DIR, LATEST_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
CNINFO_QUERY = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STOCK_LIST = "https://www.cninfo.com.cn/new/data/szse_stock.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_title(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value or "")
    return re.sub(r"\s+", "", value).replace("：", ":")


def request(method: str, url: str, *, data: dict[str, Any] | None = None, stream: bool = False,
            referer: str | None = None, timeout: tuple[int, int] = (20, 300)) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        headers = dict(BASE_HEADERS)
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
                method.upper(), url, data=data, headers=headers, timeout=timeout,
                stream=stream, allow_redirects=True,
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
            time.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"request failed for {url}: {errors[-6:]}")


def get_cninfo_org_id() -> str | None:
    try:
        response = request("GET", CNINFO_STOCK_LIST, referer="https://www.cninfo.com.cn/", timeout=(15, 90))
        try:
            payload = response.json()
        finally:
            response.close()
        for row in payload.get("stockList", []):
            if str(row.get("code")) == STOCK_CODE:
                org_id = row.get("orgId") or row.get("orgid")
                if org_id:
                    print("CNINFO_ORG_ID", org_id, flush=True)
                    return str(org_id)
    except Exception as exc:  # noqa: BLE001
        print("CNINFO_STOCK_LIST_WARNING", repr(exc), flush=True)
    return None


def discover_cninfo_pdf(target_title: str, start_date: str, end_date: str, category: str = "") -> dict[str, str] | None:
    org_id = get_cninfo_org_id()
    stock_values = [f"{STOCK_CODE},{org_id}"] if org_id else []
    stock_values.extend([f"{STOCK_CODE},sz", STOCK_CODE])
    seen_stock_values: set[str] = set()
    desired = clean_title(target_title)

    for stock_value in stock_values:
        if stock_value in seen_stock_values:
            continue
        seen_stock_values.add(stock_value)
        for search_key in (target_title, ""):
            for page_num in range(1, 8):
                form = {
                    "pageNum": str(page_num),
                    "pageSize": "30",
                    "column": "szse",
                    "tabName": "fulltext",
                    "plate": "sz",
                    "stock": stock_value,
                    "searchkey": search_key,
                    "secid": "",
                    "category": category,
                    "trade": "",
                    "seDate": f"{start_date}~{end_date}",
                    "sortName": "time",
                    "sortType": "desc",
                    "isHLtitle": "false",
                }
                try:
                    response = request(
                        "POST", CNINFO_QUERY, data=form,
                        referer="https://www.cninfo.com.cn/new/disclosure/stock?stockCode=002561&orgId=&pageNum=1",
                        timeout=(20, 120),
                    )
                    try:
                        payload = response.json()
                    finally:
                        response.close()
                except Exception as exc:  # noqa: BLE001
                    print("CNINFO_QUERY_WARNING", stock_value, search_key, page_num, repr(exc), flush=True)
                    break

                announcements = payload.get("announcements") or []
                for announcement in announcements:
                    title = clean_title(str(announcement.get("announcementTitle", "")))
                    if title != desired:
                        continue
                    adjunct = str(announcement.get("adjunctUrl", "")).lstrip("/")
                    if not adjunct:
                        continue
                    url = "https://static.cninfo.com.cn/" + adjunct
                    found = {
                        "url": url,
                        "source": "巨潮资讯网（官方信息披露平台）",
                        "title": title,
                    }
                    print("CNINFO_MATCH", json.dumps(found, ensure_ascii=False), flush=True)
                    return found

                total_pages = int(payload.get("totalpages") or payload.get("totalPages") or 0)
                if not announcements or (total_pages and page_num >= total_pages) or len(announcements) < 30:
                    break
    return None


def download_pdf(candidates: list[dict[str, str]], destination: Path) -> tuple[str, str, list[str]]:
    errors: list[str] = []
    for candidate in candidates:
        url = candidate["url"]
        source = candidate["source"]
        referer = candidate.get("referer") or (
            "https://www.cninfo.com.cn/" if "cninfo.com.cn" in url
            else "https://www.szse.cn/" if "szse.cn" in url
            else "https://money.finance.sina.com.cn/"
        )
        temp = destination.with_suffix(destination.suffix + ".part")
        temp.unlink(missing_ok=True)
        try:
            response = request("GET", url, stream=True, referer=referer, timeout=(25, 420))
            try:
                with temp.open("wb") as fh:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            fh.write(chunk)
                final_url = str(response.url)
            finally:
                response.close()
            head = temp.read_bytes()[:8]
            size = temp.stat().st_size
            if size < 50_000 or not head.startswith(b"%PDF-"):
                raise RuntimeError(f"not a valid PDF: bytes={size}, head={head!r}")
            temp.replace(destination)
            print("DOWNLOADED", destination, size, source, final_url, flush=True)
            return final_url, source, errors
        except Exception as exc:  # noqa: BLE001
            temp.unlink(missing_ok=True)
            message = f"{source} | {url} | {exc!r}"
            errors.append(message)
            print("DOWNLOAD_CANDIDATE_FAILED", message, flush=True)
    raise RuntimeError(f"all candidates failed for {destination.name}: {errors}")


def render_page(path: Path, page_number: int, tag: str) -> None:
    prefix = RENDER_DIR / f"{path.stem}_{tag}"
    command = [
        "pdftoppm", "-f", str(page_number), "-l", str(page_number),
        "-r", "84", "-png", "-singlefile", str(path), str(prefix),
    ]
    process = subprocess.run(command, capture_output=True, text=True, timeout=240)
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


def validate_pdf(path: Path, *, report_year: int, report_type: str, min_pages: int) -> dict[str, Any]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=240)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-2500:]}")

    reader = PdfReader(str(path), strict=False)
    page_count = len(reader.pages)
    if page_count < min_pages:
        raise RuntimeError(f"unexpectedly short {path.name}: {page_count} pages, expected >= {min_pages}")

    render_page(path, 1, "first")
    if page_count > 1:
        render_page(path, page_count, "last")

    sample_indices = list(range(min(8, page_count)))
    if page_count > 8:
        sample_indices.append(page_count - 1)
    sample_text = "\n".join((reader.pages[index].extract_text() or "") for index in sample_indices)
    normalized = re.sub(r"\s+", "", sample_text)
    identity_ok = SHORT_NAME in normalized or ISSUER in normalized
    if sample_text.strip() and not identity_ok:
        raise RuntimeError(f"issuer identity not found in sampled text for {path.name}")
    if sample_text.strip() and str(report_year) not in normalized:
        raise RuntimeError(f"report year {report_year} not found in sampled text for {path.name}")

    first_pages_text = "\n".join((reader.pages[index].extract_text() or "") for index in range(min(3, page_count)))
    first_normalized = re.sub(r"\s+", "", first_pages_text)
    if report_type == "年度报告":
        if "年度报告摘要" in first_normalized:
            raise RuntimeError(f"summary detected instead of full annual report: {path.name}")
        if first_pages_text.strip() and "年度报告" not in first_normalized:
            raise RuntimeError(f"annual-report title not found in first pages: {path.name}")
    elif report_type == "第一季度报告" and first_pages_text.strip() and "第一季度报告" not in first_normalized:
        raise RuntimeError(f"Q1-report title not found in first pages: {path.name}")
    elif report_type == "半年度报告" and first_pages_text.strip() and "半年度报告" not in first_normalized:
        raise RuntimeError(f"half-year-report title not found in first pages: {path.name}")

    return {
        "pages": page_count,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "render_verified_first_and_last_page": True,
        "issuer_identity_verified_when_text_extractable": identity_ok,
        "sample_text_extractable": bool(sample_text.strip()),
    }


SINA_BASE = "https://file.finance.sina.com.cn/211.154.219.97%3A9494/MRGG/CNSESZ_STOCK"
TARGETS: list[dict[str, Any]] = [
    {
        "label": "2020年年度报告", "year": 2020, "type": "年度报告",
        "start": "2021-03-01", "end": "2021-04-30", "category": "category_ndbg_szsh;",
        "destination": ANNUAL_DIR / "2020_徐家汇_年度报告全文.pdf", "min_pages": 90,
        "fallbacks": [{"url": f"{SINA_BASE}/2021/2021-3/2021-03-27/6985424.PDF", "source": "新浪财经上市公司公告镜像（对应交易所披露全文）"}],
    },
    {
        "label": "2021年年度报告", "year": 2021, "type": "年度报告",
        "start": "2022-03-01", "end": "2022-04-30", "category": "category_ndbg_szsh;",
        "destination": ANNUAL_DIR / "2021_徐家汇_年度报告全文.pdf", "min_pages": 90,
        "fallbacks": [{"url": f"{SINA_BASE}/2022/2022-3/2022-03-26/7915040.PDF", "source": "新浪财经上市公司公告镜像（对应交易所披露全文）"}],
    },
    {
        "label": "2022年年度报告", "year": 2022, "type": "年度报告",
        "start": "2023-03-01", "end": "2023-04-30", "category": "category_ndbg_szsh;",
        "destination": ANNUAL_DIR / "2022_徐家汇_年度报告全文.pdf", "min_pages": 90,
        "fallbacks": [{"url": f"{SINA_BASE}/2023/2023-3/2023-03-25/8909295.PDF", "source": "新浪财经上市公司公告镜像（对应交易所披露全文）"}],
    },
    {
        "label": "2023年年度报告", "year": 2023, "type": "年度报告",
        "start": "2024-03-01", "end": "2024-04-30", "category": "category_ndbg_szsh;",
        "destination": ANNUAL_DIR / "2023_徐家汇_年度报告全文.pdf", "min_pages": 90,
        "fallbacks": [{"url": f"{SINA_BASE}/2024/2024-3/2024-03-30/9926567.PDF", "source": "新浪财经上市公司公告镜像（对应交易所披露全文）"}],
    },
    {
        "label": "2024年年度报告", "year": 2024, "type": "年度报告",
        "start": "2025-03-01", "end": "2025-04-30", "category": "category_ndbg_szsh;",
        "destination": ANNUAL_DIR / "2024_徐家汇_年度报告全文.pdf", "min_pages": 90,
        "fallbacks": [{"url": f"{SINA_BASE}/2025/2025-3/2025-03-29/10825445.PDF", "source": "新浪财经上市公司公告镜像（对应交易所披露全文）"}],
    },
    {
        "label": "2025年年度报告", "year": 2025, "type": "年度报告",
        "start": "2026-03-01", "end": "2026-04-30", "category": "category_ndbg_szsh;",
        "destination": ANNUAL_DIR / "2025_徐家汇_年度报告全文.pdf", "min_pages": 90,
        "fallbacks": [{"url": f"{SINA_BASE}/2026/2026-3/2026-03-28/12028632.PDF", "source": "新浪财经上市公司公告镜像（对应交易所披露全文）"}],
    },
    {
        "label": "2026年第一季度报告", "year": 2026, "type": "第一季度报告",
        "start": "2026-04-01", "end": "2026-05-31", "category": "category_yjdbg_szsh;",
        "destination": LATEST_DIR / "2026_徐家汇_第一季度报告.pdf", "min_pages": 5,
        "fallbacks": [{
            "url": "https://disc.static.szse.cn/download/disc/disk03/finalpage/2026-04-25/5d345618-fc96-4710-a5b1-0bd07addbac8.PDF",
            "source": "深圳证券交易所（官方）",
        }],
    },
    {
        "label": "2026年半年度报告", "year": 2026, "type": "半年度报告",
        "start": "2026-08-01", "end": "2026-09-27", "category": "category_bndbg_szsh;",
        "destination": LATEST_DIR / "2026_徐家汇_半年度报告.pdf", "min_pages": 60,
        "fallbacks": [{"url": f"{SINA_BASE}/2026/2026-8/2026-08-21/12511871.PDF", "source": "新浪财经上市公司公告镜像（对应交易所披露全文）"}],
    },
]

records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()
for target in TARGETS:
    official = discover_cninfo_pdf(
        target["label"], target["start"], target["end"], target["category"],
    )
    candidates: list[dict[str, str]] = []
    if official:
        candidates.append(official)
    candidates.extend(target["fallbacks"])

    final_url, source, failed_candidates = download_pdf(candidates, target["destination"])
    metadata = validate_pdf(
        target["destination"], report_year=target["year"],
        report_type=target["type"], min_pages=target["min_pages"],
    )
    if metadata["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate report detected: {target['destination'].name}")
    seen_hashes.add(metadata["sha256"])
    record = {
        "label": target["label"],
        "document_type": target["type"],
        "fiscal_year": target["year"],
        "relative_path": str(target["destination"].relative_to(ROOT)),
        "source": source,
        "source_url": final_url,
        "official_cninfo_match_found": bool(official),
        "failed_download_candidates_before_success": failed_candidates,
        **metadata,
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
- 按证券市场常用口径，“季报”指第一季度报告或第三季度报告。截至2026年9月27日，2026年第三季度报告尚未进入法定披露期，因此最新季报是2026年第一季度报告。
- 为避免遗漏更新的信息，本文件包同时收入2026年半年度报告。
- 所有年度报告均为“年度报告全文”，未以“年度报告摘要”替代。

校验说明：
- 每份PDF均通过文件头、最低大小、qpdf结构检查；
- 使用PDF解析器核对页数、发行人名称、报告年度及报告类型；
- 每份PDF的第一页和最后一页均已实际渲染为PNG进行可视化可读性检查；
- 文件之间已做SHA-256去重；
- 详细来源、页数、大小和哈希值见《文件清单.csv》《SHA256SUMS.txt》及manifest.json。

来源说明：
- 下载时优先自动匹配巨潮资讯网官方披露全文；
- 若官方接口临时不可用，则使用深圳证券交易所官方静态文件或新浪财经上市公司公告镜像中的同一披露全文；
- manifest.json会如实记录每份文件实际使用的来源及最终网址。
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
