from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any, Iterable

import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-10-14"
COMPANY = "松霖科技"
CODE = "603992"
PACKAGE = "松霖科技_603992_券商深度报告_3份"
ROOT = Path(PACKAGE)
REPORT_DIR = ROOT / "01_券商深度报告"
VERIFY_DIR = ROOT / "02_说明与校验"
RENDER_DIR = Path("_solex_broker_report_renders")
DEBUG_DIR = Path("_solex_broker_report_debug")
for directory in (REPORT_DIR, VERIFY_DIR, RENDER_DIR, DEBUG_DIR):
    directory.mkdir(parents=True, exist_ok=True)

PREFERRED = [
    {
        "title_parts": ["机器人+大健康", "新增长曲线清晰"],
        "org_parts": ["国盛"],
        "date": "2025-12-24",
        "filename": "2025-12-24_国盛证券_首次覆盖_机器人+大健康_新增长曲线清晰.pdf",
    },
    {
        "title_parts": ["IDM代工首创者", "厨卫+美容双驱动"],
        "org_parts": ["浙商"],
        "date": "2024-03-29",
        "filename": "2024-03-29_浙商证券_公司深度_IDM代工首创者_厨卫+美容双驱动.pdf",
    },
    {
        "title_parts": ["厨卫+美容健康双引擎驱动", "聚焦IDM赋能产品升级"],
        "org_parts": ["天风"],
        "date": "2024-01-22",
        "filename": "2024-01-22_天风证券_首次覆盖_厨卫+美容健康双引擎驱动.pdf",
    },
]

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/155 Safari/537.36",
    "Accept": "application/json,text/javascript,*/*;q=0.8",
    "Referer": f"https://data.eastmoney.com/report/{CODE}.html",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def parse_json_or_jsonp(text: str) -> Any:
    stripped = text.strip().lstrip("\ufeff")
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    match = re.search(r"^[^(]*\((.*)\)\s*;?\s*$", stripped, re.S)
    if match:
        return json.loads(match.group(1))
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return json.loads(stripped[start : end + 1])
    raise ValueError("response is not JSON/JSONP")


def rows_from_object(obj: Any) -> list[dict[str, Any]]:
    if isinstance(obj, list):
        if obj and all(isinstance(item, dict) for item in obj):
            return obj
        for item in obj:
            rows = rows_from_object(item)
            if rows:
                return rows
        return []
    if isinstance(obj, dict):
        for key in ("data", "result", "items", "list", "rows"):
            if key in obj:
                rows = rows_from_object(obj[key])
                if rows:
                    return rows
        for value in obj.values():
            rows = rows_from_object(value)
            if rows:
                return rows
    return []


def fetch_report_rows() -> list[dict[str, Any]]:
    endpoint = "https://reportapi.eastmoney.com/report/list"
    base = {
        "pageSize": 500,
        "pageNo": 1,
        "industryCode": "*",
        "industry": "*",
        "rating": "*",
        "beginTime": "2023-01-01",
        "endTime": CHECKED_AS_OF,
        "fields": "",
        "qType": 0,
        "orgCode": "",
        "code": CODE,
        "rcode": "",
        "p": 1,
        "pageNum": 1,
        "pageNumber": 1,
    }
    variants = [
        {**base, "ratingChange": "*", "cb": "datatableSolex"},
        {**base, "ratingchange": "*", "cb": "datatableSolex"},
        {**base, "ratingChange": "*"},
        {**base, "ratingchange": "*"},
    ]
    errors: list[str] = []
    for index, params in enumerate(variants, 1):
        try:
            response = SESSION.get(endpoint, params=params, headers=HEADERS, timeout=(20, 120))
            print("REPORT_API", index, response.status_code, response.url, response.headers.get("content-type"), flush=True)
            response.raise_for_status()
            (DEBUG_DIR / f"eastmoney_response_{index}.txt").write_text(response.text, encoding="utf-8", errors="replace")
            obj = parse_json_or_jsonp(response.text)
            rows = rows_from_object(obj)
            rows = [row for row in rows if isinstance(row, dict)]
            if rows:
                print("REPORT_ROWS", len(rows), flush=True)
                return rows
            errors.append(f"variant {index}: no rows")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"variant {index}: {exc!r}")
            print("REPORT_API_ERROR", errors[-1], flush=True)
    raise RuntimeError("could not obtain Eastmoney report list: " + " | ".join(errors))


def first(row: dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": first(row, ("title", "reportTitle", "REPORT_TITLE", "name")),
        "stock_name": first(row, ("stockName", "stock_name", "SECURITY_NAME_ABBR", "securityName")),
        "stock_code": first(row, ("stockCode", "stock_code", "SECURITY_CODE", "securityCode")),
        "org": first(row, ("orgSName", "orgName", "org_name", "ORG_NAME", "publishOrg")),
        "researchers": first(row, ("researcher", "researchers", "researcherName", "author", "authors")),
        "publish_date": first(row, ("publishDate", "publish_date", "PUBLISH_DATE", "date"))[:10],
        "info_code": first(row, ("infoCode", "infocode", "INFO_CODE", "reportCode")),
        "rating": first(row, ("emRatingName", "rating", "ratingName", "RATING")),
        "raw": row,
    }


def compact(text: str) -> str:
    return re.sub(r"[\s，,。：:；;（）()·•—\-_/]+", "", text or "").lower()


def match_target(report: dict[str, Any], target: dict[str, Any]) -> bool:
    title = compact(report["title"])
    org = compact(report["org"])
    return (
        all(compact(part) in title for part in target["title_parts"])
        and all(compact(part) in org for part in target["org_parts"])
        and (not target.get("date") or report["publish_date"] == target["date"])
    )


def candidate_pdf_urls(info_code: str) -> list[str]:
    now_ms = int(time.time() * 1000)
    urls: list[str] = []
    for prefix in ("H3", "H2", "H1"):
        base = f"https://pdf.dfcfw.com/pdf/{prefix}_{info_code}_1.pdf"
        urls.extend([base, f"{base}?{now_ms}.pdf"])
    return urls


def download_pdf(report: dict[str, Any], destination: Path) -> str:
    info_code = report["info_code"]
    if not info_code:
        raise RuntimeError(f"missing infoCode for {report['title']}")
    errors: list[str] = []
    headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.5",
        "Referer": f"https://data.eastmoney.com/report/zw_stock.jshtml?infocode={info_code}",
    }
    for url in candidate_pdf_urls(info_code):
        for attempt in range(1, 4):
            tmp = destination.with_suffix(".pdf.part")
            tmp.unlink(missing_ok=True)
            try:
                with SESSION.get(url, headers=headers, stream=True, timeout=(20, 240), allow_redirects=True) as response:
                    print("PDF_GET", report["publish_date"], attempt, response.status_code, response.url, response.headers.get("content-type"), flush=True)
                    response.raise_for_status()
                    with tmp.open("wb") as handle:
                        for block in response.iter_content(1024 * 1024):
                            if block:
                                handle.write(block)
                    resolved = str(response.url)
                size = tmp.stat().st_size
                head = tmp.read_bytes()[:1024]
                if size < 80_000 or b"%PDF-" not in head:
                    raise RuntimeError(f"invalid payload size={size} head={head[:30]!r}")
                tmp.replace(destination)
                return resolved
            except Exception as exc:  # noqa: BLE001
                tmp.unlink(missing_ok=True)
                errors.append(f"{url} attempt {attempt}: {exc!r}")
                time.sleep(min(attempt * 2, 6))
    raise RuntimeError("PDF download failed: " + " | ".join(errors[-8:]))


def extract_sample_text(reader: PdfReader) -> str:
    page_count = len(reader.pages)
    indices = sorted({0, min(1, page_count - 1), min(2, page_count - 1), page_count // 2, page_count - 1})
    pieces: list[str] = []
    for index in indices:
        try:
            pieces.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_WARNING", index + 1, repr(exc), flush=True)
    return compact("\n".join(pieces))


def render_page(pdf_path: Path, page: int) -> str:
    out = RENDER_DIR / f"{pdf_path.stem}_p{page}"
    proc = subprocess.run(
        ["pdftoppm", "-f", str(page), "-l", str(page), "-r", "120", "-png", "-singlefile", str(pdf_path), str(out)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    png = Path(str(out) + ".png")
    if proc.returncode != 0 or not png.exists() or png.stat().st_size < 3000:
        raise RuntimeError(f"render failed for {pdf_path.name} page {page}: {proc.stderr[-1200:]}")
    return str(png)


def validate_pdf(report: dict[str, Any], path: Path) -> dict[str, Any]:
    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {qpdf.stderr[-1600:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 10:
        raise RuntimeError(f"report is not deep enough ({pages} pages): {path.name}")
    sample = extract_sample_text(reader)
    required_any = [compact(COMPANY), compact(CODE), compact(report["title"][:12])]
    if sample and not any(marker and marker in sample for marker in required_any):
        raise RuntimeError(f"company/title validation failed for {path.name}")
    page_samples = sorted({1, max(1, (pages + 1) // 2), pages})
    render_files = [render_page(path, page) for page in page_samples]
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "rendered_pages": page_samples,
        "render_files": render_files,
    }


def rank_fallback(report: dict[str, Any]) -> tuple[int, str]:
    title = compact(report["title"])
    date = report["publish_date"]
    score = 0
    for keyword, weight in (
        ("首次覆盖", 100),
        ("公司深度", 90),
        ("深度报告", 90),
        ("双引擎", 60),
        ("idm", 40),
        ("机器人+大健康", 50),
        ("新增长曲线", 40),
    ):
        if compact(keyword) in title:
            score += weight
    return score, date


def main() -> None:
    rows = fetch_report_rows()
    reports = [normalize_row(row) for row in rows]
    reports = [report for report in reports if report["info_code"] and (report["stock_code"] in ("", CODE) or report["stock_name"] == COMPANY)]
    (DEBUG_DIR / "normalized_reports.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("NORMALIZED_REPORTS", len(reports), flush=True)
    for report in reports[:20]:
        print("REPORT", report["publish_date"], report["org"], report["info_code"], report["title"], flush=True)

    selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    used_codes: set[str] = set()
    for target in PREFERRED:
        matches = [report for report in reports if match_target(report, target)]
        if not matches:
            print("PREFERRED_NOT_FOUND", target, flush=True)
            continue
        matches.sort(key=lambda item: item["publish_date"], reverse=True)
        selected.append((matches[0], target))
        used_codes.add(matches[0]["info_code"])

    if len(selected) < 3:
        fallbacks = sorted(reports, key=rank_fallback, reverse=True)
        for report in fallbacks:
            if report["info_code"] in used_codes:
                continue
            score, _ = rank_fallback(report)
            if score <= 0:
                continue
            filename = re.sub(r"[\\/:*?\"<>|]+", "_", f"{report['publish_date']}_{report['org']}_{report['title']}.pdf")
            selected.append((report, {"filename": filename}))
            used_codes.add(report["info_code"])
            if len(selected) >= 3:
                break

    if len(selected) < 3:
        raise RuntimeError(f"only selected {len(selected)} candidate reports")

    records: list[dict[str, Any]] = []
    successful_codes: set[str] = set()
    queue = selected + [
        (report, {"filename": re.sub(r"[\\/:*?\"<>|]+", "_", f"{report['publish_date']}_{report['org']}_{report['title']}.pdf")})
        for report in sorted(reports, key=rank_fallback, reverse=True)
        if report["info_code"] not in used_codes
    ]
    errors: list[str] = []
    for report, target in queue:
        if len(records) >= 3:
            break
        if report["info_code"] in successful_codes:
            continue
        filename = target["filename"]
        destination = REPORT_DIR / filename
        try:
            resolved_url = download_pdf(report, destination)
            check = validate_pdf(report, destination)
            record = {
                "file": str(destination),
                "title": report["title"],
                "broker": report["org"],
                "researchers": report["researchers"],
                "publish_date": report["publish_date"],
                "rating": report["rating"],
                "info_code": report["info_code"],
                "source_page": f"https://data.eastmoney.com/report/zw_stock.jshtml?infocode={report['info_code']}",
                "resolved_pdf_url": resolved_url,
                **check,
            }
            records.append(record)
            successful_codes.add(report["info_code"])
            print("SELECTED_OK", record["publish_date"], record["broker"], record["pages"], record["title"], flush=True)
        except Exception as exc:  # noqa: BLE001
            destination.unlink(missing_ok=True)
            message = f"{report['publish_date']} {report['org']} {report['title']}: {exc!r}"
            errors.append(message)
            print("SELECTED_ERROR", message, flush=True)

    if len(records) != 3:
        raise RuntimeError(f"downloaded {len(records)} deep reports, expected 3; errors: {' | '.join(errors[-10:])}")
    if len({record["sha256"] for record in records}) != len(records):
        raise RuntimeError("duplicate report PDF content detected")

    manifest = {
        "company": COMPANY,
        "stock_code": CODE,
        "checked_as_of": CHECKED_AS_OF,
        "selection_rule": "优先选择首次覆盖或明确标注公司深度、且不少于10页的券商报告",
        "reports": records,
        "download_errors": errors,
    }
    (VERIFY_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with (VERIFY_DIR / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["file", "publish_date", "broker", "title", "researchers", "rating", "pages", "bytes", "sha256", "info_code", "source_page", "resolved_pdf_url"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field, "") for field in fields})
    with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as handle:
        for record in records:
            relative = Path(record["file"]).relative_to(ROOT).as_posix()
            handle.write(f"{record['sha256']}  {relative}\n")

    lines = [
        f"{COMPANY}（{CODE}）券商深度报告合集",
        f"核对日期：{CHECKED_AS_OF}",
        "",
        "本压缩包选取3份首次覆盖或明确标注公司深度、且页数不少于10页的报告。",
        "报告仅供研究参考，不构成投资建议。版权归原券商及作者所有。",
        "",
        "文件列表：",
    ]
    for index, record in enumerate(records, 1):
        lines.append(f"{index}. {record['publish_date']}｜{record['broker']}｜{record['title']}｜{record['pages']}页")
    lines.extend(["", "每份PDF均完成结构检查，并渲染首页、中间页和末页验证可读性。", "详细来源、页数、文件大小及SHA-256见02_说明与校验目录。"])
    (ROOT / "README_文件说明.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    zip_path = Path(PACKAGE + ".zip")
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.as_posix())
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        pdf_count = sum(name.lower().endswith(".pdf") for name in archive.namelist())
        if bad:
            raise RuntimeError(f"bad ZIP member: {bad}")
        if pdf_count != 3:
            raise RuntimeError(f"ZIP contains {pdf_count} PDFs, expected 3")
    print("FINAL", zip_path, zip_path.stat().st_size, sha256(zip_path), flush=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(RENDER_DIR, ignore_errors=True)
