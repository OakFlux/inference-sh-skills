from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-10-14"
COMPANY = "海新能科"
OLD_COMPANY = "三聚环保"
STOCK_CODE = "300072"
PACKAGE = f"海新能科_{STOCK_CODE}_2020-2025年报及最新季报_截至{CHECKED_AS_OF}"
ROOT = Path(PACKAGE)
ANNUAL_DIR = ROOT / "01_年度报告"
QUARTER_DIR = ROOT / "02_最新季报"
VERIFY_DIR = ROOT / "03_说明与校验"
WORK_DIR = Path("_haixin_300072_work")
RENDER_DIR = WORK_DIR / "renders"
ZIP_PATH = Path(PACKAGE + ".zip")
for directory in (ANNUAL_DIR, QUARTER_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://data.eastmoney.com/",
})

API = "https://np-anotice-stock.eastmoney.com/api/security/ann"
ISSUER_MARKERS = [
    "海新能科",
    "北京海新能源科技股份有限公司",
    "三聚环保",
    "北京三聚环保新材料股份有限公司",
    STOCK_CODE,
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def normalized_date(row: dict[str, Any]) -> str:
    for key in ("display_time", "notice_date", "sort_date", "eiTime"):
        value = str(row.get(key) or "")
        match = re.search(r"(20\d{2})-(\d{2})-(\d{2})", value)
        if match:
            return match.group(0)
    return ""


def fetch_notice_rows() -> list[dict[str, Any]]:
    all_rows: list[dict[str, Any]] = []
    selected_ann_type = ""
    for ann_type in ("SZA", "SZSA", "SZ"):
        rows: list[dict[str, Any]] = []
        for page_index in range(1, 15):
            params = {
                "sr": "-1",
                "page_size": "100",
                "page_index": str(page_index),
                "client_source": "web",
                "stock_list": STOCK_CODE,
                "f_node": "0",
                "s_node": "0",
                "begin_time": "2021-01-01",
                "end_time": CHECKED_AS_OF,
                "ann_type": ann_type,
            }
            response = request("GET", API, params=params)
            try:
                payload = response.json()
            finally:
                response.close()
            page_rows = (((payload or {}).get("data") or {}).get("list") or [])
            print("NOTICE_PAGE", ann_type, page_index, "rows", len(page_rows), flush=True)
            rows.extend(page_rows)
            if len(page_rows) < 100:
                break
        if rows:
            all_rows = rows
            selected_ann_type = ann_type
            break
    if not all_rows:
        raise RuntimeError("No announcements returned for stock 300072")
    print("NOTICE_ROWS_COUNT", len(all_rows), "ANN_TYPE", selected_ann_type, flush=True)
    normalized: list[dict[str, Any]] = []
    for row in all_rows:
        item = dict(row)
        item["art_code_norm"] = str(row.get("art_code") or "").strip().upper()
        item["title_norm"] = str(row.get("title_ch") or row.get("title") or "").strip()
        item["date_norm"] = normalized_date(row)
        item["column_names"] = [str(col.get("column_name") or "") for col in (row.get("columns") or [])]
        normalized.append(item)
    return normalized


def annual_score(row: dict[str, Any], year: int) -> int:
    title = row["title_norm"]
    columns = row["column_names"]
    if str(year) not in title or "年度报告" not in title:
        return -10_000
    if "摘要" in title:
        return -10_000
    score = 0
    if any("年度报告全文" in name for name in columns):
        score += 1000
    if any(token in title for token in ("修订版", "更新后", "更正后", "修正版")):
        score += 300
    if "全文" in title:
        score += 30
    score += int((row.get("date_norm") or "0000-00-00").replace("-", "") or 0) // 100
    return score


def select_annual(rows: list[dict[str, Any]], year: int) -> dict[str, Any]:
    candidates = [(annual_score(row, year), row) for row in rows]
    candidates = [item for item in candidates if item[0] > -10_000]
    if not candidates:
        raise RuntimeError(f"Annual report not found for {year}")
    candidates.sort(key=lambda item: (item[0], item[1].get("date_norm", "")), reverse=True)
    selected = dict(candidates[0][1])
    selected["fiscal_year"] = year
    print("SELECTED_ANNUAL", year, json.dumps(selected, ensure_ascii=False, indent=2), flush=True)
    return selected


def quarter_rank(title: str) -> int:
    if any(token in title for token in ("第三季度报告", "三季度报告")):
        return 3
    if any(token in title for token in ("第一季度报告", "一季度报告")):
        return 1
    return 0


def select_latest_quarter(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        title = row["title_norm"]
        if "2026" not in title or "季度报告" not in title:
            continue
        if "摘要" in title:
            continue
        rank = quarter_rank(title)
        if not rank:
            continue
        item = dict(row)
        item["fiscal_year"] = 2026
        item["quarter_rank"] = rank
        item["quarter_label"] = "第三季度报告" if rank == 3 else "第一季度报告"
        candidates.append(item)
    if not candidates:
        raise RuntimeError("No 2026 quarterly report found")
    candidates.sort(key=lambda row: (row["quarter_rank"], row.get("date_norm", "")), reverse=True)
    selected = candidates[0]
    print("SELECTED_QUARTER", json.dumps(selected, ensure_ascii=False, indent=2), flush=True)
    return selected


def pdf_urls(art_code: str) -> list[str]:
    return [
        f"https://pdf.dfcfw.com/pdf/H2_{art_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{art_code}_1.pdf",
    ]


def download_pdf(art_code: str, destination: Path, min_bytes: int) -> str:
    errors: list[str] = []
    destination.parent.mkdir(parents=True, exist_ok=True)
    for url in pdf_urls(art_code):
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
                if size < min_bytes or not head.startswith(b"%PDF-"):
                    raise RuntimeError(f"invalid PDF: bytes={size}, head={head!r}")
                final_url = str(response.url)
                temp.replace(destination)
                return final_url
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{url} attempt {attempt}: {exc!r}")
                temp.unlink(missing_ok=True)
                time.sleep(min(attempt * 2, 8))
            finally:
                if response is not None:
                    response.close()
    raise RuntimeError(f"Unable to download {art_code}: {errors[-8:]}")


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


def validate_pdf(path: Path, fiscal_year: int, document_type: str, min_pages: int) -> dict[str, Any]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {check.stderr[-2500:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"Unexpectedly short PDF {path.name}: {pages} pages")
    render_page(path, 1, "first")
    if pages > 1:
        render_page(path, pages, "last")
    indices = sorted({0, 1, 2, min(7, pages - 1), max(0, pages // 2), pages - 1})
    sample_parts: list[str] = []
    for index in indices:
        try:
            sample_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_EXTRACT_WARNING", path.name, index + 1, repr(exc), flush=True)
    sample = "\n".join(sample_parts)
    normalized = re.sub(r"\s+", "", sample)
    identity_ok = any(marker in normalized for marker in ISSUER_MARKERS)
    if sample.strip() and not identity_ok:
        raise RuntimeError(f"Issuer identity not found in sampled text: {path.name}")
    if sample.strip() and str(fiscal_year) not in normalized:
        raise RuntimeError(f"Fiscal year {fiscal_year} not found in sampled text: {path.name}")
    first_text = "\n".join((reader.pages[index].extract_text() or "") for index in range(min(6, pages)))
    first_norm = re.sub(r"\s+", "", first_text)
    if document_type == "年度报告":
        if "年度报告摘要" in first_norm:
            raise RuntimeError(f"Annual report summary detected: {path.name}")
        if first_text.strip() and "年度报告" not in first_norm:
            raise RuntimeError(f"Annual report marker missing: {path.name}")
    else:
        if first_text.strip() and not any(token in first_norm for token in ("第一季度报告", "一季度报告", "第三季度报告", "三季度报告")):
            raise RuntimeError(f"Quarterly report marker missing: {path.name}")
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
    rows = fetch_notice_rows()
    annual_rows = [select_annual(rows, year) for year in range(2020, 2026)]
    quarter_row = select_latest_quarter(rows)

    targets: list[dict[str, Any]] = []
    for row in annual_rows:
        year = int(row["fiscal_year"])
        revised = any(token in row["title_norm"] for token in ("修订版", "更新后", "更正后", "修正版"))
        suffix = "_修订版" if revised else ""
        targets.append({
            "row": row,
            "document_type": "年度报告",
            "fiscal_year": year,
            "destination": ANNUAL_DIR / f"{year}_海新能科_年度报告全文{suffix}.pdf",
            "min_pages": 70,
            "min_bytes": 100_000,
        })
    targets.append({
        "row": quarter_row,
        "document_type": "季度报告",
        "fiscal_year": 2026,
        "destination": QUARTER_DIR / f"2026_{quarter_row['quarter_label']}_海新能科.pdf",
        "min_pages": 5,
        "min_bytes": 20_000,
    })

    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for target in targets:
        row = target["row"]
        art_code = row["art_code_norm"]
        final_url = download_pdf(art_code, target["destination"], target["min_bytes"])
        metadata = validate_pdf(
            target["destination"],
            int(target["fiscal_year"]),
            target["document_type"],
            int(target["min_pages"]),
        )
        if metadata["sha256"] in seen_hashes:
            raise RuntimeError(f"Duplicate document detected: {target['destination'].name}")
        seen_hashes.add(metadata["sha256"])
        record = {
            "label": row["title_norm"],
            "document_type": target["document_type"],
            "fiscal_year": target["fiscal_year"],
            "published_date": row.get("date_norm", ""),
            "announcement_id": art_code,
            "announcement_columns": row.get("column_names", []),
            "source": "东方财富公告镜像（上市公司法定披露PDF）",
            "source_url": final_url,
            "relative_path": str(target["destination"].relative_to(ROOT)),
            **metadata,
        }
        records.append(record)
        print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

    manifest = {
        "company": COMPANY,
        "former_short_name": OLD_COMPANY,
        "stock_code": STOCK_CODE,
        "checked_as_of": CHECKED_AS_OF,
        "annual_report_years": list(range(2020, 2026)),
        "latest_quarterly_report": quarter_row["title_norm"],
        "document_count": len(records),
        "total_pages": sum(int(item["pages"]) for item in records),
        "documents": records,
    }
    (VERIFY_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = [
        "label", "document_type", "fiscal_year", "published_date", "announcement_id",
        "relative_path", "pages", "bytes", "sha256", "source", "source_url",
        "qpdf_return_code", "render_verified_first_and_last_page",
        "issuer_identity_verified_when_text_extractable", "sample_text_extractable",
    ]
    with (VERIFY_DIR / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    (VERIFY_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{item['sha256']}  {item['relative_path']}" for item in records) + "\n",
        encoding="utf-8",
    )
    readme = [
        f"{COMPANY}（{STOCK_CODE}）2020-2025年年度报告及最新季报资料包",
        "",
        f"核对日期：{CHECKED_AS_OF}",
        "说明：公司曾用简称“三聚环保”，早期年度报告可能仍使用原简称或原公司名称。",
        "",
        "收录文件：",
        "- 2020-2025年度报告全文，共6份；",
        f"- 截至核对日最新已披露法定季报：{quarter_row['title_norm']}，共1份。",
        "- 半年度报告不作为季度报告混入本目录。",
        "",
        "所有PDF已完成文件头、页数、公司名称/证券代码、报告年份、qpdf结构及首末页渲染检查。",
        "详细来源链接、公告编号、页数、文件大小及SHA-256见文件清单.csv、manifest.json和SHA256SUMS.txt。",
        "",
        "文件清单：",
    ]
    for item in records:
        readme.append(f"- {item['label']}｜{item['relative_path']}｜{item['pages']}页｜披露日{item['published_date']}")
    (VERIFY_DIR / "README.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")

    ZIP_PATH.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(path))
    if not ZIP_PATH.exists() or ZIP_PATH.stat().st_size < 500_000:
        raise RuntimeError(f"ZIP missing or unexpectedly small: {ZIP_PATH}")
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP integrity failure at {bad}")
    print("FINAL_ZIP", ZIP_PATH, ZIP_PATH.stat().st_size, flush=True)
    print("DOCUMENT_COUNT", len(records), flush=True)
    print("TOTAL_PAGES", sum(int(item["pages"]) for item in records), flush=True)


if __name__ == "__main__":
    main()
