from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-10-05"
SHORT_NAME = "贝瑞基因"
FULL_NAME = "成都市贝瑞和康基因技术股份有限公司"
STOCK_CODE = "000710"
PACKAGE = f"贝瑞基因_{STOCK_CODE}_2020-2025年报及最新季报_截至{CHECKED_AS_OF}"
ROOT = Path(PACKAGE)
ANNUAL_DIR = ROOT / "01_年度报告"
QUARTER_DIR = ROOT / "02_最新季报"
VERIFY_DIR = ROOT / "03_来源与校验"
WORK_DIR = Path("_berrygenomics_000710_work")
RENDER_DIR = WORK_DIR / "renders"
ZIP_PATH = Path(PACKAGE + ".zip")

for directory in (ANNUAL_DIR, QUARTER_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        "Accept": "application/json,text/plain,application/pdf,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://data.eastmoney.com/notices/stock/000710.html",
    }
)


def request(method: str, url: str, *, timeout: tuple[int, int] = (20, 240), **kwargs: Any) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 8):
        try:
            response = SESSION.request(method, url, timeout=timeout, allow_redirects=True, **kwargs)
            print(
                "HTTP", method, url, "attempt", attempt, "status", response.status_code,
                "type", response.headers.get("content-type"),
                "length", response.headers.get("content-length"),
                "final", response.url,
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(attempt * 2, 12))
    raise RuntimeError(f"request failed for {method} {url}: {errors[-7:]}")


def normalize_date(row: dict[str, Any]) -> str:
    for key in ("display_time", "notice_date", "sort_date", "eiTime"):
        value = str(row.get(key) or "").strip()
        match = re.search(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})", value)
        if match:
            return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return ""


def column_names(row: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in row.get("columns") or []:
        if isinstance(item, dict):
            value = str(item.get("column_name") or "").strip()
            if value:
                names.append(value)
    return names


def row_matches_stock(row: dict[str, Any]) -> bool:
    for item in row.get("codes") or []:
        if isinstance(item, dict) and str(item.get("stock_code") or "") == STOCK_CODE:
            return True
    title = str(row.get("title_ch") or row.get("title") or "")
    return STOCK_CODE in title or SHORT_NAME in title


def fetch_notice_rows() -> tuple[list[dict[str, Any]], str]:
    endpoint = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    ann_types = ("SZSA", "SZ", "SZA", "")
    best_rows: list[dict[str, Any]] = []
    best_type = ""
    for ann_type in ann_types:
        collected: list[dict[str, Any]] = []
        try:
            for page in range(1, 13):
                params = {
                    "sr": "-1",
                    "page_size": "100",
                    "page_index": str(page),
                    "client_source": "web",
                    "stock_list": STOCK_CODE,
                    "f_node": "0",
                    "s_node": "0",
                    "begin_time": "2021-01-01",
                    "end_time": CHECKED_AS_OF,
                }
                if ann_type:
                    params["ann_type"] = ann_type
                response = request("GET", endpoint, params=params, timeout=(20, 180))
                try:
                    payload = response.json()
                finally:
                    response.close()
                data = payload.get("data") if isinstance(payload, dict) else None
                rows = data.get("list", []) if isinstance(data, dict) else []
                rows = [row for row in rows if isinstance(row, dict) and row_matches_stock(row)]
                print("NOTICE_PAGE", ann_type or "NONE", page, "rows", len(rows), flush=True)
                collected.extend(rows)
                if len(rows) < 100:
                    break
            unique: dict[str, dict[str, Any]] = {}
            for row in collected:
                art_code = str(row.get("art_code") or "").strip().upper()
                if art_code:
                    unique[art_code] = row
            collected = list(unique.values())
            if len(collected) > len(best_rows):
                best_rows = collected
                best_type = ann_type or "NONE"
            if len(collected) >= 50:
                break
        except Exception as exc:  # noqa: BLE001
            print("NOTICE_TYPE_ERROR", ann_type or "NONE", repr(exc), flush=True)
    if not best_rows:
        raise RuntimeError("No announcement rows were returned for 贝瑞基因 000710")
    print("NOTICE_ROWS_COUNT", len(best_rows), "ANN_TYPE", best_type, flush=True)
    return best_rows, best_type


def clean_title(row: dict[str, Any]) -> str:
    return str(row.get("title_ch") or row.get("title") or "").strip()


def date_key(value: str) -> int:
    try:
        return int(datetime.strptime(value, "%Y-%m-%d").strftime("%Y%m%d"))
    except Exception:
        return 0


def select_annual(rows: list[dict[str, Any]], year: int) -> dict[str, Any]:
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    required = re.compile(fr"{year}年?年度报告")
    exclusions = (
        "摘要", "审计报告", "业绩快报", "业绩预告", "问询函", "回复公告", "社会责任报告",
        "董事会", "监事会", "确认意见", "专项说明", "内部控制", "募集资金", "独立董事",
    )
    for row in rows:
        title = clean_title(row)
        if not required.search(title):
            continue
        if any(word in title for word in exclusions):
            continue
        columns = column_names(row)
        score = 0
        if any("年度报告全文" in name for name in columns):
            score += 500
        if any(word in title for word in ("修订版", "修订稿", "更新后", "更正版")):
            score += 220
        if re.search(fr"{year}年?年度报告[（(]?(?:修订版|修订稿|更新后|更正版)?[）)]?$", title):
            score += 100
        if SHORT_NAME in title or FULL_NAME in title or STOCK_CODE in title:
            score += 30
        date = normalize_date(row)
        candidates.append((score, date_key(date), row))
    if not candidates:
        raise RuntimeError(f"No full annual report found for {year}")
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = dict(candidates[0][2])
    selected["title_norm"] = clean_title(selected)
    selected["date_norm"] = normalize_date(selected)
    selected["fiscal_year"] = year
    print("SELECTED_ANNUAL", year, json.dumps(selected, ensure_ascii=False, indent=2), flush=True)
    return selected


def quarter_rank(title: str) -> int:
    if re.search(r"(?:第三|三)季度报告", title):
        return 3
    if re.search(r"(?:第一|一)季度报告", title):
        return 1
    return 0


def select_latest_quarter(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[tuple[int, int, int, dict[str, Any]]] = []
    for row in rows:
        title = clean_title(row)
        match = re.search(r"(20\d{2})年?(?:第?[一三]|第一|第三)季度报告", title)
        rank = quarter_rank(title)
        if not match or not rank:
            continue
        if any(word in title for word in ("摘要", "业绩说明会", "问询", "回复")):
            continue
        year = int(match.group(1))
        if year < 2025:
            continue
        columns = column_names(row)
        score = 0
        if any("季度报告全文" in name for name in columns):
            score += 100
        if any(word in title for word in ("修订版", "更正版", "更新后")):
            score += 50
        candidates.append((year, rank, date_key(normalize_date(row)) + score, row))
    if not candidates:
        raise RuntimeError("No recent first- or third-quarter report found")
    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    year, rank, _, source = candidates[0]
    selected = dict(source)
    selected["title_norm"] = clean_title(selected)
    selected["date_norm"] = normalize_date(selected)
    selected["fiscal_year"] = year
    selected["quarter_rank"] = rank
    selected["quarter_label"] = "第三季度报告" if rank == 3 else "第一季度报告"
    print("SELECTED_QUARTER", json.dumps(selected, ensure_ascii=False, indent=2), flush=True)
    return selected


def latest_half_year_note(rows: list[dict[str, Any]]) -> dict[str, str] | None:
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for row in rows:
        title = clean_title(row)
        match = re.search(r"(20\d{2})年?半年度报告", title)
        if not match or "摘要" in title:
            continue
        year = int(match.group(1))
        candidates.append((year, date_key(normalize_date(row)), row))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    row = candidates[0][2]
    return {"title": clean_title(row), "published_date": normalize_date(row)}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_pdf(art_code: str, destination: Path) -> str:
    candidates = [
        f"https://pdf.dfcfw.com/pdf/H2_{art_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{art_code}_1.pdf",
    ]
    errors: list[str] = []
    for url in candidates:
        for attempt in range(1, 5):
            temp = destination.with_suffix(destination.suffix + ".part")
            temp.unlink(missing_ok=True)
            response = None
            try:
                response = SESSION.get(url, stream=True, timeout=(25, 600), allow_redirects=True)
                print(
                    "PDF", url, "attempt", attempt, "status", response.status_code,
                    "type", response.headers.get("content-type"),
                    "length", response.headers.get("content-length"),
                    "final", response.url,
                    flush=True,
                )
                response.raise_for_status()
                with temp.open("wb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            handle.write(chunk)
                size = temp.stat().st_size
                head = temp.read_bytes()[:8]
                if size < 20_000 or not head.startswith(b"%PDF-"):
                    raise RuntimeError(f"invalid PDF size={size}, head={head!r}")
                temp.replace(destination)
                return str(response.url)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{url} attempt {attempt}: {exc!r}")
                temp.unlink(missing_ok=True)
                time.sleep(min(attempt * 2, 8))
            finally:
                if response is not None:
                    response.close()
    raise RuntimeError(f"download failed for {destination.name}: {errors[-8:]}")


def render_page(path: Path, page_number: int, tag: str) -> None:
    prefix = RENDER_DIR / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{tag}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
            "-r", "84", "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    image = Path(str(prefix) + ".png")
    valid = (
        process.returncode == 0
        and image.exists()
        and image.stat().st_size > 1000
        and image.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(f"render failed for {path.name} page {page_number}: {process.stderr[-1500:]}")
    image.unlink()


def validate_pdf(path: Path, year: int, document_type: str) -> dict[str, Any]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-2500:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    min_pages = 60 if document_type == "年度报告" else 5
    if pages < min_pages:
        raise RuntimeError(f"unexpectedly short PDF {path.name}: {pages} pages")
    render_page(path, 1, "first")
    if pages > 1:
        render_page(path, pages, "last")
    indices = sorted({0, 1, 2, min(5, pages - 1), max(0, pages // 2), pages - 1})
    sample = "\n".join((reader.pages[index].extract_text() or "") for index in indices)
    normalized = re.sub(r"\s+", "", sample)
    identity_ok = any(marker in normalized for marker in (SHORT_NAME, FULL_NAME, STOCK_CODE, "贝瑞和康"))
    if sample.strip() and not identity_ok:
        raise RuntimeError(f"issuer identity not found in sampled text for {path.name}")
    if sample.strip() and str(year) not in normalized:
        raise RuntimeError(f"report year {year} not found in sampled text for {path.name}")
    first = "\n".join((reader.pages[index].extract_text() or "") for index in range(min(6, pages)))
    first_norm = re.sub(r"\s+", "", first)
    if document_type == "年度报告":
        if "年度报告摘要" in first_norm:
            raise RuntimeError(f"annual-report summary detected: {path.name}")
        if first.strip() and "年度报告" not in first_norm:
            raise RuntimeError(f"annual-report marker missing: {path.name}")
    else:
        if first.strip() and not re.search(r"(?:第一|一|第三|三)季度报告", first_norm):
            raise RuntimeError(f"quarterly-report marker missing: {path.name}")
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "render_verified_first_and_last_page": True,
        "issuer_identity_verified_when_text_extractable": identity_ok,
        "sample_text_extractable": bool(sample.strip()),
    }


def main() -> None:
    rows, ann_type = fetch_notice_rows()
    annual_rows = [select_annual(rows, year) for year in range(2020, 2026)]
    quarter_row = select_latest_quarter(rows)
    half_year = latest_half_year_note(rows)

    targets: list[dict[str, Any]] = []
    for row in annual_rows:
        year = int(row["fiscal_year"])
        title = str(row["title_norm"])
        suffix = "_修订版" if any(word in title for word in ("修订版", "修订稿", "更正版", "更新后")) else ""
        targets.append(
            {
                "label": title,
                "document_type": "年度报告",
                "year": year,
                "published_date": row["date_norm"],
                "art_code": str(row.get("art_code") or "").upper(),
                "destination": ANNUAL_DIR / f"{year}_贝瑞基因_年度报告全文{suffix}.pdf",
                "columns": column_names(row),
            }
        )

    q_year = int(quarter_row["fiscal_year"])
    q_rank = int(quarter_row["quarter_rank"])
    q_code = "Q3" if q_rank == 3 else "Q1"
    targets.append(
        {
            "label": quarter_row["title_norm"],
            "document_type": "季度报告",
            "year": q_year,
            "published_date": quarter_row["date_norm"],
            "art_code": str(quarter_row.get("art_code") or "").upper(),
            "destination": QUARTER_DIR / f"{q_year}_{q_code}_贝瑞基因_{quarter_row['quarter_label']}.pdf",
            "columns": column_names(quarter_row),
        }
    )

    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for target in targets:
        destination: Path = target["destination"]
        final_url = download_pdf(target["art_code"], destination)
        metadata = validate_pdf(destination, int(target["year"]), target["document_type"])
        if metadata["sha256"] in seen_hashes:
            raise RuntimeError(f"duplicate PDF detected: {destination.name}")
        seen_hashes.add(metadata["sha256"])
        record = {
            "label": target["label"],
            "document_type": target["document_type"],
            "fiscal_year": target["year"],
            "published_date": target["published_date"],
            "announcement_id": target["art_code"],
            "announcement_columns": target["columns"],
            "source": "东方财富公告镜像（上市公司法定披露PDF）",
            "source_url": final_url,
            "relative_path": str(destination.relative_to(ROOT)),
            **metadata,
        }
        records.append(record)
        print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

    manifest = {
        "company": SHORT_NAME,
        "full_company_name": FULL_NAME,
        "stock_code": STOCK_CODE,
        "checked_as_of": CHECKED_AS_OF,
        "announcement_api_market_parameter": ann_type,
        "annual_report_years": list(range(2020, 2026)),
        "latest_quarterly_report": records[-1]["label"],
        "latest_half_year_report_not_included_as_quarterly": half_year,
        "document_count": len(records),
        "total_pages": sum(int(row["pages"]) for row in records),
        "documents": records,
    }
    (VERIFY_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "label", "document_type", "fiscal_year", "published_date", "announcement_id",
        "relative_path", "source", "source_url", "pages", "bytes", "sha256",
        "qpdf_return_code", "render_verified_first_and_last_page",
        "issuer_identity_verified_when_text_extractable", "sample_text_extractable",
    ]
    with (VERIFY_DIR / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    (VERIFY_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{row['sha256']}  {row['relative_path']}" for row in records) + "\n",
        encoding="utf-8",
    )

    readme = [
        f"{FULL_NAME}（{STOCK_CODE}）定期报告压缩包",
        "",
        f"核对日期：{CHECKED_AS_OF}",
        "",
        "收录范围：",
        "- 2020—2025年度报告全文，共6份；如存在修订版/更正版，优先采用后续版本。",
        f"- 最新法定季报：{records[-1]['label']}。",
    ]
    if half_year:
        readme.append(
            f"- 公司另于{half_year['published_date']}披露《{half_year['title']}》，该文件属于半年报，不作为季报混入本包。"
        )
    readme.extend(
        [
            "",
            "校验：",
            "- 每份PDF均检查文件头、页数、发行人名称或证券代码、报告年份及PDF结构；",
            "- 每份PDF的首页和末页均完成渲染检查；",
            "- ZIP已执行完整性测试。",
            "",
            "文件清单：",
        ]
    )
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
        if bad:
            raise RuntimeError(f"ZIP integrity failure at {bad}")
    print("FINAL_ZIP", ZIP_PATH, ZIP_PATH.stat().st_size, flush=True)
    print("DOCUMENT_COUNT", len(records), flush=True)
    print("TOTAL_PAGES", sum(int(row["pages"]) for row in records), flush=True)


if __name__ == "__main__":
    main()
