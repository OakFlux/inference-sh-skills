#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pymupdf
import requests
from pypdf import PdfReader

COMPANY = "天坛生物"
COMPANY_FULL = "北京天坛生物制品股份有限公司"
STOCK_CODE = "600161"
AS_OF = "2026-10-16"

ROOT = Path("dist_tiantan_broker")
PACKAGE_ROOT = ROOT / f"{COMPANY}_{STOCK_CODE}_券商深度报告"
REPORT_DIR = PACKAGE_ROOT / "01_券商深度报告"
VERIFY_DIR = ROOT / "_verification_renders"
ZIP_PATH = ROOT / f"{COMPANY}_{STOCK_CODE}_券商深度报告_3份_{AS_OF.replace('-', '')}.zip"
SUMMARY_PATH = ROOT / "package_summary.json"

API_URL = "https://reportapi.eastmoney.com/report/list"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": f"https://data.eastmoney.com/report/stock.jshtml?stockCode={STOCK_CODE}",
}


@dataclass
class Report:
    sequence: int
    institution: str
    analysts: str
    publish_date: str
    title: str
    rating: str
    info_code: str
    source_page: str
    pdf_url: str
    api_reported_pages: int
    pages: int
    bytes: int
    sha256: str
    local_filename: str
    relative_path: str
    first_last_page_rendered: bool
    company_identity_verified: bool
    institution_identity_verified_when_extractable: bool


def clean_jsonp(text: str) -> dict[str, Any]:
    value = text.strip()
    match = re.match(r"^[^(]+\((.*)\)\s*;?$", value, re.S)
    if match:
        value = match.group(1)
    data = json.loads(value)
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected API response type: {type(data)!r}")
    return data


def request_with_retry(session: requests.Session, method: str, url: str, **kwargs: Any) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = session.request(method, url, timeout=(25, 180), allow_redirects=True, **kwargs)
            if response.status_code in {429, 500, 502, 503, 504}:
                raise RuntimeError(f"Retryable HTTP {response.status_code}")
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < 5:
                time.sleep(attempt * 1.5)
    raise RuntimeError(f"Request failed after retries: {method} {url}: {last_error}")


def fetch_report_rows(session: requests.Session) -> list[dict[str, Any]]:
    rows_all: list[dict[str, Any]] = []
    seen: set[str] = set()
    page_no = 1
    while True:
        params = {
            "cb": "datatable",
            "pageSize": "100",
            "beginTime": "2015-01-01",
            "endTime": AS_OF,
            "pageNo": str(page_no),
            "fields": "",
            "qType": "0",
            "orgCode": "",
            "author": "",
            "code": STOCK_CODE,
            "rcode": "",
            "p": str(page_no),
            "pageNum": str(page_no),
            "pageNumber": str(page_no),
        }
        response = request_with_retry(session, "GET", API_URL, params=params)
        data = clean_jsonp(response.text)
        rows = data.get("data") or []
        if not isinstance(rows, list):
            raise RuntimeError("Eastmoney API data field is not a list")
        for row in rows:
            if not isinstance(row, dict):
                continue
            info_code = str(row.get("infoCode") or "")
            if not info_code or info_code in seen:
                continue
            seen.add(info_code)
            rows_all.append(row)
        total_pages = int(data.get("TotalPage") or 1)
        print("REPORT_API_PAGE", page_no, "ROWS", len(rows), "TOTAL_PAGES", total_pages, flush=True)
        if page_no >= total_pages or not rows:
            break
        page_no += 1
        if page_no > 20:
            raise RuntimeError("Unexpectedly many report API pages")
    if not rows_all:
        raise RuntimeError("No report records returned for 天坛生物")
    return rows_all


def report_score(row: dict[str, Any]) -> int:
    title = str(row.get("title") or "")
    institution = str(row.get("orgSName") or row.get("orgName") or "")
    pages = int(row.get("attachPages") or 0)
    score = pages * 5
    keyword_scores = [
        ("公司深度报告", 500),
        ("深度报告", 470),
        ("公司深度", 450),
        ("首次覆盖", 420),
        ("首次推荐", 390),
        ("首次", 300),
        ("深度", 260),
        ("扩张新周期", 150),
        ("龙头", 80),
    ]
    for keyword, value in keyword_scores:
        if keyword in title:
            score += value
    if "证券" in institution:
        score += 100
    if any(token in title for token in ("点评", "业绩快报", "一季报", "中报", "三季报", "年报点评", "跟踪报告")):
        score -= 180
    try:
        year = int(str(row.get("publishDate") or "")[:4])
        score += max(0, year - 2015) * 2
    except Exception:
        pass
    return score


def candidate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        institution = str(row.get("orgSName") or row.get("orgName") or "")
        title = str(row.get("title") or "")
        pages = int(row.get("attachPages") or 0)
        stock_code = str(row.get("stockCode") or "")
        if stock_code and stock_code != STOCK_CODE:
            continue
        if "证券" not in institution:
            continue
        if pages < 15 and not any(key in title for key in ("深度", "首次覆盖", "首次推荐")):
            continue
        if pages < 12:
            continue
        candidates.append(row)
    candidates.sort(key=report_score, reverse=True)
    print("CANDIDATE_COUNT", len(candidates), flush=True)
    for row in candidates[:30]:
        print(
            "CANDIDATE",
            report_score(row),
            row.get("publishDate"),
            row.get("orgSName") or row.get("orgName"),
            row.get("attachPages"),
            row.get("title"),
            row.get("infoCode"),
            flush=True,
        )
    return candidates


def safe_filename(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", "", value)
    return value[:140]


def download_pdf(session: requests.Session, row: dict[str, Any], destination: Path) -> str:
    info_code = str(row.get("infoCode") or "")
    source_page = f"https://data.eastmoney.com/report/info/{info_code}.html"
    candidates = [
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H2_{info_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf?{int(time.time() * 1000)}.pdf=",
        f"https://pdf.dfcfw.com/pdf/H2_{info_code}_1.pdf?{int(time.time() * 1000)}.pdf=",
    ]
    last_error: Exception | None = None
    for url in candidates:
        try:
            headers = dict(HEADERS)
            headers["Referer"] = source_page
            response = request_with_retry(session, "GET", url, headers=headers)
            payload = response.content
            if not payload.startswith(b"%PDF-"):
                raise RuntimeError(
                    f"Non-PDF response: {response.status_code} {response.headers.get('content-type')} {len(payload)}"
                )
            if len(payload) < 40_000:
                raise RuntimeError(f"Suspiciously small PDF: {len(payload)} bytes")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            return str(response.url)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            destination.unlink(missing_ok=True)
    raise RuntimeError(f"Unable to download report {info_code}: {last_error}")


def collect_text(reader: PdfReader) -> str:
    pages = len(reader.pages)
    indices = sorted({0, 1, 2, 3, min(8, pages - 1), max(0, pages // 2), pages - 1})
    parts: list[str] = []
    for index in indices:
        try:
            parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_EXTRACT_WARNING", index, repr(exc), flush=True)
    return "\n".join(parts)


def render_page(pdf_path: Path, page_index: int, output_path: Path) -> None:
    with pymupdf.open(pdf_path) as document:
        page = document[page_index]
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pixmap.save(output_path)
    if output_path.stat().st_size < 5_000:
        raise RuntimeError(f"Rendered page is unexpectedly small: {output_path}")


def validate_pdf(row: dict[str, Any], path: Path, sequence: int) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Encrypted report cannot be opened: {path.name}: {exc}")
    pages = len(reader.pages)
    if pages < 15:
        raise RuntimeError(f"Report is not a long-form report: {path.name}: {pages} pages")
    api_pages = int(row.get("attachPages") or 0)
    if api_pages and abs(pages - api_pages) > 2:
        raise RuntimeError(f"Page-count mismatch for {path.name}: API={api_pages}, PDF={pages}")

    text = collect_text(reader)
    normalized = re.sub(r"\s+", "", text)
    company_ok = COMPANY in normalized or COMPANY_FULL in normalized or STOCK_CODE in normalized
    if not company_ok:
        raise RuntimeError(f"Company identity not found in {path.name}")

    institution = str(row.get("orgSName") or row.get("orgName") or "")
    institution_core = institution.replace("股份有限公司", "").replace("有限责任公司", "")
    institution_ok = institution in normalized or institution_core in normalized

    first_render = VERIFY_DIR / f"{sequence:02d}_first.png"
    last_render = VERIFY_DIR / f"{sequence:02d}_last.png"
    render_page(path, 0, first_render)
    render_page(path, pages - 1, last_render)

    payload = path.read_bytes()
    return {
        "pages": pages,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "company_identity_verified": company_ok,
        "institution_identity_verified_when_extractable": institution_ok,
        "first_last_page_rendered": True,
    }


def select_and_download(session: requests.Session, candidates: list[dict[str, Any]]) -> list[Report]:
    selected: list[Report] = []
    selected_institutions: set[str] = set()
    selected_hashes: set[str] = set()
    failures: list[str] = []

    passes = [True, False]
    for unique_institution_only in passes:
        for row in candidates:
            if len(selected) >= 3:
                break
            institution = str(row.get("orgSName") or row.get("orgName") or "")
            if unique_institution_only and institution in selected_institutions:
                continue
            info_code = str(row.get("infoCode") or "")
            if any(report.info_code == info_code for report in selected):
                continue
            publish_date = str(row.get("publishDate") or "")[:10]
            title = str(row.get("title") or "").strip()
            sequence = len(selected) + 1
            filename = safe_filename(f"{sequence:02d}_{publish_date.replace('-', '')}_{institution}_{title}.pdf")
            destination = REPORT_DIR / filename
            try:
                pdf_url = download_pdf(session, row, destination)
                metadata = validate_pdf(row, destination, sequence)
                if metadata["sha256"] in selected_hashes:
                    raise RuntimeError("Duplicate PDF hash")
                selected_hashes.add(metadata["sha256"])
                selected_institutions.add(institution)
                author_raw = row.get("researcher") or row.get("author") or ""
                if isinstance(author_raw, list):
                    analysts = ", ".join(str(item).split(".", 1)[-1] for item in author_raw)
                else:
                    analysts = str(author_raw)
                rating = str(row.get("emRatingName") or row.get("sRatingName") or "")
                relative_path = f"01_券商深度报告/{filename}"
                selected.append(
                    Report(
                        sequence=sequence,
                        institution=institution,
                        analysts=analysts,
                        publish_date=publish_date,
                        title=title,
                        rating=rating,
                        info_code=info_code,
                        source_page=f"https://data.eastmoney.com/report/info/{info_code}.html",
                        pdf_url=pdf_url,
                        api_reported_pages=int(row.get("attachPages") or 0),
                        pages=int(metadata["pages"]),
                        bytes=int(metadata["bytes"]),
                        sha256=str(metadata["sha256"]),
                        local_filename=filename,
                        relative_path=relative_path,
                        first_last_page_rendered=bool(metadata["first_last_page_rendered"]),
                        company_identity_verified=bool(metadata["company_identity_verified"]),
                        institution_identity_verified_when_extractable=bool(
                            metadata["institution_identity_verified_when_extractable"]
                        ),
                    )
                )
                print("SELECTED", institution, publish_date, title, metadata["pages"], flush=True)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{institution} | {publish_date} | {title} | {info_code} | {exc}")
                destination.unlink(missing_ok=True)
                print("CANDIDATE_FAILED", failures[-1], flush=True)
        if len(selected) >= 3:
            break

    if len(selected) < 2:
        raise RuntimeError("Fewer than two complete long-form broker reports could be validated.\n" + "\n".join(failures))
    (PACKAGE_ROOT / "候选报告失败记录.txt").write_text("\n".join(failures) + "\n", encoding="utf-8")
    return selected


def write_metadata(reports: list[Report]) -> None:
    PACKAGE_ROOT.mkdir(parents=True, exist_ok=True)
    note_lines = [
        f"{COMPANY}（{STOCK_CODE}）券商深度报告资料包",
        f"整理日期：{AS_OF}",
        "",
        f"本包收录{len(reports)}份公开可完整下载、实际页数不少于15页的券商长篇公司研究报告。",
        "优先选择不同券商，并排除网页摘要、预览页、会员受限附件及短篇业绩点评。",
        "",
        "文件清单：",
    ]
    for report in reports:
        note_lines.append(
            f"{report.sequence}. {report.publish_date}｜{report.institution}｜{report.title}｜{report.pages}页"
            + (f"｜评级：{report.rating}" if report.rating else "")
        )
    note_lines.extend([
        "",
        "校验范围：PDF文件头、实际页数、天坛生物/600161身份、首末页渲染、单文件SHA-256及ZIP CRC。",
        "报告版权归相应证券研究机构及作者所有，仅供个人研究参考，不构成投资建议。",
    ])
    (PACKAGE_ROOT / "00_文件清单与来源说明.txt").write_text("\n".join(note_lines) + "\n", encoding="utf-8")

    with (PACKAGE_ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "序号", "券商", "分析师", "发布日期", "标题", "评级", "实际页数", "API记录页数",
            "字节数", "SHA256", "研报详情页", "PDF地址", "包内路径",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for report in reports:
            writer.writerow({
                "序号": report.sequence,
                "券商": report.institution,
                "分析师": report.analysts,
                "发布日期": report.publish_date,
                "标题": report.title,
                "评级": report.rating,
                "实际页数": report.pages,
                "API记录页数": report.api_reported_pages,
                "字节数": report.bytes,
                "SHA256": report.sha256,
                "研报详情页": report.source_page,
                "PDF地址": report.pdf_url,
                "包内路径": report.relative_path,
            })

    manifest = {
        "company": COMPANY,
        "company_full_name": COMPANY_FULL,
        "stock_code": STOCK_CODE,
        "as_of": AS_OF,
        "scope": "公开可完整下载、实际页数不少于15页的券商长篇公司研究报告",
        "document_count": len(reports),
        "documents": [asdict(report) for report in reports],
    }
    (PACKAGE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (PACKAGE_ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{report.sha256}  {report.relative_path}" for report in reports) + "\n",
        encoding="utf-8",
    )


def build_zip() -> None:
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    ZIP_PATH.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(PACKAGE_ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(path.relative_to(ROOT)))
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure at {bad}")
        pdf_count = sum(1 for name in archive.namelist() if name.lower().endswith(".pdf"))
        if pdf_count < 2 or pdf_count > 3:
            raise RuntimeError(f"Unexpected PDF count in ZIP: {pdf_count}")
    if ZIP_PATH.stat().st_size < 500_000:
        raise RuntimeError(f"ZIP unexpectedly small: {ZIP_PATH.stat().st_size}")


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(HEADERS)

    rows = fetch_report_rows(session)
    candidates = candidate_rows(rows)
    reports = select_and_download(session, candidates)
    write_metadata(reports)
    build_zip()

    summary = {
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest(),
        "pdf_count": len(reports),
        "documents": [
            {
                "institution": report.institution,
                "date": report.publish_date,
                "title": report.title,
                "pages": report.pages,
                "rating": report.rating,
                "analysts": report.analysts,
            }
            for report in reports
        ],
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
