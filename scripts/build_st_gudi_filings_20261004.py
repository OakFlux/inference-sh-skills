from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from pypdf import PdfReader

CODE = "002694"
COMPANY = "*ST顾地"
LEGAL_NAME = "顾地科技股份有限公司"
AS_OF = "2026-10-04"
EXPECTED_ANNUAL_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]

ROOT = Path("ST顾地_002694_官方披露文件")
ANNUAL_DIR = ROOT / "01_年度报告"
QUARTER_DIR = ROOT / "02_最新季报"
VERIFY_DIR = Path("_verify_st_gudi")
ZIP_NAME = "ST顾地_002694_2020-2025年报_2026最新季报.zip"

for d in (ANNUAL_DIR, QUARTER_DIR, VERIFY_DIR):
    d.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://www.cninfo.com.cn",
    "Referer": "https://www.cninfo.com.cn/",
})


def clean_title(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value or "")
    return re.sub(r"\s+", "", html.unescape(value)).strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def request_with_retry(method: str, url: str, **kwargs: Any) -> requests.Response:
    last: Exception | None = None
    for attempt in range(1, 6):
        try:
            r = SESSION.request(method, url, timeout=(20, 180), **kwargs)
            print("HTTP", attempt, r.status_code, r.headers.get("content-type"), len(r.content), r.url, flush=True)
            if r.status_code in {429, 500, 502, 503, 504}:
                time.sleep(attempt * 2)
                continue
            r.raise_for_status()
            return r
        except Exception as exc:
            last = exc
            if attempt < 5:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Request failed: {method} {url}: {last}")


def resolve_org_id() -> str:
    try:
        SESSION.get("https://www.cninfo.com.cn/new/disclosure", timeout=(20, 60))
    except Exception:
        pass
    for keyword in (CODE, "顾地科技", "ST顾地"):
        try:
            r = request_with_retry(
                "POST",
                "https://www.cninfo.com.cn/new/information/topSearch/query",
                data={"keyWord": keyword, "maxNum": "20"},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Accept": "application/json,text/plain,*/*",
                    "Referer": "https://www.cninfo.com.cn/new/disclosure",
                },
            )
            data = r.json()
            print("TOP_SEARCH", keyword, json.dumps(data, ensure_ascii=False)[:3000], flush=True)
            for item in data if isinstance(data, list) else []:
                if str(item.get("code") or "") == CODE:
                    org_id = str(item.get("orgId") or "")
                    if org_id:
                        print("ORG_ID", org_id, flush=True)
                        return org_id
        except Exception as exc:
            print("ORG_LOOKUP_FAILED", keyword, repr(exc), flush=True)
    raise RuntimeError("Could not resolve CNINFO orgId for 002694")


def query_announcements(org_id: str) -> list[dict[str, Any]]:
    endpoint = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    all_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    windows = [
        ("2020-01-01", "2020-12-31"),
        ("2021-01-01", "2021-12-31"),
        ("2022-01-01", "2022-12-31"),
        ("2023-01-01", "2023-12-31"),
        ("2024-01-01", "2024-12-31"),
        ("2025-01-01", "2025-12-31"),
        ("2026-01-01", AS_OF),
    ]
    SESSION.headers["Referer"] = f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={CODE}&orgId={org_id}"
    for start_date, end_date in windows:
        page = 1
        while True:
            payload = {
                "pageNum": str(page),
                "pageSize": "30",
                "column": "szse",
                "tabName": "fulltext",
                "plate": "sz",
                "stock": f"{CODE},{org_id}",
                "searchkey": "",
                "secid": "",
                "category": "",
                "trade": "",
                "seDate": f"{start_date}~{end_date}",
                "sortName": "time",
                "sortType": "desc",
                "isHLtitle": "true",
            }
            data = request_with_retry("POST", endpoint, data=payload).json()
            rows = data.get("announcements") or []
            total = int(data.get("totalAnnouncement") or 0)
            print("QUERY", start_date, end_date, page, len(rows), total, flush=True)
            if not rows:
                break
            for row in rows:
                ident = str(row.get("announcementId") or row.get("adjunctUrl") or "")
                if ident and ident not in seen:
                    seen.add(ident)
                    item = dict(row)
                    item["cleanTitle"] = clean_title(str(row.get("announcementTitle") or ""))
                    all_rows.append(item)
            if page * 30 >= total:
                break
            page += 1
            if page > 30:
                raise RuntimeError("Unexpected CNINFO pagination depth")
            time.sleep(0.2)
    print("ANNOUNCEMENT_COUNT", len(all_rows), flush=True)
    for row in sorted(all_rows, key=lambda x: int(x.get("announcementTime") or 0)):
        title = row["cleanTitle"]
        if any(k in title for k in ("年度报告", "季度报告")):
            print("CANDIDATE", publication_date(row), title, row.get("adjunctUrl"), row.get("adjunctSize"), flush=True)
    return all_rows


def ann_time(row: dict[str, Any]) -> int:
    try:
        return int(row.get("announcementTime") or 0)
    except Exception:
        return 0


def publication_date(row: dict[str, Any]) -> str:
    ts = ann_time(row)
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if ts else ""


def is_pdf(row: dict[str, Any]) -> bool:
    return str(row.get("adjunctUrl") or "").lower().endswith(".pdf")


def choose_documents(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    excludes = ("摘要", "英文版", "取消", "提示性公告", "关于", "审计报告")
    for year in EXPECTED_ANNUAL_YEARS:
        key = f"{year}年年度报告"
        candidates = [
            r for r in rows
            if is_pdf(r) and key in r["cleanTitle"] and not any(x in r["cleanTitle"] for x in excludes)
        ]
        if not candidates:
            raise RuntimeError(f"Missing annual report for {year}")
        candidates.sort(key=lambda r: (
            1 if any(k in r["cleanTitle"] for k in ("更新后", "更正后", "修订版", "修订后")) else 0,
            ann_time(r),
            int(r.get("adjunctSize") or 0),
        ), reverse=True)
        chosen = dict(candidates[0])
        chosen["kind"] = "年度报告"
        chosen["report_year"] = year
        selected.append(chosen)
        print("SELECT_ANNUAL", year, chosen["cleanTitle"], chosen.get("adjunctUrl"), flush=True)

    quarter_excludes = ("正文", "摘要", "英文版", "提示性公告", "更正公告", "关于")
    quarters = [
        r for r in rows
        if is_pdf(r)
        and re.search(r"20\d{2}年(?:第一|第三|一|三)季度报告", r["cleanTitle"])
        and not any(x in r["cleanTitle"] for x in quarter_excludes)
    ]
    if not quarters:
        quarters = [
            r for r in rows
            if is_pdf(r) and "季度报告" in r["cleanTitle"] and not any(x in r["cleanTitle"] for x in quarter_excludes)
        ]
    if not quarters:
        raise RuntimeError("Missing quarterly report")
    quarters.sort(key=ann_time, reverse=True)
    quarter = dict(quarters[0])
    quarter["kind"] = "最新季报"
    selected.append(quarter)
    print("SELECT_QUARTER", quarter["cleanTitle"], quarter.get("adjunctUrl"), flush=True)
    return selected


def destination_for(row: dict[str, Any]) -> Path:
    if row["kind"] == "年度报告":
        year = int(row["report_year"])
        suffix = "_修订或更新版" if any(k in row["cleanTitle"] for k in ("更新后", "更正后", "修订版", "修订后")) else ""
        return ANNUAL_DIR / f"{year}_顾地科技_年度报告{suffix}_巨潮资讯官方.pdf"
    m = re.search(r"(20\d{2})年(第一|第三|一|三)季度报告", row["cleanTitle"])
    if m:
        year, qzh = m.groups()
        q = "Q1" if qzh in ("第一", "一") else "Q3"
        return QUARTER_DIR / f"{year}_{q}_顾地科技_{qzh}季度报告_巨潮资讯官方.pdf"
    return QUARTER_DIR / f"{publication_date(row)[:4]}_顾地科技_最新季度报告_巨潮资讯官方.pdf"


def download_document(row: dict[str, Any], destination: Path) -> str:
    url = urljoin("https://static.cninfo.com.cn/", str(row.get("adjunctUrl") or "").lstrip("/"))
    r = request_with_retry("GET", url, headers={"Accept": "application/pdf,*/*", "Referer": "https://www.cninfo.com.cn/"})
    if not r.content.startswith(b"%PDF"):
        raise RuntimeError(f"Not a PDF: {url}")
    if len(r.content) < 50_000:
        raise RuntimeError(f"Suspiciously small PDF: {destination.name}: {len(r.content)}")
    destination.write_bytes(r.content)
    return url


def validate_pdf(path: Path, kind: str) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 5:
        raise RuntimeError(f"Too few pages: {path.name}: {pages}")
    samples: list[str] = []
    for idx in sorted(set([0, 1, 2, max(0, pages - 1)])):
        try:
            samples.append(reader.pages[idx].extract_text() or "")
        except Exception:
            pass
    sample_text = "\n".join(samples).lower()
    identity_ok = any(term.lower() in sample_text for term in ("顾地科技", "002694", "gudi"))
    if len(sample_text.strip()) > 200 and not identity_ok:
        raise RuntimeError(f"Identity not found in PDF sample: {path.name}")

    q = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=120)
    if q.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed: {path.name}: {q.returncode}\n{q.stderr}")

    for page_num, tag in ((1, "first"), (pages, "last")):
        outbase = VERIFY_DIR / f"{path.stem}_{tag}"
        r = subprocess.run([
            "pdftoppm", "-png", "-r", "72", "-f", str(page_num), "-l", str(page_num),
            "-singlefile", str(path), str(outbase)
        ], capture_output=True, text=True, timeout=180)
        png = Path(str(outbase) + ".png")
        if r.returncode != 0 or not png.exists() or png.stat().st_size < 1000:
            raise RuntimeError(f"Render failed: {path.name} page {page_num}: {r.stderr}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": q.returncode,
        "first_last_page_rendered": True,
        "identity_text_verified_when_extractable": bool(identity_ok or len(sample_text.strip()) <= 200),
    }


def main() -> None:
    org_id = resolve_org_id()
    rows = query_announcements(org_id)
    selected = choose_documents(rows)

    records: list[dict[str, Any]] = []
    for row in selected:
        dest = destination_for(row)
        source_url = download_document(row, dest)
        metadata = validate_pdf(dest, row["kind"])
        record = {
            "relative_path": dest.relative_to(ROOT).as_posix(),
            "filename": dest.name,
            "title": row["cleanTitle"],
            "document_type": row["kind"],
            "report_year": row.get("report_year"),
            "publication_date": publication_date(row),
            "source": "巨潮资讯网（中国证监会指定上市公司信息披露平台）",
            "source_url": source_url,
            "announcement_id": str(row.get("announcementId") or ""),
            **metadata,
        }
        records.append(record)
        print("REGISTERED", json.dumps(record, ensure_ascii=False), flush=True)

    annual_years = sorted(r["report_year"] for r in records if r["document_type"] == "年度报告")
    if annual_years != EXPECTED_ANNUAL_YEARS:
        raise RuntimeError(f"Annual year mismatch: {annual_years}")
    if sum(r["document_type"] == "最新季报" for r in records) != 1:
        raise RuntimeError("Expected exactly one latest quarterly report")

    readme = f"""{LEGAL_NAME}（现证券简称：{COMPANY}；证券代码：{CODE}）官方披露文件包

资料截止日期：{AS_OF}

收录范围：
1. 2020—2025年度完整年度报告，共6份。
2. 截至资料截止日最新已披露、严格意义上的季度报告。

说明：
- 公司股票自2026年4月30日起实施退市风险警示和其他风险警示，证券简称变更为“*ST顾地”，证券代码仍为002694。
- 截至2026年10月4日，2026年第三季度报告尚未披露，因此本包收录2026年第一季度报告；2026年半年度报告不属于季度报告，未用其替代季报。
- 已排除年报摘要、季度报告正文重复件、提示性公告、英文版、单独审计附件及重复旧版本。

来源：巨潮资讯网官方PDF。
校验：PDF文件头、实际页数、qpdf结构、公司身份信息（可提取时）、首末页渲染及ZIP CRC完整性。
"""
    (ROOT / "00_文件清单与范围说明.txt").write_text(readme, encoding="utf-8")

    with (ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["relative_path", "title", "document_type", "report_year", "publication_date", "pages", "bytes", "sha256", "source", "source_url", "announcement_id"]
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)

    manifest = {
        "company_legal_name": LEGAL_NAME,
        "current_short_name": COMPANY,
        "stock_code": CODE,
        "as_of": AS_OF,
        "scope": "2020-2025年度报告及截至当前最新严格季度报告",
        "documents": records,
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{r['sha256']}  {r['relative_path']}" for r in records) + "\n",
        encoding="utf-8",
    )

    zip_path = Path(ZIP_NAME)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=f"{ROOT.name}/{path.relative_to(ROOT).as_posix()}")
    with zipfile.ZipFile(zip_path, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure at {bad}")
        pdf_count = sum(n.lower().endswith(".pdf") for n in zf.namelist())
        if pdf_count != 7:
            raise RuntimeError(f"ZIP PDF count mismatch: {pdf_count}")

    print("FINAL_ZIP", zip_path.name, zip_path.stat().st_size, sha256_file(zip_path), flush=True)
    print("FINAL_RECORDS", json.dumps(records, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
