from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

COMPANY_CN = "中国船舶租赁"
COMPANY_EN = "CSSC (Hong Kong) Shipping Company Limited"
STOCK_CODE = "03877.HK"
HKEX_STOCK_ID = "224837"
PACKAGE_STEM = "中国船舶租赁_03877_2020-2025年报及最新财务报告"
ROOT = Path(PACKAGE_STEM)
ANNUAL_DIR = ROOT / "01_年度报告"
LATEST_DIR = ROOT / "02_最新财务报告"
NOTES_DIR = ROOT / "03_资料说明"
PREVIEW_DIR = Path("_previews_cssc_shipping_filings")
RESULT_JSON = Path("cssc_shipping_filings_result.json")
ZIP_PATH = Path(f"{PACKAGE_STEM}.zip")

for folder in (ANNUAL_DIR, LATEST_DIR, NOTES_DIR, PREVIEW_DIR):
    folder.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
}


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalized(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (value or "").upper())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_release_date(text: str) -> str | None:
    patterns = [
        r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})",
        r"(\d{1,2})[-/](\d{1,2})[-/](20\d{2})",
        r"(20\d{2})(\d{2})(\d{2})",
    ]
    for idx, pattern in enumerate(patterns):
        match = re.search(pattern, text)
        if not match:
            continue
        if idx == 1:
            day, month, year = match.groups()
        else:
            year, month, day = match.groups()
        try:
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        except ValueError:
            pass
    return None


def row_title(row: Any, link: Any) -> str:
    candidates = [
        compact(link.get_text(" ", strip=True)),
        compact(row.select_one("div.headline").get_text(" ", strip=True)) if row.select_one("div.headline") else "",
        compact(row.get_text(" ", strip=True)),
    ]
    candidates = [item for item in candidates if item]
    return max(candidates, key=len) if candidates else ""


def parse_html_rows(html: str, base_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []
    for tr in soup.select("tr"):
        link = tr.select_one("a[href*='.pdf'], a[href*='.PDF']")
        if not link:
            continue
        href = compact(link.get("href", ""))
        if not href:
            continue
        url = urljoin(base_url, href)
        title = row_title(tr, link)
        row_text = compact(tr.get_text(" ", strip=True))
        date_node = tr.select_one(".release-time")
        date_text = compact(date_node.get_text(" ", strip=True)) if date_node else row_text
        rows.append(
            {
                "title": title,
                "row_text": row_text,
                "release_date": parse_release_date(date_text) or parse_release_date(url) or "",
                "url": url,
            }
        )
    return rows


def recursive_json_rows(value: Any, output: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        text_values = {str(k).lower(): v for k, v in value.items()}
        url = ""
        for key in ("filelink", "file_link", "url", "link", "webpath", "filepath"):
            candidate = text_values.get(key)
            if isinstance(candidate, str) and ".pdf" in candidate.lower():
                url = candidate
                break
        if url:
            title_parts = []
            for key in ("title", "headline", "name", "subject", "doctitle"):
                candidate = text_values.get(key)
                if isinstance(candidate, str):
                    title_parts.append(candidate)
            row_text = " ".join(str(v) for v in value.values() if isinstance(v, (str, int, float)))
            output.append(
                {
                    "title": max(title_parts, key=len) if title_parts else row_text,
                    "row_text": row_text,
                    "release_date": parse_release_date(row_text) or parse_release_date(url) or "",
                    "url": urljoin("https://www1.hkexnews.hk/", url),
                }
            )
        for child in value.values():
            recursive_json_rows(child, output)
    elif isinstance(value, list):
        for child in value:
            recursive_json_rows(child, output)


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        url = row.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(row)
    result.sort(key=lambda item: (item.get("release_date", ""), item.get("title", "")), reverse=True)
    return result


def search_hkex(client: httpx.Client, from_date: str, to_date: str) -> list[dict[str, Any]]:
    all_rows: list[dict[str, Any]] = []
    search_page = "https://www1.hkexnews.hk/search/titlesearch.xhtml"
    try:
        client.get(search_page, params={"lang": "en"}, timeout=60)
    except Exception as exc:
        print("INITIAL_SEARCH_PAGE_WARNING", repr(exc), flush=True)

    for page_number in range(1, 16):
        form = {
            "lang": "EN",
            "stockId": HKEX_STOCK_ID,
            "sortDir": "desc",
            "sortByOptions": "DateTime",
            "category": "0",
            "market": "SEHK",
            "from": from_date,
            "to": to_date,
            "page": str(page_number),
            "searchType": "1",
            "documentType": "-1",
            "title": "",
            "t1code": "-2",
            "t2Gcode": "-2",
            "t2code": "-2",
            "rowRange": "100",
            "MB-Daterange": "0",
        }
        response = client.post(search_page, data=form, timeout=120)
        print(
            "HKEX_POST",
            json.dumps(
                {
                    "page": page_number,
                    "status": response.status_code,
                    "bytes": len(response.content),
                    "url": str(response.url),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        response.raise_for_status()
        page_rows = parse_html_rows(response.text, str(response.url))
        print("HKEX_POST_ROWS", page_number, len(page_rows), flush=True)
        before = len(dedupe_rows(all_rows))
        all_rows.extend(page_rows)
        after = len(dedupe_rows(all_rows))
        if not page_rows or after == before:
            break
        if len(page_rows) < 20:
            break

    rows = dedupe_rows(all_rows)
    if rows:
        return rows

    servlet = "https://www1.hkexnews.hk/search/titleSearchServlet.do"
    params = {
        "sortDir": "desc",
        "sortByOptions": "DateTime",
        "category": "0",
        "market": "SEHK",
        "stockId": HKEX_STOCK_ID,
        "documentType": "-1",
        "fromDate": from_date,
        "toDate": to_date,
        "title": "",
        "searchType": "1",
        "t1code": "-2",
        "t2Gcode": "-2",
        "t2code": "-2",
        "rowRange": "100",
        "lang": "EN",
    }
    response = client.get(servlet, params=params, timeout=120)
    print(
        "HKEX_SERVLET",
        json.dumps({"status": response.status_code, "bytes": len(response.content), "url": str(response.url)}),
        flush=True,
    )
    response.raise_for_status()
    try:
        payload = response.json()
        json_rows: list[dict[str, Any]] = []
        recursive_json_rows(payload, json_rows)
        rows = dedupe_rows(json_rows)
    except Exception:
        rows = dedupe_rows(parse_html_rows(response.text, str(response.url)))
    return rows


def find_annual(rows: list[dict[str, Any]], fiscal_year: int) -> dict[str, Any]:
    candidates = []
    for row in rows:
        text = compact(f"{row.get('title', '')} {row.get('row_text', '')}")
        norm = normalized(text)
        if "ANNUALREPORT" not in norm:
            continue
        if "ANNUALRESULT" in norm or "ESGREPORT" in norm or "SUSTAINABILITY" in norm or "ENVIRONMENTAL" in norm:
            continue
        if str(fiscal_year) not in norm:
            continue
        score = 0
        title_norm = normalized(row.get("title", ""))
        if title_norm in {f"ANNUALREPORT{fiscal_year}", f"{fiscal_year}ANNUALREPORT"}:
            score += 100
        if "FINANCIALSTATEMENTS" in norm:
            score += 20
        release_date = row.get("release_date", "")
        if release_date.startswith(str(fiscal_year + 1)):
            score += 15
        score -= len(title_norm) / 1000
        candidates.append((score, row))
    if not candidates:
        sample = [row.get("title", "") for row in rows[:30]]
        raise RuntimeError(f"Annual report {fiscal_year} not found. Sample titles: {sample}")
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def find_latest(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    full_candidates = []
    result_candidates = []
    for row in rows:
        text = compact(f"{row.get('title', '')} {row.get('row_text', '')}")
        norm = normalized(text)
        if "2026" not in norm:
            continue
        if "INTERIMREPORT" in norm or "HALFYEARREPORT" in norm:
            if "INTERIMRESULT" not in norm:
                score = 100
                if row.get("release_date", "").startswith("2026"):
                    score += 10
                full_candidates.append((score, row))
        if "INTERIMRESULT" in norm or ("SIXMONTHSENDED30JUNE2026" in norm and "RESULT" in norm):
            score = 50
            if row.get("release_date", "").startswith("2026"):
                score += 10
            result_candidates.append((score, row))
    if full_candidates:
        full_candidates.sort(key=lambda item: (item[0], item[1].get("release_date", "")), reverse=True)
        return full_candidates[0][1], "2026年中期报告"
    if result_candidates:
        result_candidates.sort(key=lambda item: (item[0], item[1].get("release_date", "")), reverse=True)
        return result_candidates[0][1], "2026年中期业绩公告"
    sample = [row.get("title", "") for row in rows[:50]]
    raise RuntimeError(f"Latest 2026 interim financial disclosure not found. Sample titles: {sample}")


def download_pdf(client: httpx.Client, url: str, destination: Path) -> None:
    last_error: Exception | None = None
    for attempt in range(1, 5):
        try:
            with client.stream(
                "GET",
                url,
                headers={"Referer": "https://www1.hkexnews.hk/"},
                timeout=httpx.Timeout(180.0, connect=45.0),
            ) as response:
                response.raise_for_status()
                temporary = destination.with_suffix(destination.suffix + ".part")
                with temporary.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        if chunk:
                            handle.write(chunk)
                if temporary.stat().st_size < 100_000:
                    raise RuntimeError(f"Downloaded file is too small: {temporary.stat().st_size} bytes")
                with temporary.open("rb") as handle:
                    if handle.read(5) != b"%PDF-":
                        raise RuntimeError("Downloaded content is not a PDF")
                temporary.replace(destination)
                print("DOWNLOADED", destination, destination.stat().st_size, url, flush=True)
                return
        except Exception as exc:
            last_error = exc
            print("DOWNLOAD_RETRY", attempt, url, repr(exc), flush=True)
            time.sleep(attempt * 3)
    raise RuntimeError(f"Failed to download {url}: {last_error!r}")


def extract_text(path: Path, max_pages: int = 12) -> str:
    parts: list[str] = []
    try:
        reader = PdfReader(str(path), strict=False)
        for page in reader.pages[: min(max_pages, len(reader.pages))]:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                pass
    except Exception:
        pass
    return "\n".join(parts)


def validate_pdf(path: Path, expected_year: int, document_kind: str, preview_name: str) -> dict[str, Any]:
    minimum_size = 300_000 if document_kind == "annual_report" else 120_000
    if not path.exists() or path.stat().st_size < minimum_size:
        raise RuntimeError(f"Missing or undersized PDF: {path}")
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise RuntimeError(f"Invalid PDF header: {path}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    minimum_pages = 25 if document_kind == "annual_report" else 4
    if pages < minimum_pages:
        raise RuntimeError(f"Unexpected page count for {path}: {pages}")

    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=240)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf validation failed for {path}: {check.stderr[-1200:]}")

    text = normalized(extract_text(path))
    company_markers = ["CSSCHONGKONGSHIPPING", "CSSCSHIPPING", "中國船舶租賃", "中国船舶租赁"]
    if text and not any(normalized(marker) in text for marker in company_markers):
        raise RuntimeError(f"Company marker not found in extracted PDF text: {path}")
    if text and str(expected_year) not in text:
        raise RuntimeError(f"Expected year {expected_year} not found in extracted PDF text: {path}")

    preview_prefix = PREVIEW_DIR / preview_name
    render = subprocess.run(
        [
            "pdftoppm",
            "-f",
            "1",
            "-l",
            "1",
            "-singlefile",
            "-png",
            "-r",
            "110",
            str(path),
            str(preview_prefix),
        ],
        capture_output=True,
        text=True,
        timeout=240,
    )
    preview = Path(str(preview_prefix) + ".png")
    if render.returncode != 0 or not preview.exists() or preview.stat().st_size < 2500:
        raise RuntimeError(f"First-page render failed for {path}: {render.stderr[-1000:]}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "first_page_preview": str(preview),
    }


def main() -> None:
    with httpx.Client(headers=HEADERS, follow_redirects=True, http2=True) as client:
        annual_rows: list[dict[str, Any]] = []
        for start_year, end_year in ((2021, 2023), (2024, 2026)):
            annual_rows.extend(search_hkex(client, f"{start_year}0101", f"{end_year}1231"))
        annual_rows = dedupe_rows(annual_rows)
        print("TOTAL_HKEX_ROWS", len(annual_rows), flush=True)
        for row in annual_rows[:80]:
            print("HKEX_ROW", json.dumps(row, ensure_ascii=False), flush=True)

        records: list[dict[str, Any]] = []
        for fiscal_year in range(2020, 2026):
            selected = find_annual(annual_rows, fiscal_year)
            destination = ANNUAL_DIR / f"中国船舶租赁_{fiscal_year}年年度报告.pdf"
            download_pdf(client, selected["url"], destination)
            validation = validate_pdf(destination, fiscal_year, "annual_report", f"annual_{fiscal_year}_first")
            record = {
                "filename": str(destination.relative_to(ROOT)),
                "company": COMPANY_EN,
                "stock_code": STOCK_CODE,
                "document_type": "年度报告",
                "fiscal_period": str(fiscal_year),
                "release_date": selected.get("release_date", ""),
                "official_source_url": selected["url"],
                "hkex_title": selected.get("title", ""),
                **validation,
            }
            records.append(record)
            print("VERIFIED_ANNUAL", json.dumps(record, ensure_ascii=False), flush=True)

        latest_rows = search_hkex(client, "20260701", "20261231")
        latest_selected, latest_label = find_latest(latest_rows)
        latest_destination = LATEST_DIR / f"中国船舶租赁_{latest_label}.pdf"
        download_pdf(client, latest_selected["url"], latest_destination)
        latest_kind = "interim_report" if latest_label.endswith("中期报告") else "interim_results_announcement"
        latest_validation = validate_pdf(latest_destination, 2026, latest_kind, "latest_2026_first")
        latest_record = {
            "filename": str(latest_destination.relative_to(ROOT)),
            "company": COMPANY_EN,
            "stock_code": STOCK_CODE,
            "document_type": latest_label,
            "fiscal_period": "截至2026年6月30日止六个月",
            "release_date": latest_selected.get("release_date", ""),
            "official_source_url": latest_selected["url"],
            "hkex_title": latest_selected.get("title", ""),
            **latest_validation,
        }
        records.append(latest_record)
        print("VERIFIED_LATEST", json.dumps(latest_record, ensure_ascii=False), flush=True)

    manifest = {
        "package": PACKAGE_STEM,
        "company": COMPANY_EN,
        "company_chinese": COMPANY_CN,
        "stock_code": STOCK_CODE,
        "source": "香港交易所披露易（HKEXnews）",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "annual_report_years": list(range(2020, 2026)),
        "latest_document_type": latest_label,
        "latest_period": "截至2026年6月30日止六个月",
        "file_count": len(records),
        "records": records,
    }
    (NOTES_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"{COMPANY_CN}（{STOCK_CODE}）定期财务报告资料包",
        "",
        "资料范围：2020—2025年度报告，以及截至打包日可取得的最新2026年中期财务披露。",
        "来源：香港交易所披露易（HKEXnews）官方PDF。",
        "说明：香港上市公司通常以年度报告和中期报告作为主要定期报告，本资料包将最新中期报告（如尚未发布，则为中期业绩公告）作为用户所称的‘最新季报’口径。",
        "",
        "文件清单：",
    ]
    for index, record in enumerate(records, start=1):
        lines.extend(
            [
                f"{index}. {record['filename']}",
                f"   类型：{record['document_type']}",
                f"   报告期：{record['fiscal_period']}",
                f"   发布日期：{record['release_date']}",
                f"   页数：{record['pages']}",
                f"   官方来源：{record['official_source_url']}",
                f"   SHA-256：{record['sha256']}",
            ]
        )
    (NOTES_DIR / "资料清单与来源说明.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    checksum_lines = []
    for record in records:
        checksum_lines.append(f"{record['sha256']}  {record['filename']}")
    (NOTES_DIR / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(path))

    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP integrity test failed at {bad}")
        members = archive.namelist()
    if len([name for name in members if name.lower().endswith(".pdf")]) != 7:
        raise RuntimeError(f"Expected 7 PDF files in ZIP, got {members}")

    result = {
        "zip_filename": ZIP_PATH.name,
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256(ZIP_PATH),
        "latest_document_type": latest_label,
        "latest_release_date": latest_selected.get("release_date", ""),
        "latest_source_url": latest_selected["url"],
        "pdf_count": 7,
        "members": members,
        "manifest": manifest,
    }
    RESULT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("FINAL_RESULT", json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
