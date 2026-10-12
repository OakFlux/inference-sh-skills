#!/usr/bin/env python3
"""Download and package public broker research reports for Bingshan Refrigeration (000530)."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

CODE = "000530"
COMPANY = "冰山冷热"
AS_OF = "2026-10-12"
REPORT_API = "https://reportapi.eastmoney.com/report/list"
REPORT_API_V2 = "https://reportapi.eastmoney.com/report/list2"
PDF_TEMPLATE = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"
OUT_ROOT = Path("output")
PACKAGE_DIR = OUT_ROOT / f"{COMPANY}_{CODE}_券商研究报告"
PDF_DIR = PACKAGE_DIR / "01_券商研究报告"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
    "Accept": "application/pdf,text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}

# One formal company deep-dive plus two newer full broker updates.
FIXED_TARGETS = [
    {
        "infoCode": "AP202306271591738514",
        "publishDate": "2023-06-27",
        "orgSName": "信达证券",
        "researcher": "罗岸阳",
        "title": "公司深度报告：聚焦冷热事业，百年冰山再出发",
        "priority": 1,
    },
    {
        "infoCode": "AP202407121637819783",
        "publishDate": "2024-07-12",
        "orgSName": "信达证券",
        "researcher": "罗岸阳,尹圣迪",
        "title": "冰山冷热：Q2业绩稳健增长，期待设备更新机遇",
        "priority": 3,
    },
]

FALLBACK_TARGETS = [
    {
        "infoCode": "AP202404291631668413",
        "publishDate": "2024-04-29",
        "orgSName": "华安证券",
        "researcher": "张帆",
        "title": "冷热产业链完善，新兴业务持续拓展",
        "priority": 4,
    },
    {
        "infoCode": "AP202410251640507957",
        "publishDate": "2024-10-25",
        "orgSName": "华安证券",
        "researcher": "张帆",
        "title": "并购事业与新事业加速发展，利润稳步提升",
        "priority": 5,
    },
]


def clean_filename(text: str, max_len: int = 90) -> str:
    text = re.sub(r"[\\/:*?\"<>|]", "_", text).strip()
    text = re.sub(r"\s+", "", text)
    return text[:max_len] or "report"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_response_json(response: requests.Response) -> dict[str, Any]:
    try:
        return response.json()
    except Exception:
        text = response.text.strip()
        if text.startswith("{"):
            return json.loads(text)
        match = re.search(r"^[^(]*\((.*)\)\s*;?\s*$", text, flags=re.S)
        if match:
            return json.loads(match.group(1))
        raise RuntimeError(f"Unexpected report API response: {text[:300]!r}")


def fetch_report_list(session: requests.Session) -> list[dict[str, Any]]:
    params = {
        "industryCode": "*",
        "pageSize": "100",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": "2000-01-01",
        "endTime": "2030-01-01",
        "pageNo": "1",
        "fields": "",
        "qType": "0",
        "orgCode": "",
        "code": CODE,
        "rcode": "",
        "p": "1",
        "pageNum": "1",
        "pageNumber": "1",
    }
    errors: list[str] = []

    try:
        response = session.get(REPORT_API, params=params, timeout=60)
        response.raise_for_status()
        payload = parse_response_json(response)
        rows = payload.get("data") or []
        if rows:
            return rows
        errors.append(f"GET returned no rows: {payload.get('hits')}")
    except Exception as exc:
        errors.append(f"GET failed: {exc}")

    try:
        body = {
            "pageSize": 100,
            "pageNo": 1,
            "p": 1,
            "pageNum": 1,
            "pageNumber": 1,
            "beginTime": "2000-01-01",
            "endTime": "2030-01-01",
            "code": CODE,
            "industryCode": "*",
            "rating": None,
            "ratingChange": None,
            "orgCode": None,
            "rcode": "",
        }
        response = session.post(
            REPORT_API_V2,
            json=body,
            headers={**HEADERS, "Content-Type": "application/json"},
            timeout=60,
        )
        response.raise_for_status()
        payload = parse_response_json(response)
        rows = payload.get("data") or []
        if rows:
            return rows
        errors.append(f"POST returned no rows: {payload.get('hits')}")
    except Exception as exc:
        errors.append(f"POST failed: {exc}")

    print("WARNING: report list unavailable; using known public report identifiers", errors)
    return []


def normalize_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "infoCode": row.get("infoCode") or row.get("info_code") or "",
        "publishDate": str(row.get("publishDate") or row.get("publish_date") or "")[:10],
        "orgSName": row.get("orgSName") or row.get("orgName") or row.get("org_name") or "",
        "researcher": row.get("researcher") or row.get("researcherName") or row.get("author") or "",
        "title": row.get("title") or "",
        "emRatingName": row.get("emRatingName") or row.get("ratingName") or row.get("rating") or "",
        "attachPages": row.get("attachPages") or row.get("pageCount") or None,
        "attachSize": row.get("attachSize") or None,
    }


def find_latest_2025(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized = [normalize_record(row) for row in rows]
    candidates = [
        row
        for row in normalized
        if row["publishDate"].startswith("2025-05")
        and "冷热核心事业稳步发展" in row["title"]
        and row["infoCode"]
    ]
    if not candidates:
        candidates = [
            row
            for row in normalized
            if row["publishDate"].startswith("2025")
            and row["orgSName"] == "华安证券"
            and row["infoCode"]
        ]
    if not candidates:
        return None
    candidates.sort(key=lambda x: x["publishDate"], reverse=True)
    record = candidates[0]
    record["priority"] = 2
    return record


def download_pdf(
    session: requests.Session,
    record: dict[str, Any],
    ordinal: int,
) -> dict[str, Any] | None:
    info_code = record["infoCode"]
    url = PDF_TEMPLATE.format(info_code=info_code)
    date = record.get("publishDate") or "未知日期"
    org = record.get("orgSName") or "未知机构"
    title = record.get("title") or info_code
    filename = f"{ordinal:02d}_{date.replace('-', '')}_{clean_filename(org)}_{clean_filename(title)}.pdf"
    target = PDF_DIR / filename

    last_error = ""
    for attempt in range(1, 5):
        try:
            response = session.get(url, timeout=120, allow_redirects=True)
            content = response.content
            content_type = response.headers.get("Content-Type", "")
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}")
            if not content.startswith(b"%PDF"):
                raise RuntimeError(
                    f"not a PDF; content-type={content_type!r}, bytes={len(content)}, head={content[:20]!r}"
                )
            if len(content) < 20_000:
                raise RuntimeError(f"PDF too small: {len(content)} bytes")
            target.write_bytes(content)
            reader = PdfReader(str(target), strict=False)
            pages = len(reader.pages)
            if pages < 3:
                raise RuntimeError(f"unexpectedly short PDF: {pages} pages")
            # Force parser access to first and last page to catch damaged xref/page trees.
            _ = reader.pages[0].mediabox
            _ = reader.pages[-1].mediabox
            result = {
                **record,
                "filename": filename,
                "relative_path": f"01_券商研究报告/{filename}",
                "pdf_url": url,
                "detail_url": f"https://data.eastmoney.com/report/info/{info_code}.html",
                "pages": pages,
                "bytes": len(content),
                "sha256": sha256_file(target),
                "content_type": content_type,
                "downloaded_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            }
            print("DOWNLOADED", json.dumps(result, ensure_ascii=False))
            return result
        except Exception as exc:
            last_error = str(exc)
            print(f"RETRY {info_code} attempt={attempt}: {last_error}")
            target.unlink(missing_ok=True)
            time.sleep(attempt * 2)

    print(f"FAILED {info_code}: {last_error}")
    return None


def write_metadata(records: list[dict[str, Any]]) -> None:
    source_note = [
        f"{COMPANY}（{CODE}）券商研究报告文件包",
        f"整理日期：{AS_OF}",
        "",
        "筛选说明：优先收录公开渠道可直接取得、能够通过PDF结构解析的完整券商报告。",
        "本包包含1份正式公司深度报告及2份较新的完整跟踪报告；报告版权归原券商及作者所有。",
        "文件仅供研究参考，不构成投资建议。",
        "",
        "文件清单：",
    ]
    for i, row in enumerate(records, 1):
        source_note.append(
            f"{i}. {row['publishDate']}｜{row['orgSName']}｜{row['title']}｜{row['pages']}页｜{row['filename']}"
        )
        source_note.append(f"   来源页：{row['detail_url']}")
    (PACKAGE_DIR / "00_文件清单与来源说明.txt").write_text("\n".join(source_note) + "\n", encoding="utf-8")

    csv_path = PACKAGE_DIR / "文件清单.csv"
    fields = [
        "序号",
        "发布日期",
        "券商",
        "分析师",
        "报告标题",
        "评级",
        "页数",
        "文件大小",
        "文件名",
        "来源页",
        "PDF链接",
        "SHA256",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for i, row in enumerate(records, 1):
            writer.writerow(
                {
                    "序号": i,
                    "发布日期": row["publishDate"],
                    "券商": row["orgSName"],
                    "分析师": row.get("researcher", ""),
                    "报告标题": row["title"],
                    "评级": row.get("emRatingName", ""),
                    "页数": row["pages"],
                    "文件大小": row["bytes"],
                    "文件名": row["filename"],
                    "来源页": row["detail_url"],
                    "PDF链接": row["pdf_url"],
                    "SHA256": row["sha256"],
                }
            )

    manifest = {
        "company": COMPANY,
        "stock_code": CODE,
        "as_of": AS_OF,
        "selection_method": "公开完整PDF中优先选择正式深度报告与较新完整跟踪报告，最多3份",
        "documents": records,
    }
    (PACKAGE_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    checksum_lines = []
    for row in records:
        checksum_lines.append(f"{row['sha256']}  01_券商研究报告/{row['filename']}")
    for metadata_name in ["00_文件清单与来源说明.txt", "文件清单.csv", "manifest.json"]:
        path = PACKAGE_DIR / metadata_name
        checksum_lines.append(f"{sha256_file(path)}  {metadata_name}")
    (PACKAGE_DIR / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")


def make_zip(records: list[dict[str, Any]]) -> Path:
    zip_path = OUT_ROOT / f"{COMPANY}_{CODE}_券商研究报告_{len(records)}份_{AS_OF.replace('-', '')}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(PACKAGE_DIR.rglob("*")):
            if path.is_file():
                arcname = Path(PACKAGE_DIR.name) / path.relative_to(PACKAGE_DIR)
                zf.write(path, arcname.as_posix())
    with zipfile.ZipFile(zip_path, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")
    return zip_path


def main() -> int:
    OUT_ROOT.mkdir(exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(HEADERS)
    rows = fetch_report_list(session)
    print(f"REPORT_LIST_ROWS={len(rows)}")
    for row in rows:
        normalized = normalize_record(row)
        if normalized["publishDate"] >= "2024-01-01":
            print("REPORT", json.dumps(normalized, ensure_ascii=False))

    targets = list(FIXED_TARGETS)
    latest_2025 = find_latest_2025(rows)
    if latest_2025:
        targets.insert(1, latest_2025)
    else:
        targets.insert(1, FALLBACK_TARGETS[1])

    # Remove duplicates while preserving priority order.
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in sorted(targets, key=lambda x: x.get("priority", 99)):
        if item["infoCode"] not in seen:
            deduped.append(item)
            seen.add(item["infoCode"])

    records: list[dict[str, Any]] = []
    attempted: set[str] = set()
    queue = deduped + FALLBACK_TARGETS
    for candidate in queue:
        if len(records) >= 3:
            break
        if candidate["infoCode"] in attempted:
            continue
        attempted.add(candidate["infoCode"])
        downloaded = download_pdf(session, candidate, len(records) + 1)
        if downloaded:
            records.append(downloaded)

    if len(records) < 2:
        raise RuntimeError(f"Only {len(records)} complete reports downloaded; refusing to package")

    write_metadata(records)
    zip_path = make_zip(records)
    summary = {
        "zip_path": str(zip_path),
        "zip_bytes": zip_path.stat().st_size,
        "zip_sha256": sha256_file(zip_path),
        "report_count": len(records),
        "reports": [
            {
                "publishDate": r["publishDate"],
                "orgSName": r["orgSName"],
                "title": r["title"],
                "pages": r["pages"],
                "bytes": r["bytes"],
                "sha256": r["sha256"],
            }
            for r in records
        ],
    }
    (OUT_ROOT / "package_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("PACKAGE_SUMMARY", json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
