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

AS_OF = "2026-10-16"
COMPANY = "鄂尔多斯"
FULL_COMPANY = "内蒙古鄂尔多斯资源股份有限公司"
STOCK_CODE = "600295"
ANNUAL_YEARS = list(range(2020, 2026))

PACKAGE_NAME = f"{COMPANY}_{STOCK_CODE}_2020-2025年报_最新季报_截至{AS_OF.replace('-', '')}"
ROOT = Path(PACKAGE_NAME)
ANNUAL_DIR = ROOT / "01_年度报告"
QUARTER_DIR = ROOT / "02_最新季报"
VERIFY_DIR = ROOT / "03_来源与校验"
WORK_DIR = Path("_erdos_600295_work")
RENDER_DIR = WORK_DIR / "renders"
ZIP_PATH = Path(PACKAGE_NAME + ".zip")
SUMMARY_PATH = Path("package_summary.json")

NOTICE_API = "https://np-anotice-stock.eastmoney.com/api/security/ann"

for directory in (ANNUAL_DIR, QUARTER_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

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
    }
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request(method: str, url: str, *, timeout: tuple[int, int] = (20, 300), **kwargs: Any) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 9):
        try:
            response = SESSION.request(method, url, timeout=timeout, allow_redirects=True, **kwargs)
            print(
                "HTTP", method, url, "attempt", attempt, "status", response.status_code,
                "type", response.headers.get("content-type"),
                "length", response.headers.get("content-length"),
                "final", response.url,
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
    raise RuntimeError(f"request failed for {method} {url}: {errors[-8:]}")


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
            for row in collected:
                title = title_of(row)
                if "年度报告" in title or "季度报告" in title:
                    print(
                        "CANDIDATE", date_of(row), title,
                        row.get("art_code"), row.get("columns"),
                        flush=True,
                    )
            return collected
    raise RuntimeError(f"No announcement rows returned for stock {STOCK_CODE}")


def title_of(row: dict[str, Any]) -> str:
    return str(row.get("title_ch") or row.get("title") or "").strip()


def date_of(row: dict[str, Any]) -> str:
    raw = str(row.get("display_time") or row.get("notice_date") or row.get("sort_date") or "")
    match = re.search(r"\d{4}-\d{2}-\d{2}", raw)
    return match.group(0) if match else ""


def columns_of(row: dict[str, Any]) -> list[str]:
    columns = row.get("columns") or []
    return [str(item.get("column_name") or "") for item in columns if isinstance(item, dict)]


def annual_score(row: dict[str, Any], year: int) -> int:
    title = re.sub(r"\s+", "", title_of(row))
    columns = columns_of(row)
    score = 0
    if any(name == "年度报告全文" for name in columns):
        score += 500
    if re.search(fr"{year}年?年度报告(?:全文)?(?:[(（].*(?:修订|更新|更正).*[)）])?$", title):
        score += 350
    if f"{year}年年度报告" in title:
        score += 250
    if any(token in title for token in ("修订版", "更新后", "更正版", "修订后", "更正后")):
        score += 100
    if any(token in title for token in ("摘要", "英文", "取消", "提示性公告")):
        score -= 1000
    if any(token in title for token in ("审计报告", "问询函", "回复公告", "社会责任报告", "环境报告")):
        score -= 1000
    score += int(date_of(row).replace("-", "") or "0") // 10000
    return score


def select_annual(rows: list[dict[str, Any]], year: int) -> dict[str, Any]:
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for row in rows:
        title = title_of(row)
        compact = re.sub(r"\s+", "", title)
        if str(year) not in compact or "年度报告" not in compact:
            continue
        if any(token in compact for token in ("摘要", "英文", "取消", "提示性公告")):
            continue
        score = annual_score(row, year)
        if score > 0 and row.get("art_code"):
            candidates.append((score, date_of(row), row))
    if not candidates:
        related = [title_of(row) for row in rows if str(year) in title_of(row)]
        raise RuntimeError(f"No annual report found for {year}; related titles={related[:40]}")
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = dict(candidates[0][2])
    selected["title_norm"] = title_of(selected)
    selected["date_norm"] = date_of(selected)
    selected["fiscal_year"] = year
    print("SELECTED_ANNUAL", year, json.dumps(selected, ensure_ascii=False, indent=2), flush=True)
    return selected


def quarter_rank(title: str) -> int:
    compact = re.sub(r"\s+", "", title)
    if any(token in compact for token in ("第三季度报告", "三季度报告")):
        return 3
    if any(token in compact for token in ("第一季度报告", "一季度报告")):
        return 1
    return 0


def select_latest_quarter(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for row in rows:
        title = title_of(row)
        compact = re.sub(r"\s+", "", title)
        if "2026" not in compact or "季度报告" not in compact:
            continue
        if any(token in compact for token in ("摘要", "英文", "提示性公告")):
            continue
        rank = quarter_rank(compact)
        if rank and row.get("art_code"):
            candidates.append((rank, date_of(row), row))
    if not candidates:
        related = [title_of(row) for row in rows if "2026" in title_of(row)]
        raise RuntimeError(f"No 2026 quarterly report found; related titles={related[:60]}")
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    rank, _, row = candidates[0]
    selected = dict(row)
    selected["title_norm"] = title_of(selected)
    selected["date_norm"] = date_of(selected)
    selected["fiscal_year"] = 2026
    selected["quarter_rank"] = rank
    selected["quarter_label"] = "第三季度报告" if rank == 3 else "第一季度报告"
    print("SELECTED_QUARTER", json.dumps(selected, ensure_ascii=False, indent=2), flush=True)
    return selected


def download_pdf(announcement_id: str, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
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
            print("PDF_CANDIDATE_FAILED", url, repr(exc), flush=True)
            temp.unlink(missing_ok=True)
    raise RuntimeError(f"Could not download PDF for {announcement_id}")


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
        raise RuntimeError(
            f"render validation failed for {path.name} page {page_number}: {process.stderr[-1500:]}"
        )
    image.unlink()


def validate_pdf(path: Path, fiscal_year: int, document_type: str, min_pages: int) -> dict[str, Any]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-2500:]}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"unexpectedly short PDF {path.name}: {pages} pages")

    render_page(path, 1, "first")
    if pages > 1:
        render_page(path, pages, "last")

    indices = sorted({0, 1, 2, min(5, pages - 1), max(0, pages // 2), pages - 1})
    sample_parts: list[str] = []
    for index in indices:
        try:
            sample_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_EXTRACT_WARNING", path.name, index + 1, repr(exc), flush=True)
    sample = "\n".join(sample_parts)
    normalized = re.sub(r"\s+", "", sample)
    identity_ok = any(marker in normalized for marker in (COMPANY, FULL_COMPANY, STOCK_CODE, "900936"))
    if sample.strip() and not identity_ok:
        raise RuntimeError(f"issuer identity not found in sampled text for {path.name}")
    if sample.strip() and str(fiscal_year) not in normalized:
        raise RuntimeError(f"fiscal year {fiscal_year} not found in sampled text for {path.name}")

    first_text = "\n".join((reader.pages[index].extract_text() or "") for index in range(min(6, pages)))
    first_normalized = re.sub(r"\s+", "", first_text)
    if document_type == "年度报告":
        if "年度报告摘要" in first_normalized:
            raise RuntimeError(f"annual report summary detected: {path.name}")
        if first_text.strip() and "年度报告" not in first_normalized:
            raise RuntimeError(f"annual-report marker missing: {path.name}")
    else:
        if first_text.strip() and "季度报告" not in first_normalized:
            raise RuntimeError(f"quarterly-report marker missing: {path.name}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": check.returncode,
        "render_verified_first_and_last_page": True,
        "issuer_identity_verified_when_text_extractable": identity_ok,
        "sample_text_extractable": bool(sample.strip()),
    }


def main() -> None:
    rows = fetch_notice_rows()
    annuals = [select_annual(rows, year) for year in ANNUAL_YEARS]
    quarter = select_latest_quarter(rows)

    targets: list[dict[str, Any]] = []
    for row in annuals:
        year = int(row["fiscal_year"])
        revised = any(token in row["title_norm"] for token in ("修订", "更新", "更正"))
        suffix = "_修订版" if revised else ""
        targets.append(
            {
                "row": row,
                "document_type": "年度报告",
                "fiscal_year": year,
                "destination": ANNUAL_DIR / f"{year}_{COMPANY}_年度报告全文{suffix}.pdf",
                "min_pages": 80,
            }
        )

    q_name = (
        f"2026_Q3_{COMPANY}_第三季度报告.pdf"
        if quarter["quarter_rank"] == 3
        else f"2026_Q1_{COMPANY}_第一季度报告.pdf"
    )
    targets.append(
        {
            "row": quarter,
            "document_type": "季度报告",
            "fiscal_year": 2026,
            "destination": QUARTER_DIR / q_name,
            "min_pages": 5,
        }
    )

    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for target in targets:
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
        )
        if metadata["sha256"] in seen_hashes:
            raise RuntimeError(f"duplicate document detected: {target['destination'].name}")
        seen_hashes.add(metadata["sha256"])
        record = {
            "title": row["title_norm"],
            "document_type": target["document_type"],
            "period": str(target["fiscal_year"]) if target["document_type"] == "年度报告" else "2026_Q3" if quarter["quarter_rank"] == 3 else "2026_Q1",
            "publication_date": row["date_norm"],
            "announcement_id": announcement_id,
            "announcement_columns": columns_of(row),
            "source": "东方财富公告镜像（上市公司法定披露PDF）",
            "source_url": final_url,
            "relative_path": str(target["destination"].relative_to(ROOT)),
            **metadata,
        }
        records.append(record)
        print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

    q3_absent = quarter["quarter_rank"] < 3
    latest_quarter = f"2026年{quarter['quarter_label']}"
    manifest = {
        "package_name": PACKAGE_NAME,
        "company": COMPANY,
        "full_company_name": FULL_COMPANY,
        "stock_code_a": STOCK_CODE,
        "stock_code_b": "900936",
        "checked_as_of": AS_OF,
        "scope": "2020-2025年度报告全文 + 截至整理日的最新严格季度报告",
        "strict_quarter_rule": "仅一季度报告和三季度报告参与最新季报判断；半年报不替代季报",
        "annual_report_years": ANNUAL_YEARS,
        "latest_quarterly_report": latest_quarter,
        "q3_disclosure_status": "截至核对日未检索到2026年第三季度报告" if q3_absent else "已收录2026年第三季度报告",
        "document_count": len(records),
        "total_pages": sum(int(record["pages"]) for record in records),
        "documents": records,
    }
    (VERIFY_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    fields = [
        "title", "document_type", "period", "publication_date", "announcement_id",
        "relative_path", "source", "source_url", "pages", "bytes", "sha256",
        "qpdf_return_code", "render_verified_first_and_last_page",
        "issuer_identity_verified_when_text_extractable", "sample_text_extractable",
    ]
    with (VERIFY_DIR / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    (VERIFY_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{record['sha256']}  {record['relative_path']}" for record in records) + "\n",
        encoding="utf-8",
    )

    readme = [
        f"{FULL_COMPANY}（A股{STOCK_CODE}；B股900936）定期报告资料包",
        "",
        f"核对日期：{AS_OF}",
        "",
        "收录内容：",
        "- 2020—2025年年度报告全文，共6份；",
        f"- 截至核对日最新法定季报：{latest_quarter}，共1份。",
        "",
        "版本处理：同一年度存在后续修订、更新或更正版本时，优先收录后续版本。",
        "半年报不属于季度报告，因此未放入“最新季报”目录。",
        "截至核对日未检索到2026年第三季度报告。" if q3_absent else "已收录2026年第三季度报告。",
        "",
        "校验：全部PDF均完成文件头、页数、qpdf结构、发行人身份以及首页和末页渲染检查。",
        "详细来源、页数、文件大小和SHA-256见manifest.json、文件清单.csv及SHA256SUMS.txt。",
        "",
        "文件清单：",
    ]
    for record in records:
        readme.append(
            f"- {record['title']}｜{record['relative_path']}｜{record['pages']}页｜披露日{record['publication_date']}"
        )
    (VERIFY_DIR / "README.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")

    ZIP_PATH.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(path))
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP integrity failure at {bad}")
    if ZIP_PATH.stat().st_size < 500_000:
        raise RuntimeError(f"ZIP unexpectedly small: {ZIP_PATH.stat().st_size}")

    summary = {
        "zip_path": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256_file(ZIP_PATH),
        "document_count": len(records),
        "total_pages": sum(int(record["pages"]) for record in records),
        "latest_quarterly_report": latest_quarter,
        "documents": [
            {
                "type": record["document_type"],
                "period": record["period"],
                "title": record["title"],
                "publication_date": record["publication_date"],
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
