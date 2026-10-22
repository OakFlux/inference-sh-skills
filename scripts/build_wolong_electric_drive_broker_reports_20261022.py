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
STOCK_CODE = "600580"
STOCK_NAME = "卧龙电驱"
ISSUER = "卧龙电气驱动集团股份有限公司"
PACKAGE = "卧龙电驱_600580_券商深度报告_3份_截至20261022"
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
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "Chrome/155.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,application/pdf,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://data.eastmoney.com/report/600580.html",
    }
)

PREFERRED_PATTERNS = [
    "卡位人形机器人",
    "航空电驱国际一流供应商",
    "新能源电机进入收获期",
]


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


def request(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    stream: bool = False,
    timeout: tuple[int, int] = (25, 600),
    extra_headers: dict[str, str] | None = None,
) -> requests.Response:
    errors: list[str] = []
    headers = dict(SESSION.headers)
    if extra_headers:
        headers.update(extra_headers)
    for attempt in range(1, 8):
        try:
            response = SESSION.get(
                url,
                params=params,
                headers=headers,
                stream=stream,
                timeout=timeout,
                allow_redirects=True,
            )
            print(
                "HTTP", response.status_code, "attempt", attempt,
                "type", response.headers.get("content-type"),
                "length", response.headers.get("content-length"),
                "url", response.url,
                flush=True,
            )
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
        "industryCode": "*",
        "pageSize": "100",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": "2000-01-01",
        "endTime": AS_OF,
        "fields": "",
        "qType": "0",
        "orgCode": "",
        "code": STOCK_CODE,
        "rcode": "",
    }
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_pages = 1
    page = 1
    while page <= total_pages and page <= 50:
        params = dict(base_params)
        params.update(
            {
                "pageNo": str(page),
                "p": str(page),
                "pageNum": str(page),
                "pageNumber": str(page),
            }
        )
        response = request(REPORT_API, params=params, timeout=(25, 180))
        try:
            payload = response.json()
        finally:
            response.close()
        if page == 1:
            total_pages = parse_int(
                payload.get("TotalPage") or payload.get("totalPage") or payload.get("totalPages")
            ) or 1
            print(
                "REPORT_API_TOTAL",
                {
                    "pages": total_pages,
                    "count": parse_int(
                        payload.get("TotalCount") or payload.get("totalCount") or payload.get("count")
                    ),
                },
                flush=True,
            )
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
        print("REPORT_PAGE", page, "ROWS", len(page_rows), "ACCUMULATED", len(rows), flush=True)
        page += 1
    if not rows:
        raise RuntimeError("Eastmoney report API returned no data")
    return rows


def score(row: dict[str, Any]) -> float:
    title = str(row.get("title") or "")
    report_type = str(row.get("reportType") or "")
    normalized = re.sub(r"\s+", "", title)
    pages = parse_int(row.get("attachPages"))
    date = parse_date(row.get("publishDate"))
    value = min(pages, 80) * 4.0 + max(date.year - 2018, 0) * 5
    if "深度" in normalized or "深度" in report_type:
        value += 300
    if "首次覆盖" in normalized or "首次覆盖" in report_type:
        value += 280
    if any(token in normalized for token in ("全球", "龙头", "航空", "机器人", "电机", "电驱", "低空")):
        value += 35
    if any(token in normalized for token in ("点评", "季报", "年报", "半年报", "快报", "业绩", "事件")):
        value -= 260
    if pages < 12:
        value -= 300
    return value


def choose_reports(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    for original in rows:
        row = dict(original)
        row["_pages"] = parse_int(row.get("attachPages"))
        row["_score"] = score(row)
        row["_date"] = parse_date(row.get("publishDate"))
        if row["_pages"] >= 10:
            candidates.append(row)
    candidates.sort(key=lambda item: (item["_score"], item["_date"], item["_pages"]), reverse=True)

    catalog = [
        {
            "title": item.get("title"),
            "institution": item.get("orgSName") or item.get("orgName"),
            "publish_date": str(item.get("publishDate") or "")[:10],
            "pages": item.get("_pages"),
            "score": item.get("_score"),
            "info_code": item.get("infoCode"),
            "report_type": item.get("reportType"),
            "analyst": item.get("researcher") or item.get("author") or "",
        }
        for item in candidates
    ]
    print("CANDIDATE_CATALOG", json.dumps(catalog[:50], ensure_ascii=False, indent=2), flush=True)

    selected: list[dict[str, Any]] = []
    selected_codes: set[str] = set()
    for pattern in PREFERRED_PATTERNS:
        match = next(
            (
                item for item in candidates
                if pattern in str(item.get("title") or "")
                and str(item.get("infoCode") or "") not in selected_codes
            ),
            None,
        )
        if match is not None:
            selected.append(match)
            selected_codes.add(str(match.get("infoCode")))

    # Fill any remaining slot with the strongest genuine deep/first-coverage report.
    for item in candidates:
        if len(selected) >= 3:
            break
        code = str(item.get("infoCode") or "")
        title = str(item.get("title") or "")
        report_type = str(item.get("reportType") or "")
        if code in selected_codes:
            continue
        if not ("深度" in title or "首次覆盖" in title or "深度" in report_type or "首次覆盖" in report_type):
            continue
        if any(token in title for token in ("点评", "季报", "年报", "半年报", "快报")):
            continue
        selected.append(item)
        selected_codes.add(code)

    if len(selected) < 2:
        raise RuntimeError(f"Only {len(selected)} suitable deep reports found")
    print(
        "SELECTED_METADATA",
        json.dumps(
            [
                {
                    "title": item.get("title"),
                    "institution": item.get("orgSName") or item.get("orgName"),
                    "publish_date": str(item.get("publishDate") or "")[:10],
                    "pages": item.get("_pages"),
                    "info_code": item.get("infoCode"),
                }
                for item in selected[:3]
            ],
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return selected[:3], catalog


def candidate_pdf_urls(row: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for key, value in row.items():
        if not isinstance(value, str):
            continue
        lower_key = str(key).lower()
        lower_value = value.lower()
        if ("pdf" in lower_key or "attach" in lower_key or "url" in lower_key) and value.startswith("http"):
            if ".pdf" in lower_value:
                urls.append(value)
    code = str(row.get("infoCode") or "").strip()
    if code:
        urls.extend(
            [
                f"https://pdf.dfcfw.com/pdf/H3_{code}_1.pdf",
                f"https://pdf.dfcfw.com/pdf/H2_{code}_1.pdf",
                f"https://pdf.dfcfw.com/pdf/H1_{code}_1.pdf",
            ]
        )
    return list(dict.fromkeys(urls))


def download_report(row: dict[str, Any], destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for url in candidate_pdf_urls(row):
        temp = destination.with_suffix(destination.suffix + ".part")
        temp.unlink(missing_ok=True)
        try:
            response = request(
                url,
                stream=True,
                timeout=(30, 900),
                extra_headers={"Referer": "https://data.eastmoney.com/"},
            )
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
            if size < 60_000 or not head.startswith(b"%PDF-"):
                raise RuntimeError(f"invalid PDF bytes={size}, head={head!r}")
            temp.replace(destination)
            print("DOWNLOADED", destination, destination.stat().st_size, final_url, flush=True)
            return final_url
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc!r}")
            temp.unlink(missing_ok=True)
    raise RuntimeError(f"Could not download report {row.get('title')}: {errors}")


def render_check(path: Path, pages: int) -> None:
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    indices = sorted({0, pages // 2, pages - 1})
    document = pymupdf.open(path)
    try:
        for index in indices:
            page = document.load_page(index)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(0.8, 0.8), alpha=False)
            output = RENDER_DIR / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{index + 1}.png"
            pix.save(output)
            if output.stat().st_size < 3_000:
                raise RuntimeError(f"Suspiciously small render: {output}")
    finally:
        document.close()


def validate_pdf(path: Path, listed_pages: int) -> dict[str, Any]:
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF-"):
        raise RuntimeError(f"Invalid PDF header: {path.name}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 10:
        raise RuntimeError(f"Report too short for deep-report package: {path.name}, pages={pages}")
    if listed_pages and abs(pages - listed_pages) > 4:
        raise RuntimeError(
            f"Page-count mismatch for {path.name}: actual={pages}, listed={listed_pages}"
        )
    text_parts: list[str] = []
    for index in sorted({0, 1, min(4, pages - 1), pages // 2, pages - 1}):
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_WARNING", path.name, index + 1, repr(exc), flush=True)
    text = "\n".join(text_parts)
    normalized = re.sub(r"\s+", "", text)
    identity_ok = any(token in normalized for token in (STOCK_NAME, STOCK_CODE, ISSUER))
    if len(normalized) > 200 and not identity_ok:
        raise RuntimeError(f"Issuer identity not found in sampled text: {path.name}")
    render_check(path, pages)
    return {
        "actual_pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "issuer_identity_verified_when_text_extractable": identity_ok,
        "first_middle_last_pages_rendered": True,
    }


def write_metadata(records: list[ReportRecord], catalog: list[dict[str, Any]]) -> None:
    META_DIR.mkdir(parents=True, exist_ok=True)
    total_pages = sum(record.actual_pages for record in records)
    lines = [
        f"{STOCK_NAME}（{STOCK_CODE}）券商深度报告资料包",
        f"整理日期：{AS_OF}",
        f"报告数量：{len(records)}份",
        f"合计页数：{total_pages}页",
        "",
        "筛选口径：优先首次覆盖、公司深度和长篇专题，排除普通业绩点评、季报点评和短篇事件报告。",
        "正文文件来自公开研报附件地址，未改写原文、页面顺序或免责声明。",
        "",
    ]
    for index, record in enumerate(records, 1):
        lines.extend(
            [
                f"{index}. {record.institution}：《{record.title}》",
                f"   日期：{record.publish_date}",
                f"   页数：{record.actual_pages}页",
                f"   分析师：{record.analyst or '见原报告'}",
                f"   评级：{record.rating or '见原报告'}",
                f"   文件：{record.relative_path}",
                f"   来源：{record.source_url}",
                f"   SHA-256：{record.sha256}",
                "",
            ]
        )
    lines.extend(
        [
            "校验项目：PDF文件头、实际页数、公司身份、首页/中间页/末页渲染、单文件SHA-256、ZIP CRC。",
            "报告中的评级、目标价、盈利预测与行业判断均对应原报告发布时点，不代表当前观点。",
        ]
    )
    (META_DIR / "README_报告清单与来源说明.txt").write_text("\n".join(lines), encoding="utf-8")

    with (META_DIR / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "序号", "券商", "标题", "日期", "分析师", "评级", "实际页数",
                "文件路径", "来源PDF", "研报详情页", "SHA-256",
            ]
        )
        for index, record in enumerate(records, 1):
            writer.writerow(
                [
                    index, record.institution, record.title, record.publish_date,
                    record.analyst, record.rating, record.actual_pages,
                    record.relative_path, record.source_url,
                    record.eastmoney_info_page, record.sha256,
                ]
            )

    (META_DIR / "manifest.json").write_text(
        json.dumps([asdict(record) for record in records], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (META_DIR / "候选报告目录.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (META_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{record.sha256}  {record.relative_path}" for record in records) + "\n",
        encoding="utf-8",
    )


def create_zip() -> None:
    ZIP_PATH.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for path in sorted(PACKAGE_ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(ROOT))
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP integrity failure: {bad}")
        pdf_count = sum(name.lower().endswith(".pdf") for name in archive.namelist())
        if pdf_count < 2 or pdf_count > 3:
            raise RuntimeError(f"Unexpected PDF count in ZIP: {pdf_count}")


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

    for index, row in enumerate(selected, 1):
        title = str(row.get("title") or "未命名报告").strip()
        institution = str(row.get("orgSName") or row.get("orgName") or "未知机构").strip()
        publish_date = str(row.get("publishDate") or "")[:10]
        info_code = str(row.get("infoCode") or "").strip()
        listed_pages = parse_int(row.get("attachPages"))
        filename = f"{index:02d}_{safe_name(institution)}_{safe_name(title)}_{publish_date}.pdf"
        destination = REPORT_DIR / filename
        source_url = download_report(row, destination)
        validation = validate_pdf(destination, listed_pages)
        if validation["sha256"] in seen_hashes:
            raise RuntimeError(f"Duplicate PDF detected: {destination.name}")
        seen_hashes.add(validation["sha256"])
        records.append(
            ReportRecord(
                title=title,
                institution=institution,
                publish_date=publish_date,
                analyst=str(row.get("researcher") or row.get("author") or ""),
                rating=str(row.get("emRatingName") or row.get("sRatingName") or ""),
                listed_pages=listed_pages,
                actual_pages=int(validation["actual_pages"]),
                info_code=info_code,
                relative_path=str(destination.relative_to(PACKAGE_ROOT)),
                source_url=source_url,
                eastmoney_info_page=f"https://data.eastmoney.com/report/info/{info_code}.html",
                bytes=int(validation["bytes"]),
                sha256=str(validation["sha256"]),
                issuer_identity_verified_when_text_extractable=bool(
                    validation["issuer_identity_verified_when_text_extractable"]
                ),
                first_middle_last_pages_rendered=True,
            )
        )

    write_metadata(records, catalog)
    create_zip()
    summary = {
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256_file(ZIP_PATH),
        "pdf_count": len(records),
        "total_pages": sum(record.actual_pages for record in records),
        "company": STOCK_NAME,
        "stock_code": STOCK_CODE,
        "as_of": AS_OF,
        "documents": [asdict(record) for record in records],
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PACKAGE_SUMMARY=" + json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
