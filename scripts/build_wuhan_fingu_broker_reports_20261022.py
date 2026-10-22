#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import sys
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pymupdf
import requests
from pypdf import PdfReader

AS_OF = "2026-10-22"
STOCK_CODE = "002194"
STOCK_NAME = "武汉凡谷"
ISSUER = "武汉凡谷电子技术股份有限公司"
PACKAGE = "武汉凡谷_002194_券商深度报告_截至20261022"
ROOT = Path("dist")
PACKAGE_ROOT = ROOT / PACKAGE
REPORT_DIR = PACKAGE_ROOT / "01_券商深度报告"
META_DIR = PACKAGE_ROOT / "02_清单与校验"
RENDER_DIR = ROOT / "_verification_renders"
ZIP_PATH = ROOT / f"{PACKAGE}.zip"
SUMMARY_PATH = ROOT / "package_summary.json"

REPORT_API = "https://reportapi.eastmoney.com/report/list"
SESSION = requests.Session()
SESSION.trust_env = False
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/155.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,application/pdf,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://data.eastmoney.com/report/002194.html",
})


@dataclass
class ReportRecord:
    title: str
    institution: str
    publish_date: str
    analyst: str
    rating: str
    listed_pages: int
    actual_pages: int
    info_code: str
    relative_path: str
    source_url: str
    eastmoney_info_page: str
    bytes: int
    sha256: str
    issuer_identity_verified_when_text_extractable: bool
    first_middle_last_pages_rendered: bool


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "_", str(value or ""))
    value = re.sub(r"\s+", "_", value.strip())
    return value[:110] or "未命名"


def parse_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return 0


def parse_date(value: Any) -> datetime:
    text = str(value or "")[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except Exception:
        return datetime(1900, 1, 1)


def request(url: str, *, params: dict[str, Any] | None = None, stream: bool = False,
            timeout: tuple[int, int] = (25, 600), extra_headers: dict[str, str] | None = None) -> requests.Response:
    errors: list[str] = []
    headers = dict(SESSION.headers)
    if extra_headers:
        headers.update(extra_headers)
    for attempt in range(1, 8):
        try:
            response = SESSION.get(url, params=params, headers=headers, stream=stream,
                                   timeout=timeout, allow_redirects=True)
            print("HTTP", response.status_code, "attempt", attempt,
                  "type", response.headers.get("content-type"),
                  "length", response.headers.get("content-length"),
                  "url", response.url, flush=True)
            if response.status_code in {429, 500, 502, 503, 504}:
                response.close()
                time.sleep(min(attempt * 2, 12))
                continue
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            time.sleep(min(attempt * 2, 12))
    raise RuntimeError(f"Request failed for {url}: {errors[-7:]}")


def fetch_reports() -> list[dict[str, Any]]:
    base_params = {
        "industryCode": "*", "pageSize": "100", "industry": "*", "rating": "*",
        "ratingChange": "*", "beginTime": "2000-01-01", "endTime": AS_OF,
        "fields": "", "qType": "0", "orgCode": "", "code": STOCK_CODE, "rcode": "",
    }
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_pages = 1
    page = 1
    while page <= total_pages and page <= 50:
        params = dict(base_params)
        params.update({"pageNo": str(page), "p": str(page), "pageNum": str(page), "pageNumber": str(page)})
        response = request(REPORT_API, params=params, timeout=(25, 180))
        try:
            payload = response.json()
        finally:
            response.close()
        if page == 1:
            total_pages = parse_int(payload.get("TotalPage") or payload.get("totalPage") or payload.get("totalPages")) or 1
            print("REPORT_API_TOTAL", {"pages": total_pages,
                  "count": parse_int(payload.get("TotalCount") or payload.get("totalCount") or payload.get("count"))}, flush=True)
        page_rows = payload.get("data") or []
        if not isinstance(page_rows, list):
            raise RuntimeError(f"Invalid API data on page {page}")
        if not page_rows:
            break
        for row in page_rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("infoCode") or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            rows.append(row)
        page += 1
    if not rows:
        raise RuntimeError("Eastmoney report API returned no data")
    return rows


def report_score(row: dict[str, Any]) -> float:
    title = str(row.get("title") or "")
    report_type = str(row.get("reportType") or "")
    normalized = re.sub(r"\s+", "", title)
    pages = parse_int(row.get("attachPages"))
    date = parse_date(row.get("publishDate"))
    value = min(pages, 80) * 5.0 + max(date.year - 2010, 0) * 1.5
    if "深度" in normalized or "深度" in report_type:
        value += 320
    if "首次覆盖" in normalized or "首次覆盖" in report_type:
        value += 300
    if any(token in normalized for token in ("龙头", "滤波器", "射频", "5G", "通信", "基站", "成长", "复苏", "国产")):
        value += 35
    if any(token in normalized for token in ("点评", "季报", "年报", "半年报", "快报", "业绩", "事件", "公告")):
        value -= 280
    if pages < 10:
        value -= 300
    return value


def choose_reports(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    for original in rows:
        row = dict(original)
        row["_pages"] = parse_int(row.get("attachPages"))
        row["_score"] = report_score(row)
        row["_date"] = parse_date(row.get("publishDate"))
        if row["_pages"] >= 8:
            candidates.append(row)
    candidates.sort(key=lambda item: (item["_score"], item["_pages"], item["_date"]), reverse=True)

    catalog = [{
        "title": item.get("title"),
        "institution": item.get("orgSName") or item.get("orgName"),
        "publish_date": str(item.get("publishDate") or "")[:10],
        "pages": item.get("_pages"),
        "score": item.get("_score"),
        "info_code": item.get("infoCode"),
        "report_type": item.get("reportType"),
        "analyst": item.get("researcher") or item.get("author") or "",
        "rating": item.get("emRatingName") or item.get("sRatingName") or "",
    } for item in candidates]
    print("CANDIDATE_CATALOG", json.dumps(catalog[:80], ensure_ascii=False, indent=2), flush=True)

    selected: list[dict[str, Any]] = []
    selected_codes: set[str] = set()
    used_orgs: set[str] = set()

    for item in candidates:
        if len(selected) >= 3:
            break
        code = str(item.get("infoCode") or "")
        title = str(item.get("title") or "")
        report_type = str(item.get("reportType") or "")
        org = str(item.get("orgSName") or item.get("orgName") or "")
        if code in selected_codes or org in used_orgs:
            continue
        if not ("深度" in title or "首次覆盖" in title or "深度" in report_type or "首次覆盖" in report_type):
            continue
        if any(token in title for token in ("点评", "季报", "年报", "半年报", "快报")):
            continue
        selected.append(item)
        selected_codes.add(code)
        used_orgs.add(org)

    for item in candidates:
        if len(selected) >= 3:
            break
        code = str(item.get("infoCode") or "")
        title = str(item.get("title") or "")
        org = str(item.get("orgSName") or item.get("orgName") or "")
        pages = int(item.get("_pages") or 0)
        if code in selected_codes or org in used_orgs:
            continue
        if pages < 12:
            continue
        if any(token in title for token in ("点评", "季报", "年报", "半年报", "快报", "业绩", "事件")):
            continue
        selected.append(item)
        selected_codes.add(code)
        used_orgs.add(org)

    for item in candidates:
        if len(selected) >= 3:
            break
        code = str(item.get("infoCode") or "")
        title = str(item.get("title") or "")
        if code in selected_codes or int(item.get("_pages") or 0) < 10:
            continue
        if any(token in title for token in ("季报点评", "年报点评", "半年报点评", "快报点评")):
            continue
        selected.append(item)
        selected_codes.add(code)

    if len(selected) < 2:
        raise RuntimeError(f"Only {len(selected)} suitable reports found")
    print("SELECTED_METADATA", json.dumps([{
        "title": item.get("title"), "institution": item.get("orgSName") or item.get("orgName"),
        "publish_date": str(item.get("publishDate") or "")[:10], "pages": item.get("_pages"),
        "info_code": item.get("infoCode"), "score": item.get("_score")
    } for item in selected[:3]], ensure_ascii=False, indent=2), flush=True)
    return selected[:3], catalog


def candidate_pdf_urls(row: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for key, value in row.items():
        if isinstance(value, str) and value.startswith("http"):
            if ".pdf" in value.lower() and any(token in str(key).lower() for token in ("pdf", "attach", "url")):
                urls.append(value)
    code = str(row.get("infoCode") or "").strip()
    if code:
        urls.extend([
            f"https://pdf.dfcfw.com/pdf/H3_{code}_1.pdf",
            f"https://pdf.dfcfw.com/pdf/H2_{code}_1.pdf",
            f"https://pdf.dfcfw.com/pdf/H1_{code}_1.pdf",
        ])
    return list(dict.fromkeys(urls))


def download_report(row: dict[str, Any], destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for url in candidate_pdf_urls(row):
        temp = destination.with_suffix(destination.suffix + ".part")
        temp.unlink(missing_ok=True)
        try:
            response = request(url, stream=True, timeout=(30, 900), extra_headers={"Referer": "https://data.eastmoney.com/"})
            try:
                with temp.open("wb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            handle.write(chunk)
                final_url = str(response.url)
            finally:
                response.close()
            size = temp.stat().st_size if temp.exists() else 0
            head = temp.read_bytes()[:8] if temp.exists() else b""
            if size < 50_000 or not head.startswith(b"%PDF-"):
                raise RuntimeError(f"invalid PDF bytes={size}, head={head!r}")
            temp.replace(destination)
            return final_url
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc!r}")
            temp.unlink(missing_ok=True)
    raise RuntimeError(f"Could not download report {row.get('title')}: {errors}")


def render_check(path: Path, pages: int) -> None:
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open(path)
    try:
        for index in sorted({0, pages // 2, pages - 1}):
            page = document.load_page(index)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(0.8, 0.8), alpha=False)
            output = RENDER_DIR / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{index + 1}.png"
            pix.save(output)
            if output.stat().st_size < 2500:
                raise RuntimeError(f"Suspiciously small render: {output}")
    finally:
        document.close()


def validate_pdf(path: Path, listed_pages: int) -> dict[str, Any]:
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF-"):
        raise RuntimeError(f"Invalid PDF header: {path.name}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 8:
        raise RuntimeError(f"Report too short: {path.name}, pages={pages}")
    if listed_pages and abs(pages - listed_pages) > 4:
        raise RuntimeError(f"Page-count mismatch for {path.name}: actual={pages}, listed={listed_pages}")
    text_parts: list[str] = []
    for index in sorted({0, 1, min(4, pages - 1), pages // 2, pages - 1}):
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_WARNING", path.name, index + 1, repr(exc), flush=True)
    normalized = re.sub(r"\s+", "", "\n".join(text_parts))
    identity_ok = any(token in normalized for token in (STOCK_NAME, STOCK_CODE, ISSUER, "武汉凡谷电子"))
    if len(normalized) > 200 and not identity_ok:
        raise RuntimeError(f"Issuer identity not found in sampled text for {path.name}")
    render_check(path, pages)
    return {
        "actual_pages": pages,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "issuer_identity_verified_when_text_extractable": identity_ok,
        "first_middle_last_pages_rendered": True,
    }


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    META_DIR.mkdir(parents=True, exist_ok=True)
    RENDER_DIR.mkdir(parents=True, exist_ok=True)

    rows = fetch_reports()
    selected, catalog = choose_reports(rows)
    records: list[ReportRecord] = []
    seen_hashes: set[str] = set()

    for index, row in enumerate(selected, start=1):
        info_code = str(row.get("infoCode") or "").strip()
        title = str(row.get("title") or "未命名报告").strip()
        institution = str(row.get("orgSName") or row.get("orgName") or "未知机构").strip()
        date_text = str(row.get("publishDate") or "")[:10]
        listed_pages = parse_int(row.get("attachPages"))
        filename = f"{index:02d}_{safe_name(institution)}_{safe_name(title)}_{date_text}.pdf"
        destination = REPORT_DIR / filename
        source_url = download_report(row, destination)
        metadata = validate_pdf(destination, listed_pages)
        if metadata["sha256"] in seen_hashes:
            raise RuntimeError(f"Duplicate report detected: {destination.name}")
        seen_hashes.add(metadata["sha256"])
        records.append(ReportRecord(
            title=title,
            institution=institution,
            publish_date=date_text,
            analyst=str(row.get("researcher") or row.get("author") or ""),
            rating=str(row.get("emRatingName") or row.get("sRatingName") or ""),
            listed_pages=listed_pages,
            actual_pages=metadata["actual_pages"],
            info_code=info_code,
            relative_path=str(destination.relative_to(PACKAGE_ROOT)),
            source_url=source_url,
            eastmoney_info_page=f"https://data.eastmoney.com/report/info/{info_code}.html",
            bytes=metadata["bytes"],
            sha256=metadata["sha256"],
            issuer_identity_verified_when_text_extractable=metadata["issuer_identity_verified_when_text_extractable"],
            first_middle_last_pages_rendered=True,
        ))

    readme_lines = [
        f"{STOCK_NAME}（{STOCK_CODE}）券商深度报告资料包",
        f"整理日期：{AS_OF}",
        f"报告数量：{len(records)}份",
        f"合计页数：{sum(r.actual_pages for r in records)}页",
        "",
        "筛选口径：优先公司深度、首次覆盖和长篇公司研究；排除普通季报/年报点评及短篇事件点评；尽量保持机构多样性。",
        "文件来自公开研报PDF地址，未改写正文、页面顺序或免责声明。",
        "",
    ]
    for i, record in enumerate(records, start=1):
        readme_lines.extend([
            f"{i}. {record.institution}：《{record.title}》",
            f"   日期：{record.publish_date}",
            f"   页数：{record.actual_pages}页",
            f"   分析师：{record.analyst or '见原报告'}",
            f"   评级：{record.rating or '见原报告'}",
            f"   文件：{record.relative_path}",
            f"   SHA-256：{record.sha256}",
            "",
        ])
    readme_lines.extend([
        "校验：PDF文件头、实际页数、发行人身份、首页/中间页/末页渲染、单文件SHA-256和ZIP CRC。",
        "报告中的评级、盈利预测与行业判断均对应原报告发布时点，不代表当前观点。",
    ])
    (META_DIR / "README_报告清单与来源说明.txt").write_text("\n".join(readme_lines), encoding="utf-8")

    with (META_DIR / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["序号", "机构", "标题", "日期", "分析师", "评级", "实际页数", "文件", "来源页", "SHA-256"])
        for i, record in enumerate(records, start=1):
            writer.writerow([i, record.institution, record.title, record.publish_date, record.analyst,
                             record.rating, record.actual_pages, record.relative_path,
                             record.eastmoney_info_page, record.sha256])

    (META_DIR / "manifest.json").write_text(
        json.dumps([asdict(record) for record in records], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (META_DIR / "候选报告目录.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    (META_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{record.sha256}  {record.relative_path}" for record in records) + "\n", encoding="utf-8"
    )

    ZIP_PATH.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as archive:
        for path in sorted(PACKAGE_ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(ROOT))
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")
        pdf_count = sum(name.lower().endswith(".pdf") for name in archive.namelist())
        if pdf_count != len(records):
            raise RuntimeError(f"Expected {len(records)} PDFs, found {pdf_count}")

    summary = {
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256_file(ZIP_PATH),
        "pdf_count": len(records),
        "total_pages": sum(record.actual_pages for record in records),
        "documents": [asdict(record) for record in records],
        "top_candidates": catalog[:20],
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PACKAGE_SUMMARY=" + json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
