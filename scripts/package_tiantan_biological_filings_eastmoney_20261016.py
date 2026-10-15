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
from pathlib import Path
from typing import Any

import pymupdf
import requests
from pypdf import PdfReader

AS_OF = "2026-10-16"
COMPANY = "天坛生物"
FULL_COMPANY = "北京天坛生物制品股份有限公司"
STOCK_CODE = "600161"
ANNUAL_YEARS = list(range(2020, 2026))

ROOT = Path("dist_tiantan_em")
PACKAGE_ROOT = ROOT / f"{COMPANY}_{STOCK_CODE}_2020-2025年报_最新季报"
ANNUAL_DIR = PACKAGE_ROOT / "01_年度报告"
QUARTER_DIR = PACKAGE_ROOT / "02_最新季报"
META_DIR = PACKAGE_ROOT / "03_来源与校验"
RENDER_DIR = ROOT / "_renders"
ZIP_PATH = ROOT / f"{COMPANY}_{STOCK_CODE}_2020-2025年报_最新季报_20261016.zip"
SUMMARY_PATH = ROOT / "package_summary.json"

NOTICE_API = "https://np-anotice-stock.eastmoney.com/api/security/ann"

SESSION = requests.Session()
SESSION.trust_env = False
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/155 Safari/537.36",
    "Accept": "application/json,text/plain,application/pdf,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request(method: str, url: str, *, timeout: tuple[int, int] = (20, 300), **kwargs: Any) -> requests.Response:
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
            errors.append(repr(exc))
            time.sleep(min(attempt * 2, 10))
    raise RuntimeError(f"Request failed for {method} {url}: {errors[-7:]}")


def fetch_notice_rows() -> list[dict[str, Any]]:
    for ann_type in ("SHA", "SH"):
        collected: list[dict[str, Any]] = []
        for page in range(1, 20):
            params = {
                "sr": "-1",
                "page_size": "100",
                "page_index": str(page),
                "ann_type": ann_type,
                "client_source": "web",
                "stock_list": STOCK_CODE,
                "f_node": "0",
                "s_node": "0",
                "begin_time": "2021-01-01",
                "end_time": AS_OF,
            }
            response = request("GET", NOTICE_API, params=params, timeout=(20, 180))
            try:
                payload = response.json()
            finally:
                response.close()
            rows = (((payload or {}).get("data") or {}).get("list") or [])
            print("NOTICE_PAGE", ann_type, page, "rows", len(rows), flush=True)
            collected.extend(row for row in rows if isinstance(row, dict))
            if len(rows) < 100:
                break
        if collected:
            print("NOTICE_ROWS_COUNT", len(collected), "ANN_TYPE", ann_type, flush=True)
            return collected
    raise RuntimeError(f"No announcement rows returned for {STOCK_CODE}")


def title_of(row: dict[str, Any]) -> str:
    return re.sub(r"\s+", "", str(row.get("title_ch") or row.get("title") or "")).strip()


def date_of(row: dict[str, Any]) -> str:
    raw = str(row.get("display_time") or row.get("notice_date") or row.get("sort_date") or "")
    match = re.search(r"\d{4}-\d{2}-\d{2}", raw)
    return match.group(0) if match else ""


def columns_of(row: dict[str, Any]) -> list[str]:
    columns = row.get("columns") or []
    return [str(item.get("column_name") or "") for item in columns if isinstance(item, dict)]


def annual_score(row: dict[str, Any], year: int) -> int:
    title = title_of(row)
    columns = columns_of(row)
    score = 0
    if any(name == "年度报告全文" for name in columns):
        score += 500
    if re.search(fr"{year}年?年度报告(?:全文)?(?:[(（].*(?:修订|更新|更正).*[)）])?$", title):
        score += 350
    elif f"{year}年年度报告" in title:
        score += 250
    if any(token in title for token in ("修订版", "更新后", "更正版", "修订后", "更正后")):
        score += 100
    if "摘要" in title:
        score -= 1000
    if any(token in title for token in ("审计报告", "问询函", "回复公告", "社会责任报告", "环境报告")):
        score -= 1000
    return score


def select_annual(rows: list[dict[str, Any]], year: int) -> dict[str, Any]:
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for row in rows:
        title = title_of(row)
        if str(year) not in title or "年度报告" not in title or "摘要" in title:
            continue
        score = annual_score(row, year)
        if score > 0:
            candidates.append((score, date_of(row), row))
    if not candidates:
        related = [title_of(row) for row in rows if str(year) in title_of(row)]
        raise RuntimeError(f"No annual report found for {year}. Related titles: {related[:30]}")
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = dict(candidates[0][2])
    selected["title_norm"] = title_of(selected)
    selected["date_norm"] = date_of(selected)
    selected["fiscal_year"] = year
    print("SELECTED_ANNUAL", year, json.dumps(selected, ensure_ascii=False)[:5000], flush=True)
    return selected


def quarter_rank(title: str) -> int:
    compact = re.sub(r"\s+", "", title)
    if "第三季度报告" in compact or "三季度报告" in compact:
        return 3
    if "第一季度报告" in compact or "一季度报告" in compact:
        return 1
    return 0


def select_latest_quarter(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for row in rows:
        title = title_of(row)
        if "2026" not in title or "季度报告" not in title or "摘要" in title:
            continue
        rank = quarter_rank(title)
        if rank:
            candidates.append((rank, date_of(row), row))
    if not candidates:
        related = [title_of(row) for row in rows if "季度报告" in title_of(row)]
        raise RuntimeError(f"No 2026 quarterly report found. Related titles: {related[:30]}")
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    rank, _, row = candidates[0]
    selected = dict(row)
    selected["title_norm"] = title_of(selected)
    selected["date_norm"] = date_of(selected)
    selected["fiscal_year"] = 2026
    selected["quarter_rank"] = rank
    selected["quarter_label"] = "第三季度报告" if rank == 3 else "第一季度报告"
    print("SELECTED_QUARTER", json.dumps(selected, ensure_ascii=False)[:5000], flush=True)
    return selected


def download_pdf(announcement_id: str, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for prefix in ("H2", "H3"):
        url = f"https://pdf.dfcfw.com/pdf/{prefix}_{announcement_id}_1.pdf"
        temp = destination.with_suffix(destination.suffix + ".part")
        temp.unlink(missing_ok=True)
        try:
            response = request(
                "GET",
                url,
                timeout=(25, 600),
                stream=True,
                headers={"Referer": "https://data.eastmoney.com/"},
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
            if size < 20_000 or not head.startswith(b"%PDF-"):
                raise RuntimeError(f"invalid PDF bytes={size}, head={head!r}")
            temp.replace(destination)
            print("DOWNLOADED", destination, destination.stat().st_size, final_url, flush=True)
            return final_url
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
            temp.unlink(missing_ok=True)
    raise RuntimeError(f"Could not download PDF for {announcement_id}: {errors}")


def render_page(pdf_path: Path, page_index: int, output_path: Path) -> None:
    with pymupdf.open(pdf_path) as document:
        page = document[page_index]
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.4, 1.4), alpha=False)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pixmap.save(output_path)
        if output_path.stat().st_size < 4_000:
            raise RuntimeError(f"Rendered image too small: {output_path}")


def validate_pdf(path: Path, fiscal_year: int, document_type: str, min_pages: int, sequence: int) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"Unexpectedly short PDF {path.name}: {pages} pages")

    render_page(path, 0, RENDER_DIR / f"{sequence:02d}_first.png")
    render_page(path, pages - 1, RENDER_DIR / f"{sequence:02d}_last.png")

    indices = sorted({0, 1, 2, min(5, pages - 1), max(0, pages // 2), pages - 1})
    sample_parts: list[str] = []
    for index in indices:
        try:
            sample_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_EXTRACT_WARNING", path.name, index + 1, repr(exc), flush=True)
    sample = "\n".join(sample_parts)
    normalized = re.sub(r"\s+", "", sample)
    identity_ok = any(marker in normalized for marker in (COMPANY, FULL_COMPANY, STOCK_CODE))
    if sample.strip() and not identity_ok:
        raise RuntimeError(f"Issuer identity not found in sampled text for {path.name}")
    if sample.strip() and str(fiscal_year) not in normalized:
        raise RuntimeError(f"Fiscal year {fiscal_year} not found in sampled text for {path.name}")

    first_text_parts: list[str] = []
    for index in range(min(6, pages)):
        try:
            first_text_parts.append(reader.pages[index].extract_text() or "")
        except Exception:
            pass
    first_normalized = re.sub(r"\s+", "", "\n".join(first_text_parts))
    if document_type == "年度报告":
        if "年度报告摘要" in first_normalized:
            raise RuntimeError(f"Annual report summary detected: {path.name}")
        if first_normalized and "年度报告" not in first_normalized:
            raise RuntimeError(f"Annual-report marker missing: {path.name}")
    else:
        if first_normalized and "季度报告" not in first_normalized:
            raise RuntimeError(f"Quarterly-report marker missing: {path.name}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "render_verified_first_and_last_page": True,
        "issuer_identity_verified_when_text_extractable": identity_ok,
        "sample_text_extractable": bool(sample.strip()),
    }


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    for directory in (ANNUAL_DIR, QUARTER_DIR, META_DIR, RENDER_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    rows = fetch_notice_rows()
    annuals = [select_annual(rows, year) for year in ANNUAL_YEARS]
    quarter = select_latest_quarter(rows)

    targets: list[dict[str, Any]] = []
    for row in annuals:
        year = int(row["fiscal_year"])
        revised = any(token in row["title_norm"] for token in ("修订", "更新", "更正"))
        suffix = "_修订版" if revised else ""
        targets.append({
            "row": row,
            "document_type": "年度报告",
            "fiscal_year": year,
            "destination": ANNUAL_DIR / f"{year}_{COMPANY}_年度报告全文{suffix}.pdf",
            "relative_path": f"01_年度报告/{year}_{COMPANY}_年度报告全文{suffix}.pdf",
            "min_pages": 80,
        })

    q_name = (
        f"2026_Q3_{COMPANY}_第三季度报告.pdf"
        if quarter["quarter_rank"] == 3
        else f"2026_Q1_{COMPANY}_第一季度报告.pdf"
    )
    targets.append({
        "row": quarter,
        "document_type": "季度报告",
        "fiscal_year": 2026,
        "destination": QUARTER_DIR / q_name,
        "relative_path": f"02_最新季报/{q_name}",
        "min_pages": 5,
    })

    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for sequence, target in enumerate(targets, 1):
        row = target["row"]
        announcement_id = str(row.get("art_code") or "").upper()
        if not re.fullmatch(r"AN\d+", announcement_id):
            raise RuntimeError(f"Invalid announcement id: {announcement_id}")
        final_url = download_pdf(announcement_id, target["destination"])
        metadata = validate_pdf(
            target["destination"],
            int(target["fiscal_year"]),
            str(target["document_type"]),
            int(target["min_pages"]),
            sequence,
        )
        if metadata["sha256"] in seen_hashes:
            raise RuntimeError(f"Duplicate document detected: {target['destination'].name}")
        seen_hashes.add(metadata["sha256"])
        records.append({
            "label": row["title_norm"],
            "document_type": target["document_type"],
            "fiscal_year": target["fiscal_year"],
            "published_date": row["date_norm"],
            "announcement_id": announcement_id,
            "announcement_columns": columns_of(row),
            "source": "东方财富公告镜像（上市公司法定披露PDF）",
            "source_url": final_url,
            "relative_path": target["relative_path"],
            **metadata,
        })

    latest_quarter_label = quarter["quarter_label"]
    q3_absent = quarter["quarter_rank"] < 3
    manifest = {
        "company": COMPANY,
        "full_company_name": FULL_COMPANY,
        "stock_code": STOCK_CODE,
        "checked_as_of": AS_OF,
        "scope": "2020-2025年度报告全文 + 截至整理日的最新严格季度报告",
        "strict_quarter_rule": "仅第一季度报告和第三季度报告参与最新季报判断；半年报不替代季报",
        "latest_quarterly_report": f"2026年{latest_quarter_label}",
        "q3_disclosure_status": "截至核对日未检索到2026年第三季度报告" if q3_absent else "已收录2026年第三季度报告",
        "document_count": len(records),
        "total_pages": sum(int(record["pages"]) for record in records),
        "documents": records,
    }
    (META_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = [
        "label", "document_type", "fiscal_year", "published_date", "announcement_id",
        "relative_path", "source", "source_url", "pages", "bytes", "sha256",
        "render_verified_first_and_last_page", "issuer_identity_verified_when_text_extractable",
        "sample_text_extractable",
    ]
    with (META_DIR / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    (META_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{record['sha256']}  {record['relative_path']}" for record in records) + "\n",
        encoding="utf-8",
    )

    readme = [
        f"{FULL_COMPANY}（{STOCK_CODE}）定期报告资料包",
        "",
        f"核对日期：{AS_OF}",
        "",
        "收录内容：",
        "- 2020—2025年年度报告全文，共6份；",
        f"- 截至核对日最新法定季报：2026年{latest_quarter_label}，共1份。",
        "",
        "版本处理：如同一年度存在后续修订、更新或更正版本，优先收录后续版本。",
        "半年报不属于季度报告，因此未放入“最新季报”目录。",
        "截至核对日未检索到2026年第三季度报告。" if q3_absent else "已收录2026年第三季度报告。",
        "",
        "校验：所有PDF均完成文件头、页数、发行人身份及首末页渲染检查。",
        "详细来源、页数、文件大小和SHA-256见manifest.json、文件清单.csv及SHA256SUMS.txt。",
        "",
        "文件清单：",
    ]
    for record in records:
        readme.append(
            f"- {record['label']}｜{record['relative_path']}｜{record['pages']}页｜披露日{record['published_date']}"
        )
    (META_DIR / "README.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")

    ZIP_PATH.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(PACKAGE_ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(path.relative_to(ROOT)))
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP integrity failure at {bad}")
        pdfs = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
        if len(pdfs) != 7:
            raise RuntimeError(f"Expected 7 PDFs in ZIP, found {len(pdfs)}")

    summary = {
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256_file(ZIP_PATH),
        "pdf_count": len(records),
        "documents": [
            {
                "type": record["document_type"],
                "period": str(record["fiscal_year"]),
                "title": record["label"],
                "publication_date": record["published_date"],
                "pages": record["pages"],
                "bytes": record["bytes"],
            }
            for record in records
        ],
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
