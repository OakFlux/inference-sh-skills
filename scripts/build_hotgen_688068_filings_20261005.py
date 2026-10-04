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

import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-10-05"
ISSUER = "北京热景生物技术股份有限公司"
SHORT_NAME = "热景生物"
STOCK_CODE = "688068"
PACKAGE = f"热景生物_{STOCK_CODE}_2020-2025年报及最新季报_截至{CHECKED_AS_OF}"
ROOT = Path(PACKAGE)
ANNUAL_DIR = ROOT / "01_年度报告"
QUARTER_DIR = ROOT / "02_最新季报"
VERIFY_DIR = ROOT / "03_来源与校验"
WORK_DIR = Path("_hotgen_688068_filings_work")
RENDER_DIR = WORK_DIR / "renders"
ZIP_PATH = Path(PACKAGE + ".zip")
for directory in (ANNUAL_DIR, QUARTER_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})

CNINFO_SEARCH_URL = "https://www.cninfo.com.cn/new/information/topSearch/query"
CNINFO_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"


def strip_tags(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", value or ""))).strip()


def compact(value: str) -> str:
    return re.sub(r"[\s　]", "", strip_tags(value))


def request(method: str, url: str, *, timeout: tuple[int, int] = (20, 180), **kwargs: Any) -> requests.Response:
    errors: list[str] = []
    extra_headers = kwargs.pop("headers", {})
    headers = {**SESSION.headers, **extra_headers}
    for attempt in range(1, 8):
        response = None
        try:
            response = SESSION.request(
                method,
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
                **kwargs,
            )
            print(
                "HTTP", method, url, "attempt", attempt,
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
            if response is not None:
                response.close()
            time.sleep(min(2 * attempt, 12))
    raise RuntimeError(f"request failed for {method} {url}: {errors[-7:]}")


def get_org_id() -> str:
    response = request(
        "GET",
        CNINFO_SEARCH_URL,
        params={"keyWord": STOCK_CODE, "maxNum": 20},
        headers={
            "Accept": "application/json,text/plain,*/*",
            "Referer": f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={STOCK_CODE}",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    try:
        data = response.json()
    finally:
        response.close()
    print("TOP_SEARCH", json.dumps(data, ensure_ascii=False, indent=2), flush=True)
    candidates = data if isinstance(data, list) else data.get("data", []) if isinstance(data, dict) else []
    for item in candidates:
        code = str(item.get("code") or item.get("secCode") or item.get("stockCode") or "")
        name = str(item.get("zwjc") or item.get("secName") or item.get("name") or "")
        org_id = str(item.get("orgId") or item.get("orgid") or item.get("org_id") or "")
        if code == STOCK_CODE and org_id:
            if name and SHORT_NAME not in name:
                continue
            return org_id
    raise RuntimeError("Could not resolve CNINFO orgId for 688068")


def query_cninfo(org_id: str, *, category: str, start_date: str, end_date: str, searchkey: str = "") -> list[dict[str, Any]]:
    all_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    variants = [
        {"column": "sse", "plate": "shkcp"},
        {"column": "sse", "plate": ""},
        {"column": "", "plate": ""},
    ]
    stock_variants = [f"{STOCK_CODE},{org_id}", STOCK_CODE]
    for variant in variants:
        for stock_value in stock_variants:
            for page_num in range(1, 6):
                form = {
                    "pageNum": str(page_num),
                    "pageSize": "50",
                    "column": variant["column"],
                    "tabName": "fulltext",
                    "plate": variant["plate"],
                    "stock": stock_value,
                    "searchkey": searchkey,
                    "secid": "",
                    "category": category,
                    "trade": "",
                    "seDate": f"{start_date}~{end_date}",
                    "sortName": "",
                    "sortType": "",
                    "isHLtitle": "true",
                }
                response = request(
                    "POST",
                    CNINFO_QUERY_URL,
                    data=form,
                    headers={
                        "Accept": "application/json,text/plain,*/*",
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "Origin": "https://www.cninfo.com.cn",
                        "Referer": f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={STOCK_CODE}",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                )
                try:
                    payload = response.json()
                finally:
                    response.close()
                rows = payload.get("announcements") or payload.get("data") or []
                print(
                    "CNINFO_QUERY_RESULT", variant, stock_value, category, searchkey,
                    "page", page_num, "rows", len(rows),
                    flush=True,
                )
                for row in rows:
                    adjunct = str(row.get("adjunctUrl") or row.get("adjunct_url") or "")
                    title = strip_tags(str(row.get("announcementTitle") or row.get("title") or ""))
                    sec_code = str(row.get("secCode") or row.get("stockCode") or "")
                    sec_name = str(row.get("secName") or row.get("stockName") or "")
                    key = adjunct or f"{title}|{row.get('announcementTime')}"
                    if key in seen:
                        continue
                    if sec_code and sec_code != STOCK_CODE:
                        continue
                    if sec_name and SHORT_NAME not in sec_name:
                        continue
                    seen.add(key)
                    normalized = dict(row)
                    normalized["clean_title"] = title
                    normalized["adjunct_url"] = adjunct
                    all_rows.append(normalized)
                has_more = bool(payload.get("hasMore"))
                total_pages = int(payload.get("totalpages") or payload.get("totalPages") or 0)
                if not rows or (total_pages and page_num >= total_pages) or (not has_more and page_num >= 1):
                    break
            if all_rows:
                break
        if all_rows:
            break
    print("CNINFO_ROWS", json.dumps(all_rows, ensure_ascii=False, indent=2), flush=True)
    return all_rows


def announcement_timestamp(row: dict[str, Any]) -> int:
    value = row.get("announcementTime") or row.get("announcement_time") or 0
    try:
        return int(value)
    except Exception:
        text = str(value)
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return int(datetime.strptime(text[:19], fmt).replace(tzinfo=timezone.utc).timestamp() * 1000)
            except Exception:
                continue
    return 0


def published_date(row: dict[str, Any]) -> str:
    ts = announcement_timestamp(row)
    if ts:
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    adjunct = str(row.get("adjunct_url") or "")
    match = re.search(r"finalpage/(\d{4}-\d{2}-\d{2})/", adjunct)
    return match.group(1) if match else ""


def source_url(row: dict[str, Any]) -> str:
    adjunct = str(row.get("adjunct_url") or row.get("adjunctUrl") or "").strip()
    if not adjunct:
        raise RuntimeError(f"Announcement has no adjunctUrl: {row}")
    if adjunct.startswith("http://") or adjunct.startswith("https://"):
        return adjunct
    return "https://static.cninfo.com.cn/" + adjunct.lstrip("/")


def annual_score(row: dict[str, Any], year: int) -> tuple[int, int]:
    title = compact(row.get("clean_title", ""))
    score = 0
    if f"{year}年年度报告" in title or f"{year}年度报告" in title:
        score += 500
    if title.endswith("年度报告") or "年度报告（" in title or "年度报告(" in title:
        score += 100
    if "修订版" in title or "修订稿" in title or "修订" in title:
        score += 80
    if "更新后" in title or "更新版" in title:
        score += 70
    if "更正版" in title or "更正后" in title:
        score += 60
    if "摘要" in title:
        score -= 1000
    if any(token in title for token in ("英文版", "取消", "问询", "审核", "审计报告", "财务报表")):
        score -= 500
    return score, announcement_timestamp(row)


def select_annuals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for year in range(2020, 2026):
        candidates = [row for row in rows if f"{year}" in compact(row.get("clean_title", ""))]
        ranked = sorted(candidates, key=lambda row: annual_score(row, year), reverse=True)
        if not ranked or annual_score(ranked[0], year)[0] < 500:
            raise RuntimeError(f"No full annual report found for {year}; candidates={candidates}")
        chosen = dict(ranked[0])
        chosen["fiscal_year"] = year
        chosen["document_type"] = "年度报告"
        selected.append(chosen)
        print("SELECTED_ANNUAL", year, json.dumps(chosen, ensure_ascii=False, indent=2), flush=True)
    return selected


def quarter_rank(title: str) -> int:
    value = compact(title)
    if "第三季度报告" in value or "三季度报告" in value:
        return 3
    if "第一季度报告" in value or "一季度报告" in value:
        return 1
    return 0


def select_latest_quarter(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        title = compact(row.get("clean_title", ""))
        rank = quarter_rank(title)
        if rank == 0:
            continue
        if any(token in title for token in ("摘要", "取消", "更正公告", "修订说明")):
            continue
        item = dict(row)
        item["quarter_rank"] = rank
        candidates.append(item)
    if not candidates:
        raise RuntimeError(f"No 2026 quarterly report found; rows={rows}")
    candidates.sort(key=lambda row: (int(row["quarter_rank"]), announcement_timestamp(row)), reverse=True)
    chosen = candidates[0]
    chosen["fiscal_year"] = 2026
    chosen["document_type"] = "季度报告"
    chosen["quarter_label"] = "第三季度报告" if chosen["quarter_rank"] == 3 else "第一季度报告"
    print("SELECTED_QUARTER", json.dumps(chosen, ensure_ascii=False, indent=2), flush=True)
    return chosen


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_pdf(url: str, destination: Path, min_bytes: int) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".part")
    errors: list[str] = []
    for attempt in range(1, 8):
        temp.unlink(missing_ok=True)
        response = None
        try:
            response = request(
                "GET",
                url,
                timeout=(30, 900),
                stream=True,
                headers={
                    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
                    "Referer": "https://www.cninfo.com.cn/",
                },
            )
            with temp.open("wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        handle.write(chunk)
            final_url = str(response.url)
            response.close()
            response = None
            size = temp.stat().st_size
            head = temp.read_bytes()[:8]
            if size < min_bytes or not head.startswith(b"%PDF-"):
                raise RuntimeError(f"invalid PDF: bytes={size}, head={head!r}")
            temp.replace(destination)
            print("DOWNLOADED", destination, destination.stat().st_size, final_url, flush=True)
            return final_url
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            if response is not None:
                response.close()
            temp.unlink(missing_ok=True)
            time.sleep(min(2 * attempt, 12))
    raise RuntimeError(f"download failed for {destination.name}: {errors[-7:]}")


def render_page(path: Path, page_number: int, tag: str) -> None:
    prefix = RENDER_DIR / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{tag}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
            "-r", "96", "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    image = Path(str(prefix) + ".png")
    valid = (
        process.returncode == 0
        and image.exists()
        and image.stat().st_size > 1500
        and image.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(f"render validation failed for {path.name} page {page_number}: {process.stderr[-2000:]}")
    image.unlink()


def validate_pdf(path: Path, *, year: int, document_type: str, min_pages: int) -> dict[str, Any]:
    check = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-3000:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"unexpectedly short PDF {path.name}: pages={pages}, expected>={min_pages}")
    render_page(path, 1, "first")
    if pages > 1:
        render_page(path, pages, "last")
    indices = sorted({0, 1, 2, min(5, pages - 1), pages // 2, pages - 1})
    text_parts: list[str] = []
    for index in indices:
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_EXTRACT_WARNING", path.name, index + 1, repr(exc), flush=True)
    sample = "\n".join(text_parts)
    normalized = re.sub(r"\s+", "", sample)
    identity_ok = any(marker in normalized for marker in (SHORT_NAME, ISSUER, STOCK_CODE))
    if sample.strip() and not identity_ok:
        raise RuntimeError(f"issuer identity not found in sampled text for {path.name}")
    if sample.strip() and str(year) not in normalized:
        raise RuntimeError(f"year {year} not found in sampled text for {path.name}")
    first_text = "\n".join((reader.pages[i].extract_text() or "") for i in range(min(8, pages)))
    first_normalized = re.sub(r"\s+", "", first_text)
    if document_type == "年度报告":
        if "年度报告摘要" in first_normalized:
            raise RuntimeError(f"annual report summary detected: {path.name}")
        if first_text.strip() and "年度报告" not in first_normalized:
            raise RuntimeError(f"annual report marker missing: {path.name}")
    else:
        if first_text.strip() and not any(token in first_normalized for token in ("第一季度报告", "一季度报告", "第三季度报告", "三季度报告")):
            raise RuntimeError(f"quarterly report marker missing: {path.name}")
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "render_verified_first_and_last_page": True,
        "issuer_identity_verified_when_text_extractable": identity_ok,
        "sample_text_extractable": bool(sample.strip()),
    }


def safe_filename(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", "", value)
    return value[:120]


def main() -> None:
    org_id = get_org_id()
    annual_rows = query_cninfo(
        org_id,
        category="category_ndbg_szsh;",
        start_date="2021-01-01",
        end_date=CHECKED_AS_OF,
    )
    if len(annual_rows) < 6:
        extra = query_cninfo(
            org_id,
            category="",
            start_date="2021-01-01",
            end_date=CHECKED_AS_OF,
            searchkey="年度报告",
        )
        known = {row.get("adjunct_url") for row in annual_rows}
        annual_rows.extend(row for row in extra if row.get("adjunct_url") not in known)
    annuals = select_annuals(annual_rows)

    quarter_rows = query_cninfo(
        org_id,
        category="category_yjdbg_szsh;category_sjdbg_szsh;",
        start_date="2026-01-01",
        end_date=CHECKED_AS_OF,
    )
    if not any(quarter_rank(row.get("clean_title", "")) for row in quarter_rows):
        quarter_rows = query_cninfo(
            org_id,
            category="",
            start_date="2026-01-01",
            end_date=CHECKED_AS_OF,
            searchkey="季度报告",
        )
    latest_quarter = select_latest_quarter(quarter_rows)

    documents: list[dict[str, Any]] = []
    for row in annuals:
        year = int(row["fiscal_year"])
        title = row["clean_title"]
        suffix = "_修订版" if "修订" in compact(title) else ""
        destination = ANNUAL_DIR / f"{year}_热景生物_年度报告全文{suffix}.pdf"
        documents.append({
            "label": title,
            "document_type": "年度报告",
            "fiscal_year": year,
            "published_date": published_date(row),
            "announcement_id": row.get("announcementId") or row.get("announcement_id") or "",
            "source_url": source_url(row),
            "destination": destination,
            "min_pages": 60,
            "min_bytes": 100_000,
        })

    quarter_label = latest_quarter["quarter_label"]
    quarter_title = latest_quarter["clean_title"]
    quarter_destination = QUARTER_DIR / f"2026_热景生物_{safe_filename(quarter_label)}.pdf"
    documents.append({
        "label": quarter_title,
        "document_type": "季度报告",
        "fiscal_year": 2026,
        "published_date": published_date(latest_quarter),
        "announcement_id": latest_quarter.get("announcementId") or latest_quarter.get("announcement_id") or "",
        "source_url": source_url(latest_quarter),
        "destination": quarter_destination,
        "min_pages": 5,
        "min_bytes": 10_000,
    })

    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for document in documents:
        final_url = download_pdf(document["source_url"], document["destination"], document["min_bytes"])
        metadata = validate_pdf(
            document["destination"],
            year=int(document["fiscal_year"]),
            document_type=document["document_type"],
            min_pages=int(document["min_pages"]),
        )
        if metadata["sha256"] in seen_hashes:
            raise RuntimeError(f"duplicate PDF detected: {document['destination'].name}")
        seen_hashes.add(metadata["sha256"])
        record = {
            "label": document["label"],
            "document_type": document["document_type"],
            "fiscal_year": document["fiscal_year"],
            "published_date": document["published_date"],
            "announcement_id": document["announcement_id"],
            "source": "巨潮资讯网（法定信息披露平台）",
            "source_url": document["source_url"],
            "download_final_url": final_url,
            "relative_path": str(document["destination"].relative_to(ROOT)),
            **metadata,
        }
        records.append(record)
        print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

    manifest = {
        "issuer": ISSUER,
        "short_name": SHORT_NAME,
        "stock_code": STOCK_CODE,
        "checked_as_of": CHECKED_AS_OF,
        "org_id": org_id,
        "annual_report_years": list(range(2020, 2026)),
        "latest_quarterly_report": latest_quarter["quarter_label"],
        "document_count": len(records),
        "documents": records,
    }
    (VERIFY_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "label", "document_type", "fiscal_year", "published_date", "announcement_id",
        "source", "source_url", "download_final_url", "relative_path", "pages", "bytes",
        "sha256", "qpdf_return_code", "render_verified_first_and_last_page",
        "issuer_identity_verified_when_text_extractable", "sample_text_extractable",
    ]
    with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    (VERIFY_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{row['sha256']}  {row['relative_path']}" for row in records) + "\n",
        encoding="utf-8",
    )

    readme = [
        f"{ISSUER}（{STOCK_CODE}）定期报告资料包",
        "",
        f"核对日期：{CHECKED_AS_OF}",
        "来源：巨潮资讯网公开披露原始PDF。",
        "",
        "收录范围：",
        "- 2020—2025年度报告全文，共6份；如公司后续发布修订版，优先采用修订版。",
        f"- 截至核对日最新法定季度报告：2026年{latest_quarter['quarter_label']}，共1份。",
        "- 半年度报告不属于季度报告，因此未混入本包。",
        "",
        "校验：每份PDF均检查文件头、文件大小、页数、qpdf结构，并渲染首末页；",
        "详细来源、页数、文件大小及SHA-256见文件清单.csv、manifest.json和SHA256SUMS.txt。",
        "",
        "文件清单：",
    ]
    for row in records:
        readme.append(
            f"- {row['label']}｜{row['relative_path']}｜{row['pages']}页｜披露日{row['published_date']}"
        )
    (VERIFY_DIR / "README.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")

    ZIP_PATH.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(path))
    if not ZIP_PATH.exists() or ZIP_PATH.stat().st_size < 500_000:
        raise RuntimeError(f"ZIP creation failed or unexpectedly small: {ZIP_PATH}")
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP integrity failure at {bad}")
    print("FINAL_ZIP", ZIP_PATH, ZIP_PATH.stat().st_size, flush=True)
    print("DOCUMENT_COUNT", len(records), flush=True)
    print("TOTAL_PAGES", sum(int(row["pages"]) for row in records), flush=True)


if __name__ == "__main__":
    main()
