from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-10-04"
COMPANY = "之江生物"
FULL_COMPANY = "上海之江生物科技股份有限公司"
STOCK_CODE = "688317"
PACKAGE = "之江生物_688317_全部年报_招股说明书_2026最新季报及半年报"
ROOT = Path(PACKAGE)
ANNUAL_DIR = ROOT / "01_年度报告"
PROSPECTUS_DIR = ROOT / "02_招股说明书"
QUARTER_DIR = ROOT / "03_最新季报"
SUPPLEMENT_DIR = ROOT / "04_补充定期报告"
VERIFY_DIR = ROOT / "05_说明与校验"
WORK_DIR = Path("_zhijiang_bio_688317_filings_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (ANNUAL_DIR, PROSPECTUS_DIR, QUARTER_DIR, SUPPLEMENT_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
    "Accept": "application/json,text/javascript,application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
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
            headers.update(
                {
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Origin": "https://www.cninfo.com.cn",
                    "X-Requested-With": "XMLHttpRequest",
                }
            )
        try:
            response = SESSION.request(
                method.upper(),
                url,
                data=data,
                headers=headers,
                timeout=timeout,
                stream=stream,
                allow_redirects=True,
            )
            print(
                "HTTP",
                method.upper(),
                url,
                "attempt",
                attempt,
                "status",
                response.status_code,
                "type",
                response.headers.get("content-type"),
                "length",
                response.headers.get("content-length"),
                "final",
                response.url,
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(attempt * 2, 10))
    raise RuntimeError(f"request failed for {url}: {errors[-6:]}")


def get_org_id() -> str:
    response = request(
        "GET",
        CNINFO_STOCK_LIST,
        referer="https://www.cninfo.com.cn/",
        timeout=(20, 120),
    )
    try:
        payload = response.json()
    finally:
        response.close()
    for row in payload.get("stockList", []):
        if str(row.get("code")) == STOCK_CODE:
            org_id = str(row.get("orgId") or "")
            if not org_id:
                break
            print("STOCK_ROW", json.dumps(row, ensure_ascii=False), flush=True)
            return org_id
    raise RuntimeError(f"CNInfo orgId not found for {STOCK_CODE}")


ORG_ID = get_org_id()


def query_announcements(search_key: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    form = {
        "pageNum": "1",
        "pageSize": "100",
        "column": "sse",
        "tabName": "fulltext",
        "plate": "sh",
        "stock": f"{STOCK_CODE},{ORG_ID}",
        "searchkey": search_key,
        "secid": "",
        "category": "",
        "trade": "",
        "seDate": f"{start_date}~{end_date}",
        "sortName": "time",
        "sortType": "desc",
        "isHLtitle": "false",
    }
    response = request(
        "POST",
        CNINFO_QUERY,
        data=form,
        referer=f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={STOCK_CODE}&orgId={ORG_ID}",
        timeout=(20, 120),
    )
    try:
        payload = response.json()
    finally:
        response.close()
    rows = payload.get("announcements") or []
    print(
        "QUERY",
        search_key,
        start_date,
        end_date,
        "total",
        payload.get("totalAnnouncement"),
        "returned",
        len(rows),
        flush=True,
    )
    for row in rows:
        print(
            "ROW",
            json.dumps(
                {
                    "title": clean_title(str(row.get("announcementTitle") or "")),
                    "time": row.get("announcementTime"),
                    "adjunctUrl": row.get("adjunctUrl"),
                    "announcementId": row.get("announcementId"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return rows


def merge_queries(keys: list[str], start_date: str, end_date: str) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in keys:
        for row in query_announcements(key, start_date, end_date):
            rid = str(row.get("announcementId") or row.get("adjunctUrl") or "")
            if rid and rid not in seen:
                seen.add(rid)
                merged.append(row)
    return merged


def row_date(row: dict[str, Any]) -> str:
    timestamp = row.get("announcementTime")
    if not timestamp:
        return ""
    return datetime.fromtimestamp(
        float(timestamp) / 1000,
        timezone(timedelta(hours=8)),
    ).strftime("%Y-%m-%d")


def choose_annual(year: int) -> dict[str, Any]:
    keys = [f"{year}年年度报告", f"{year}年度报告"]
    rows = merge_queries(keys, f"{year + 1}-01-01", f"{year + 2}-12-31")
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for row in rows:
        title = clean_title(str(row.get("announcementTitle") or ""))
        if not any(key in title for key in keys):
            continue
        if any(token in title for token in ("摘要", "审计报告", "问询函", "回复", "说明会", "已取消")):
            continue
        adjunct = str(row.get("adjunctUrl") or "")
        if not adjunct.lower().endswith(".pdf"):
            continue
        score = 10
        if title.endswith(keys[0]) or title.endswith(keys[1]):
            score += 30
        if any(token in title for token in ("更正后", "更新后", "修订版", "修订稿")):
            score += 80
        if any(token in title for token in ("更新前", "更正前")):
            score -= 40
        candidates.append((score, int(row.get("announcementTime") or 0), row))
    if not candidates:
        raise RuntimeError(f"no full annual report found for {year}")
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = candidates[0][2]
    print("SELECTED_ANNUAL", year, json.dumps(selected, ensure_ascii=False, default=str), flush=True)
    return selected


def choose_prospectus() -> dict[str, Any]:
    keys = [
        "首次公开发行股票并在科创板上市招股说明书",
        "首次公开发行股票招股说明书",
        "招股说明书",
    ]
    rows = merge_queries(keys, "2019-01-01", "2021-12-31")
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for row in rows:
        title = clean_title(str(row.get("announcementTitle") or ""))
        if "招股说明书" not in title:
            continue
        if any(
            token in title
            for token in (
                "注册稿",
                "上会稿",
                "申报稿",
                "招股意向书",
                "摘要",
                "提示性公告",
                "附录",
                "已取消",
            )
        ):
            continue
        adjunct = str(row.get("adjunctUrl") or "")
        if not adjunct.lower().endswith(".pdf"):
            continue
        score = 10
        if "首次公开发行股票并在科创板上市招股说明书" in title:
            score += 100
        if title.endswith("招股说明书"):
            score += 30
        candidates.append((score, int(row.get("announcementTime") or 0), row))
    if not candidates:
        raise RuntimeError("formal IPO prospectus not found")
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = candidates[0][2]
    print("SELECTED_PROSPECTUS", json.dumps(selected, ensure_ascii=False, default=str), flush=True)
    return selected


def choose_periodic(
    search_keys: list[str],
    start_date: str,
    end_date: str,
    exclude_tokens: tuple[str, ...] = ("摘要", "更正公告"),
) -> dict[str, Any] | None:
    rows = merge_queries(search_keys, start_date, end_date)
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for row in rows:
        title = clean_title(str(row.get("announcementTitle") or ""))
        if not any(key in title for key in search_keys):
            continue
        if any(token in title for token in exclude_tokens):
            continue
        adjunct = str(row.get("adjunctUrl") or "")
        if not adjunct.lower().endswith(".pdf"):
            continue
        score = 10
        if any(token in title for token in ("更正后", "更新后", "修订版")):
            score += 60
        candidates.append((score, int(row.get("announcementTime") or 0), row))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = candidates[0][2]
    print("SELECTED_PERIODIC", json.dumps(selected, ensure_ascii=False, default=str), flush=True)
    return selected


def static_url(row: dict[str, Any]) -> str:
    adjunct = str(row.get("adjunctUrl") or "").lstrip("/")
    if not adjunct:
        raise RuntimeError("announcement has no adjunctUrl")
    return "https://static.cninfo.com.cn/" + adjunct


def download_pdf(url: str, destination: Path) -> str:
    temp = destination.with_suffix(destination.suffix + ".part")
    temp.unlink(missing_ok=True)
    response = request(
        "GET",
        url,
        stream=True,
        referer="https://www.cninfo.com.cn/",
        timeout=(25, 480),
    )
    try:
        with temp.open("wb") as file_handle:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    file_handle.write(chunk)
        final_url = str(response.url)
    finally:
        response.close()
    size = temp.stat().st_size
    head = temp.read_bytes()[:8]
    if size < 50_000 or not head.startswith(b"%PDF-"):
        raise RuntimeError(f"invalid PDF download: {destination.name}, size={size}, head={head!r}")
    temp.replace(destination)
    print("DOWNLOADED", destination, size, final_url, flush=True)
    return final_url


def render_page(path: Path, page_number: int, suffix: str) -> None:
    prefix = RENDER_DIR / f"{path.stem}_{suffix}"
    process = subprocess.run(
        [
            "pdftoppm",
            "-f",
            str(page_number),
            "-l",
            str(page_number),
            "-r",
            "84",
            "-png",
            "-singlefile",
            str(path),
            str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    png = Path(str(prefix) + ".png")
    valid = (
        process.returncode == 0
        and png.exists()
        and png.stat().st_size > 1000
        and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(
            f"render failed for {path.name} page {page_number}: "
            f"return={process.returncode}, stderr={process.stderr[-1500:]}"
        )
    png.unlink()


def validate_pdf(
    path: Path,
    *,
    period_token: str,
    document_type: str,
    min_pages: int,
) -> dict[str, Any]:
    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {qpdf.stderr[-2500:]}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"page count too small for {path.name}: {pages} < {min_pages}")

    render_page(path, 1, "first")
    if pages > 1:
        render_page(path, pages, "last")

    indices = list(range(min(10, pages)))
    if pages > 10:
        indices.append(pages - 1)
    text_parts: list[str] = []
    for index in indices:
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_EXTRACT_WARNING", path.name, index + 1, repr(exc), flush=True)
    text = "\n".join(text_parts)
    normalized = re.sub(r"\s+", "", text)
    identity_ok = any(token in normalized for token in (COMPANY, FULL_COMPANY, STOCK_CODE))
    period_ok = period_token in normalized
    if text.strip() and not identity_ok:
        raise RuntimeError(f"company identity not found in sampled text: {path.name}")
    if text.strip() and not period_ok:
        raise RuntimeError(f"period/type token {period_token} not found in sampled text: {path.name}")
    if document_type == "年度报告" and "年度报告摘要" in normalized:
        raise RuntimeError(f"annual report summary detected: {path.name}")
    if document_type == "招股说明书" and "招股说明书" not in normalized:
        raise RuntimeError(f"prospectus marker missing: {path.name}")

    return {
        "bytes": path.stat().st_size,
        "pages": pages,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "identity_text_verified_when_extractable": identity_ok,
        "period_or_type_text_verified_when_extractable": period_ok,
        "render_verified_first_and_last_page": True,
        "sample_text_extractable": bool(text.strip()),
    }


def add_record(
    records: list[dict[str, Any]],
    seen_hashes: set[str],
    *,
    row: dict[str, Any],
    destination: Path,
    period: str,
    document_type: str,
    period_token: str,
    min_pages: int,
) -> None:
    title = clean_title(str(row.get("announcementTitle") or ""))
    source_url = static_url(row)
    final_url = download_pdf(source_url, destination)
    metadata = validate_pdf(
        destination,
        period_token=period_token,
        document_type=document_type,
        min_pages=min_pages,
    )
    if metadata["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate report detected: {destination.name}")
    seen_hashes.add(metadata["sha256"])
    records.append(
        {
            "period": period,
            "document_type": document_type,
            "title": title,
            "publication_date": row_date(row),
            "announcement_id": str(row.get("announcementId") or ""),
            "relative_path": str(destination.relative_to(ROOT)),
            "source": "巨潮资讯网信息披露文件",
            "source_url": source_url,
            "download_final_url": final_url,
            **metadata,
        }
    )


records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()

for year in range(2020, 2026):
    row = choose_annual(year)
    title = clean_title(str(row.get("announcementTitle") or ""))
    suffix = "_更新后" if any(token in title for token in ("更新后", "更正后", "修订版", "修订稿")) else ""
    add_record(
        records,
        seen_hashes,
        row=row,
        destination=ANNUAL_DIR / f"{year}_之江生物_年度报告{suffix}.pdf",
        period=str(year),
        document_type="年度报告",
        period_token=str(year),
        min_pages=70,
    )

prospectus_row = choose_prospectus()
add_record(
    records,
    seen_hashes,
    row=prospectus_row,
    destination=PROSPECTUS_DIR / "之江生物_首次公开发行股票并在科创板上市招股说明书_正式版.pdf",
    period="IPO",
    document_type="招股说明书",
    period_token="招股说明书",
    min_pages=250,
)

quarter_row = choose_periodic(
    ["2026年第三季度报告", "2026年三季度报告"],
    "2026-10-01",
    CHECKED_AS_OF,
)
quarter_period = "2026Q3"
quarter_title_label = "第三季度报告"
if quarter_row is None:
    quarter_row = choose_periodic(
        ["2026年第一季度报告", "2026年一季度报告"],
        "2026-04-01",
        "2026-05-31",
    )
    quarter_period = "2026Q1"
    quarter_title_label = "第一季度报告"
if quarter_row is None:
    raise RuntimeError("latest 2026 quarterly report not found")
add_record(
    records,
    seen_hashes,
    row=quarter_row,
    destination=QUARTER_DIR / f"{quarter_period}_之江生物_{quarter_title_label}.pdf",
    period=quarter_period,
    document_type=quarter_title_label,
    period_token="2026",
    min_pages=5,
)

half_row = choose_periodic(
    ["2026年半年度报告"],
    "2026-07-01",
    "2026-09-30",
)
if half_row is not None:
    add_record(
        records,
        seen_hashes,
        row=half_row,
        destination=SUPPLEMENT_DIR / "2026H1_之江生物_半年度报告.pdf",
        period="2026H1",
        document_type="半年度报告（补充）",
        period_token="2026",
        min_pages=60,
    )

manifest = {
    "package_name": PACKAGE,
    "company": FULL_COMPANY,
    "stock_code": STOCK_CODE,
    "checked_as_of": CHECKED_AS_OF,
    "annual_report_years": list(range(2020, 2026)),
    "annual_report_count": 6,
    "prospectus_count": 1,
    "latest_quarterly_report": clean_title(str(quarter_row.get("announcementTitle") or "")),
    "supplementary_half_year_report_included": half_row is not None,
    "pdf_count": len(records),
    "selection_notes": [
        "收录之江生物上市以来2020—2025年度报告全文，排除年度报告摘要。",
        "如同一年度存在更新后、更正后或修订版，优先选择后续版本。",
        "招股说明书采用首次公开发行正式发行版本，排除申报稿、上会稿、注册稿、招股意向书和提示性公告。",
        "截至2026年10月4日先检索2026年三季度报告；若尚未披露，则以2026年一季度报告作为最新季报。",
        "2026年半年度报告披露时间晚于一季报，作为补充定期报告单独收录，不将其称为季报。",
    ],
    "records": records,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as file_handle:
    writer = csv.writer(file_handle)
    writer.writerow(
        [
            "期间",
            "类型",
            "标题",
            "披露日期",
            "文件",
            "页数",
            "字节数",
            "SHA-256",
            "公告编号",
            "官方来源网址",
        ]
    )
    for record in records:
        writer.writerow(
            [
                record["period"],
                record["document_type"],
                record["title"],
                record["publication_date"],
                record["relative_path"],
                record["pages"],
                record["bytes"],
                record["sha256"],
                record["announcement_id"],
                record["source_url"],
            ]
        )

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as file_handle:
    for record in records:
        file_handle.write(f"{record['sha256']}  {record['relative_path']}\n")

readme_lines = [
    f"{FULL_COMPANY}（{STOCK_CODE}）定期报告与招股说明书文件包",
    "",
    f"核对日期：{CHECKED_AS_OF}",
    "",
    "收录内容：",
    "1. 2020—2025年年度报告全文，共6份；",
    "2. 首次公开发行股票并在科创板上市招股说明书正式版，共1份；",
    f"3. 最新季报：{clean_title(str(quarter_row.get('announcementTitle') or ''))}，共1份；",
]
if half_row is not None:
    readme_lines.append("4. 2026年半年度报告，共1份，作为披露时间更晚的补充定期报告单独收录。")
readme_lines.extend(
    [
        "",
        "版本口径：",
        "- 年度报告均为全文版，排除摘要；",
        "- 招股说明书为正式发行版，排除申报稿、上会稿、注册稿、招股意向书及提示性公告；",
        "- 半年度报告不是季报，已放在补充目录中。",
        "",
        "校验：",
        "- PDF文件头、文件大小与qpdf结构检查；",
        "- PDF页数、公司身份和报告期间/类型抽样核验；",
        "- 每份PDF首页和末页实际渲染检查；",
        "- SHA-256去重及ZIP完整性测试。",
    ]
)
(VERIFY_DIR / "README.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

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
    pdf_count = sum(1 for name in archive.namelist() if name.lower().endswith(".pdf"))
    if pdf_count != len(records):
        raise RuntimeError(f"ZIP PDF count mismatch: expected {len(records)}, got {pdf_count}")

print(
    "FINAL_ZIP",
    zip_path,
    "bytes",
    zip_path.stat().st_size,
    "sha256",
    sha256(zip_path),
    flush=True,
)
print(
    json.dumps(
        {
            "package_name": PACKAGE,
            "annual_reports": 6,
            "prospectus": 1,
            "latest_quarterly_report": clean_title(str(quarter_row.get("announcementTitle") or "")),
            "supplementary_half_year_report_included": half_row is not None,
            "pdf_count": len(records),
            "zip_bytes": zip_path.stat().st_size,
            "zip_sha256": sha256(zip_path),
        },
        ensure_ascii=False,
        indent=2,
    ),
    flush=True,
)
