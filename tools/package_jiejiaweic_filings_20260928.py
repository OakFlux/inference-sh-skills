from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

COMPANY = "捷佳伟创"
CODE = "300724"
YEARS = list(range(2020, 2026))
TODAY = "2026-09-28"
ROOT = Path("捷佳伟创_300724_2020-2025年报及最新季报")
ANNUAL_DIR = ROOT / "01_年度报告"
QUARTER_DIR = ROOT / "02_最新季报"
NOTES_DIR = ROOT / "03_资料说明"
TMP_DIR = Path("_tmp_jiejiaweic_filings")
RESULT_JSON = Path("jiejiaweic_filings_result.json")

CNINFO_QUERY = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_SEARCH = "https://www.cninfo.com.cn/new/information/topSearch/query"
CNINFO_STATIC = "https://static.cninfo.com.cn/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Referer": "https://www.cninfo.com.cn/",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def clean_title(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("&nbsp;", " ")
    return " ".join(value.split()).strip()


def safe_filename(value: str) -> str:
    value = clean_title(value)
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", "", value)
    return value[:150]


def get_org_id(session: requests.Session) -> str:
    candidates: list[str] = []
    for keyword in (CODE, COMPANY):
        try:
            r = session.get(CNINFO_SEARCH, params={"keyWord": keyword, "maxSecNum": 20}, timeout=60)
            print("TOP_SEARCH", keyword, r.status_code, r.url, len(r.content), flush=True)
            r.raise_for_status()
            data = r.json()
            rows = data if isinstance(data, list) else data.get("data") or data.get("result") or []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                sec_code = str(row.get("code") or row.get("secCode") or row.get("stockCode") or "")
                sec_name = str(row.get("zwjc") or row.get("secName") or row.get("name") or "")
                org_id = str(row.get("orgId") or row.get("orgid") or row.get("orgID") or "")
                if org_id and (sec_code == CODE or COMPANY in sec_name):
                    candidates.append(org_id)
        except Exception as exc:
            print("TOP_SEARCH_ERROR", keyword, repr(exc), flush=True)
    if candidates:
        print("ORG_ID_RESOLVED", candidates[0], flush=True)
        return candidates[0]
    # This fallback is harmless because the query routine also retries using the bare stock code.
    fallback = "9900033513"
    print("ORG_ID_FALLBACK", fallback, flush=True)
    return fallback


def query_announcements(
    session: requests.Session,
    org_id: str,
    category: str,
    searchkey: str,
    date_range: str,
    page_size: int = 30,
) -> list[dict[str, Any]]:
    all_rows: list[dict[str, Any]] = []
    stock_values = [f"{CODE},{org_id}", CODE]
    for stock_value in stock_values:
        for page_num in range(1, 8):
            payload = {
                "pageNum": str(page_num),
                "pageSize": str(page_size),
                "column": "szse",
                "tabName": "fulltext",
                "plate": "sz",
                "stock": stock_value,
                "searchkey": searchkey,
                "secid": "",
                "category": category,
                "trade": "",
                "seDate": date_range,
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            }
            last_exc: Exception | None = None
            for attempt in range(1, 5):
                try:
                    r = session.post(
                        CNINFO_QUERY,
                        data=payload,
                        headers={
                            **HEADERS,
                            "Accept": "application/json, text/javascript, */*; q=0.01",
                            "X-Requested-With": "XMLHttpRequest",
                            "Referer": f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={CODE}&orgId={org_id}",
                        },
                        timeout=90,
                    )
                    print("QUERY", stock_value, category, searchkey, page_num, attempt, r.status_code, len(r.content), flush=True)
                    r.raise_for_status()
                    data = r.json()
                    rows = data.get("announcements") or []
                    if rows:
                        all_rows.extend(rows)
                    total_pages = int(data.get("totalpages") or data.get("totalPages") or 1)
                    if page_num >= total_pages or not rows:
                        break
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    print("QUERY_RETRY", repr(exc), flush=True)
                    time.sleep(attempt * 2)
            if last_exc is not None:
                raise last_exc
            if page_num >= total_pages or not rows:
                break
        if all_rows:
            break
    # Deduplicate by announcement ID or source URL.
    dedup: dict[str, dict[str, Any]] = {}
    for row in all_rows:
        key = str(row.get("announcementId") or row.get("adjunctUrl") or json.dumps(row, sort_keys=True, ensure_ascii=False))
        dedup[key] = row
    rows = list(dedup.values())
    print("QUERY_RESULT_COUNT", category, searchkey, len(rows), flush=True)
    for row in rows[:80]:
        print(
            "ANN",
            row.get("announcementId"),
            clean_title(str(row.get("announcementTitle") or "")),
            row.get("announcementTime"),
            row.get("adjunctUrl"),
            flush=True,
        )
    return rows


def announcement_time(row: dict[str, Any]) -> int:
    value = row.get("announcementTime") or row.get("announcementDate") or 0
    try:
        return int(value)
    except Exception:
        return 0


def reject_title(title: str) -> bool:
    bad_terms = (
        "摘要",
        "英文版",
        "取消",
        "更正公告",
        "审计报告",
        "问询函",
        "回复",
        "提示性公告",
        "董事会",
        "监事会",
    )
    return any(term in title for term in bad_terms)


def select_annual(rows: list[dict[str, Any]], year: int) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    target = f"{year}年年度报告"
    for row in rows:
        title = clean_title(str(row.get("announcementTitle") or ""))
        if target not in title or reject_title(title) or "半年度" in title:
            continue
        if not row.get("adjunctUrl"):
            continue
        candidates.append(row)
    if not candidates:
        raise RuntimeError(f"未找到{year}年年度报告")
    # Prefer the newest filing so a later revised/update version supersedes the original.
    candidates.sort(key=announcement_time, reverse=True)
    chosen = candidates[0]
    print("SELECT_ANNUAL", year, clean_title(chosen.get("announcementTitle", "")), chosen.get("adjunctUrl"), flush=True)
    return chosen


def select_latest_quarter(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    pattern = re.compile(r"20\d{2}年(?:第一|第三)季度报告")
    for row in rows:
        title = clean_title(str(row.get("announcementTitle") or ""))
        if not pattern.search(title) or reject_title(title):
            continue
        if not row.get("adjunctUrl"):
            continue
        candidates.append(row)
    if not candidates:
        raise RuntimeError("未找到季度报告")
    candidates.sort(key=announcement_time, reverse=True)
    chosen = candidates[0]
    print("SELECT_QUARTER", clean_title(chosen.get("announcementTitle", "")), chosen.get("adjunctUrl"), flush=True)
    return chosen


def source_url(row: dict[str, Any]) -> str:
    adjunct = str(row.get("adjunctUrl") or "").lstrip("/")
    if not adjunct:
        raise RuntimeError("公告缺少PDF路径")
    return CNINFO_STATIC + adjunct


def download_pdf(session: requests.Session, url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    last_exc: Exception | None = None
    for attempt in range(1, 6):
        try:
            if part.exists():
                part.unlink()
            with session.get(
                url,
                stream=True,
                headers={**HEADERS, "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8"},
                timeout=(45, 240),
                allow_redirects=True,
            ) as r:
                print("DOWNLOAD", attempt, r.status_code, r.url, r.headers.get("content-type"), flush=True)
                r.raise_for_status()
                with part.open("wb") as f:
                    for chunk in r.iter_content(1024 * 1024):
                        if chunk:
                            f.write(chunk)
            if part.stat().st_size < 50_000:
                raise RuntimeError(f"PDF文件过小：{part.stat().st_size}")
            with part.open("rb") as f:
                if f.read(5) != b"%PDF-":
                    raise RuntimeError("下载内容不是PDF")
            part.replace(path)
            print("DOWNLOADED", path, path.stat().st_size, flush=True)
            return
        except Exception as exc:
            last_exc = exc
            print("DOWNLOAD_RETRY", attempt, repr(exc), flush=True)
            time.sleep(attempt * 3)
    raise RuntimeError(f"下载失败 {url}: {last_exc!r}")


def validate_pdf(path: Path, annual: bool) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    minimum_pages = 20 if annual else 3
    if pages < minimum_pages:
        raise RuntimeError(f"页数异常：{path}，仅{pages}页")
    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=240)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf校验失败：{path}: {qpdf.stderr[-1000:]}")
    preview_base = TMP_DIR / (path.stem + "_first")
    preview_base.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pdftoppm", "-f", "1", "-singlefile", "-png", "-r", "110", str(path), str(preview_base)],
        check=True,
        timeout=240,
        capture_output=True,
    )
    preview = preview_base.with_suffix(".png")
    if not preview.exists() or preview.stat().st_size < 5_000:
        raise RuntimeError(f"首页渲染失败：{path}")
    text_parts: list[str] = []
    for page in reader.pages[: min(5, pages)]:
        try:
            text_parts.append(page.extract_text() or "")
        except Exception:
            pass
    first_text = "".join(text_parts)
    # Text extraction is advisory because some official PDFs use unusual embedded fonts.
    text_match = COMPANY in first_text or CODE in first_text or "深圳市捷佳伟创新能源装备股份有限公司" in first_text
    print("VALIDATED", path, pages, path.stat().st_size, "text_match", text_match, flush=True)
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "first_page_rendered": True,
        "identity_text_match": text_match,
    }


def filing_date_iso(row: dict[str, Any]) -> str:
    ts = announcement_time(row)
    if ts > 10_000_000_000:
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date().isoformat()
    if ts > 0:
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        except Exception:
            pass
    adjunct = str(row.get("adjunctUrl") or "")
    m = re.search(r"/(20\d{2}-\d{2}-\d{2})/", adjunct)
    return m.group(1) if m else ""


def main() -> None:
    for path in (ROOT, TMP_DIR):
        if path.exists():
            shutil.rmtree(path)
    ANNUAL_DIR.mkdir(parents=True, exist_ok=True)
    QUARTER_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        home = session.get("https://www.cninfo.com.cn/", timeout=60)
        print("HOME", home.status_code, len(home.content), flush=True)
    except Exception as exc:
        print("HOME_WARN", repr(exc), flush=True)

    org_id = get_org_id(session)
    annual_rows = query_announcements(
        session,
        org_id,
        category="category_ndbg_szsh;",
        searchkey="",
        date_range="2020-01-01~2026-09-28",
        page_size=30,
    )
    if not annual_rows:
        annual_rows = query_announcements(
            session,
            org_id,
            category="",
            searchkey="年度报告",
            date_range="2020-01-01~2026-09-28",
            page_size=30,
        )

    quarter_rows = query_announcements(
        session,
        org_id,
        category="category_yjdbg_szsh;category_sjdbg_szsh;",
        searchkey="",
        date_range="2024-01-01~2026-09-28",
        page_size=30,
    )
    if not quarter_rows:
        quarter_rows = query_announcements(
            session,
            org_id,
            category="",
            searchkey="季度报告",
            date_range="2024-01-01~2026-09-28",
            page_size=30,
        )

    records: list[dict[str, Any]] = []
    for year in YEARS:
        row = select_annual(annual_rows, year)
        title = clean_title(str(row.get("announcementTitle") or ""))
        filename = f"捷佳伟创_300724_{year}年年度报告.pdf"
        path = ANNUAL_DIR / filename
        url = source_url(row)
        download_pdf(session, url, path)
        check = validate_pdf(path, annual=True)
        records.append(
            {
                "type": "年度报告",
                "report_year": year,
                "filename": str(path.relative_to(ROOT)),
                "source_title": title,
                "announcement_id": str(row.get("announcementId") or ""),
                "filing_date": filing_date_iso(row),
                "source_url": url,
                **check,
            }
        )

    quarter_row = select_latest_quarter(quarter_rows)
    quarter_title = clean_title(str(quarter_row.get("announcementTitle") or ""))
    quarter_filename = f"捷佳伟创_300724_{safe_filename(quarter_title)}.pdf"
    quarter_path = QUARTER_DIR / quarter_filename
    quarter_url = source_url(quarter_row)
    download_pdf(session, quarter_url, quarter_path)
    quarter_check = validate_pdf(quarter_path, annual=False)
    records.append(
        {
            "type": "最新季报",
            "filename": str(quarter_path.relative_to(ROOT)),
            "source_title": quarter_title,
            "announcement_id": str(quarter_row.get("announcementId") or ""),
            "filing_date": filing_date_iso(quarter_row),
            "source_url": quarter_url,
            **quarter_check,
        }
    )

    manifest = {
        "company": COMPANY,
        "stock_code": CODE,
        "org_id": org_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "annual_report_years": YEARS,
        "latest_quarter_title": quarter_title,
        "document_count": len(records),
        "source": "巨潮资讯网（中国证监会指定上市公司信息披露平台）",
        "records": records,
    }
    (NOTES_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (NOTES_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{item['sha256']}  {item['filename']}" for item in records) + "\n",
        encoding="utf-8",
    )
    lines = [
        f"公司：{COMPANY}（{CODE}.SZ）",
        "来源：巨潮资讯网官方披露文件",
        f"年度报告：{', '.join(str(y) for y in YEARS)}年，共{len(YEARS)}份",
        f"最新季度报告：{quarter_title}",
        f"文件总数：{len(records)}份PDF",
        "",
        "校验：每份PDF均已检查文件头、页数和qpdf结构，并完成首页渲染测试。",
        "各文件的官方PDF地址、公告日期、页数和SHA-256校验值见manifest.json。",
    ]
    (NOTES_DIR / "资料清单与来源说明.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Remove temporary render outputs so the artifact contains only requested deliverables.
    if TMP_DIR.exists():
        shutil.rmtree(TMP_DIR)

    result = {
        "artifact_root": ROOT.name,
        "document_count": len(records),
        "annual_report_years": YEARS,
        "latest_quarter_title": quarter_title,
        "records": records,
    }
    RESULT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PACKAGE_COMPLETE", json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
