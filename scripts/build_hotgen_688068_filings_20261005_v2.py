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

CHECKED_AS_OF = "2026-10-05"
ISSUER = "北京热景生物技术股份有限公司"
SHORT_NAME = "热景生物"
STOCK_CODE = "688068"
PACKAGE = f"热景生物_{STOCK_CODE}_2020-2025年报及最新季报_截至{CHECKED_AS_OF}"
ROOT = Path(PACKAGE)
ANNUAL_DIR = ROOT / "01_年度报告"
QUARTER_DIR = ROOT / "02_最新季报"
VERIFY_DIR = ROOT / "03_来源与校验"
WORK_DIR = Path("_hotgen_688068_filings_v2_work")
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
    "Referer": "https://data.eastmoney.com/notices/stock/688068.html",
})
NOTICE_API = "https://np-anotice-stock.eastmoney.com/api/security/ann"


def compact(value: Any) -> str:
    return re.sub(r"[\s　]", "", str(value or ""))


def request(method: str, url: str, *, timeout: tuple[int, int] = (20, 180), **kwargs: Any) -> requests.Response:
    errors: list[str] = []
    extra_headers = kwargs.pop("headers", {})
    headers = {**SESSION.headers, **extra_headers}
    for attempt in range(1, 8):
        response = None
        try:
            response = SESSION.request(method, url, headers=headers, timeout=timeout, allow_redirects=True, **kwargs)
            print(
                "HTTP", method, url, "attempt", attempt,
                "status", response.status_code,
                "type", response.headers.get("content-type"),
                "length", response.headers.get("content-length"),
                "final", response.url,
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            if response is not None:
                response.close()
            time.sleep(min(2 * attempt, 12))
    raise RuntimeError(f"request failed for {method} {url}: {errors[-7:]}")


def notice_rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("list", "announcements", "items", "data"):
                if isinstance(data.get(key), list):
                    candidates = data[key]
                    break
        elif isinstance(data, list):
            candidates = data
        if not candidates:
            for key in ("list", "announcements", "items", "result"):
                if isinstance(payload.get(key), list):
                    candidates = payload[key]
                    break
    elif isinstance(payload, list):
        candidates = payload
    return [item for item in candidates if isinstance(item, dict)]


def fetch_notice_rows() -> list[dict[str, Any]]:
    all_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    successful_variant = False
    for ann_type in ("SHA", "A", ""):
        variant_rows: list[dict[str, Any]] = []
        for page_index in range(1, 31):
            params = {
                "sr": "-1",
                "page_size": "100",
                "page_index": str(page_index),
                "ann_type": ann_type,
                "client_source": "web",
                "stock_list": STOCK_CODE,
                "f_node": "0",
                "s_node": "0",
                "begin_time": "2021-01-01",
                "end_time": CHECKED_AS_OF,
            }
            response = request("GET", NOTICE_API, params=params)
            try:
                payload = response.json()
            finally:
                response.close()
            rows = notice_rows_from_payload(payload)
            if page_index == 1:
                print("NOTICE_PAYLOAD_PREFIX", json.dumps(payload, ensure_ascii=False)[:5000], flush=True)
            print("NOTICE_PAGE", ann_type, page_index, "rows", len(rows), flush=True)
            if not rows:
                break
            oldest_year = 9999
            for row in rows:
                art_code = str(row.get("art_code") or row.get("artCode") or row.get("announcementId") or "")
                title = str(row.get("title_ch") or row.get("title") or row.get("announcementTitle") or "").strip()
                date_text = str(row.get("display_time") or row.get("notice_date") or row.get("eiTime") or row.get("date") or "")
                if not art_code or not title:
                    continue
                key = art_code
                if key in seen:
                    continue
                seen.add(key)
                normalized = dict(row)
                normalized["art_code_norm"] = art_code.upper()
                normalized["title_norm"] = title
                normalized["date_norm"] = date_text[:10]
                variant_rows.append(normalized)
                match = re.match(r"(20\d{2})", date_text)
                if match:
                    oldest_year = min(oldest_year, int(match.group(1)))
            if oldest_year <= 2020:
                break
            if len(rows) < 100:
                break
        if variant_rows:
            all_rows.extend(variant_rows)
            successful_variant = True
            break
    if not successful_variant:
        raise RuntimeError("Eastmoney notice API returned no announcements for 688068")
    print("NOTICE_ROWS_COUNT", len(all_rows), flush=True)
    for row in all_rows:
        print("NOTICE_ROW", row["date_norm"], row["art_code_norm"], row["title_norm"], flush=True)
    return all_rows


def annual_score(row: dict[str, Any], year: int) -> tuple[int, str]:
    title = compact(row.get("title_norm"))
    score = 0
    if f"{year}年年度报告" in title or f"{year}年度报告" in title:
        score += 500
    if title.endswith("年度报告") or "年度报告（" in title or "年度报告(" in title:
        score += 100
    if "修订版" in title or "修订稿" in title or "修订" in title:
        score += 90
    if "更新后" in title or "更新版" in title:
        score += 80
    if "更正版" in title or "更正后" in title:
        score += 70
    if "摘要" in title:
        score -= 1000
    if any(token in title for token in ("英文版", "取消", "问询", "审核", "审计报告", "财务报表", "关于修订")):
        score -= 500
    return score, str(row.get("date_norm") or "")


def select_annuals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for year in range(2020, 2026):
        candidates = [row for row in rows if str(year) in compact(row.get("title_norm"))]
        candidates.sort(key=lambda row: annual_score(row, year), reverse=True)
        if not candidates or annual_score(candidates[0], year)[0] < 500:
            raise RuntimeError(f"No full annual report found for {year}; candidates={candidates}")
        chosen = dict(candidates[0])
        chosen["fiscal_year"] = year
        selected.append(chosen)
        print("SELECTED_ANNUAL", year, json.dumps(chosen, ensure_ascii=False, indent=2), flush=True)
    return selected


def quarter_rank(title: str) -> int:
    value = compact(title)
    if "第三季度报告" in value or "三季度报告" in value:
        return 3
    if "第一季度报告" in value or "一季度报告" in value:
        return 1
    return 0


def select_latest_quarter(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if not str(row.get("date_norm", "")).startswith("2026-"):
            continue
        title = compact(row.get("title_norm"))
        rank = quarter_rank(title)
        if rank == 0 or any(token in title for token in ("摘要", "取消", "更正公告", "修订说明")):
            continue
        item = dict(row)
        item["quarter_rank"] = rank
        candidates.append(item)
    if not candidates:
        raise RuntimeError("No 2026 quarterly report found in notice rows")
    candidates.sort(key=lambda row: (int(row["quarter_rank"]), str(row.get("date_norm") or "")), reverse=True)
    chosen = candidates[0]
    chosen["quarter_label"] = "第三季度报告" if chosen["quarter_rank"] == 3 else "第一季度报告"
    print("SELECTED_QUARTER", json.dumps(chosen, ensure_ascii=False, indent=2), flush=True)
    return chosen


def flatten_strings(value: Any):
    if isinstance(value, dict):
        for child in value.values():
            yield from flatten_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from flatten_strings(child)
    elif isinstance(value, str):
        yield value


def pdf_candidates(row: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for value in flatten_strings(row):
        if value.lower().startswith(("http://", "https://")) and ".pdf" in value.lower():
            urls.append(value.replace("\\/", "/"))
    art_code = str(row["art_code_norm"])
    for prefix in ("H2", "H3", "H1"):
        urls.append(f"https://pdf.dfcfw.com/pdf/{prefix}_{art_code}_1.pdf")
        urls.append(f"https://pdf.dfcfw.com/pdf/{prefix}_{art_code}_1.pdf?{int(time.time())}.pdf")
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_pdf(row: dict[str, Any], destination: Path, min_bytes: int) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for url in pdf_candidates(row):
        for attempt in range(1, 4):
            temp = destination.with_suffix(destination.suffix + ".part")
            temp.unlink(missing_ok=True)
            response = None
            try:
                response = request(
                    "GET",
                    url,
                    timeout=(25, 900),
                    stream=True,
                    headers={
                        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
                        "Referer": "https://data.eastmoney.com/",
                    },
                )
                with temp.open("wb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            handle.write(chunk)
                final_url = str(response.url)
                response.close()
                response = None
                size = temp.stat().st_size
                head = temp.read_bytes()[:8]
                if size < min_bytes or not head.startswith(b"%PDF-"):
                    raise RuntimeError(f"invalid PDF: bytes={size}, head={head!r}")
                temp.replace(destination)
                print("DOWNLOADED", destination, size, final_url, flush=True)
                return final_url
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{url} attempt {attempt}: {exc!r}")
                if response is not None:
                    response.close()
                temp.unlink(missing_ok=True)
                time.sleep(min(2 * attempt, 8))
    raise RuntimeError(f"download failed for {destination.name}: {errors[-12:]}")


def render_page(path: Path, page_number: int, tag: str) -> None:
    prefix = RENDER_DIR / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{tag}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
            "-r", "96", "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    image = Path(str(prefix) + ".png")
    valid = process.returncode == 0 and image.exists() and image.stat().st_size > 1500 and image.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    if not valid:
        raise RuntimeError(f"render validation failed for {path.name} page {page_number}: {process.stderr[-2000:]}")
    image.unlink()


def validate_pdf(path: Path, *, year: int, document_type: str, min_pages: int) -> dict[str, Any]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=600)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-3000:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"unexpectedly short PDF {path.name}: pages={pages}, expected>={min_pages}")
    render_page(path, 1, "first")
    if pages > 1:
        render_page(path, pages, "last")
    indices = sorted({0, 1, 2, min(5, pages - 1), pages // 2, pages - 1})
    sample_parts: list[str] = []
    for index in indices:
        try:
            sample_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_EXTRACT_WARNING", path.name, index + 1, repr(exc), flush=True)
    sample = "\n".join(sample_parts)
    normalized = re.sub(r"\s+", "", sample)
    identity_ok = any(marker in normalized for marker in (SHORT_NAME, ISSUER, STOCK_CODE))
    if sample.strip() and not identity_ok:
        raise RuntimeError(f"issuer identity not found in sampled text for {path.name}")
    if sample.strip() and str(year) not in normalized:
        raise RuntimeError(f"year {year} not found in sampled text for {path.name}")
    first_text = "\n".join((reader.pages[i].extract_text() or "") for i in range(min(8, pages)))
    first_normalized = re.sub(r"\s+", "", first_text)
    if document_type == "年度报告":
        if "年度报告摘要" in first_normalized:
            raise RuntimeError(f"annual report summary detected: {path.name}")
        if first_text.strip() and "年度报告" not in first_normalized:
            raise RuntimeError(f"annual report marker missing: {path.name}")
    else:
        if first_text.strip() and not any(token in first_normalized for token in ("第一季度报告", "一季度报告", "第三季度报告", "三季度报告")):
            raise RuntimeError(f"quarterly report marker missing: {path.name}")
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
    annuals = select_annuals(rows)
    latest_quarter = select_latest_quarter(rows)
    documents: list[dict[str, Any]] = []
    for row in annuals:
        year = int(row["fiscal_year"])
        title = str(row["title_norm"])
        revision = "_修订版" if "修订" in compact(title) else ""
        documents.append({
            "row": row,
            "label": title,
            "document_type": "年度报告",
            "fiscal_year": year,
            "published_date": row["date_norm"],
            "announcement_id": row["art_code_norm"],
            "destination": ANNUAL_DIR / f"{year}_热景生物_年度报告全文{revision}.pdf",
            "min_pages": 60,
            "min_bytes": 100_000,
        })
    documents.append({
        "row": latest_quarter,
        "label": latest_quarter["title_norm"],
        "document_type": "季度报告",
        "fiscal_year": 2026,
        "published_date": latest_quarter["date_norm"],
        "announcement_id": latest_quarter["art_code_norm"],
        "destination": QUARTER_DIR / f"2026_热景生物_{latest_quarter['quarter_label']}.pdf",
        "min_pages": 5,
        "min_bytes": 10_000,
    })

    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for document in documents:
        final_url = download_pdf(document["row"], document["destination"], int(document["min_bytes"]))
        metadata = validate_pdf(
            document["destination"],
            year=int(document["fiscal_year"]),
            document_type=document["document_type"],
            min_pages=int(document["min_pages"]),
        )
        if metadata["sha256"] in seen_hashes:
            raise RuntimeError(f"duplicate PDF detected: {document['destination'].name}")
        seen_hashes.add(metadata["sha256"])
        record = {
            "label": document["label"],
            "document_type": document["document_type"],
            "fiscal_year": document["fiscal_year"],
            "published_date": document["published_date"],
            "announcement_id": document["announcement_id"],
            "source": "东方财富公告镜像（上市公司法定披露PDF）",
            "source_url": final_url,
            "relative_path": str(document["destination"].relative_to(ROOT)),
            **metadata,
        }
        records.append(record)
        print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

    manifest = {
        "issuer": ISSUER,
        "short_name": SHORT_NAME,
        "stock_code": STOCK_CODE,
        "checked_as_of": CHECKED_AS_OF,
        "annual_report_years": list(range(2020, 2026)),
        "latest_quarterly_report": latest_quarter["quarter_label"],
        "document_count": len(records),
        "documents": records,
    }
    (VERIFY_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    fieldnames = [
        "label", "document_type", "fiscal_year", "published_date", "announcement_id",
        "source", "source_url", "relative_path", "pages", "bytes", "sha256",
        "qpdf_return_code", "render_verified_first_and_last_page",
        "issuer_identity_verified_when_text_extractable", "sample_text_extractable",
    ]
    with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    (VERIFY_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{row['sha256']}  {row['relative_path']}" for row in records) + "\n",
        encoding="utf-8",
    )
    readme = [
        f"{ISSUER}（{STOCK_CODE}）定期报告资料包",
        "",
        f"核对日期：{CHECKED_AS_OF}",
        "",
        "收录范围：",
        "- 2020—2025年度报告全文，共6份；后续存在修订版时优先采用修订版。",
        f"- 截至核对日最新法定季度报告：2026年{latest_quarter['quarter_label']}，共1份。",
        "- 半年度报告不属于季度报告，因此未混入本包。",
        "",
        "来源说明：PDF来自东方财富公开公告镜像，其对应上市公司法定披露文件。",
        "巨潮资讯检索接口在本次构建时持续返回服务器错误，因此未使用其检索接口；",
        "文件内容通过公司名称、证券代码、报告年份、页数、PDF结构和首末页渲染复核。",
        "",
        "详细来源、页数、文件大小及SHA-256见文件清单.csv、manifest.json和SHA256SUMS.txt。",
        "",
        "文件清单：",
    ]
    for row in records:
        readme.append(f"- {row['label']}｜{row['relative_path']}｜{row['pages']}页｜披露日{row['published_date']}")
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
        if bad is not None:
            raise RuntimeError(f"ZIP integrity failure at {bad}")
    print("FINAL_ZIP", ZIP_PATH, ZIP_PATH.stat().st_size, flush=True)
    print("DOCUMENT_COUNT", len(records), flush=True)
    print("TOTAL_PAGES", sum(int(row["pages"]) for row in records), flush=True)


if __name__ == "__main__":
    main()
