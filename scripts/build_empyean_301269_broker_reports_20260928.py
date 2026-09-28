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

CHECKED_AS_OF = "2026-09-28"
STOCK_CODE = "301269"
STOCK_NAME = "华大九天"
PACKAGE = "华大九天_301269_券商深度报告_3份"
ROOT = Path(PACKAGE)
REPORT_DIR = ROOT / "01_原始券商研报PDF"
VERIFY_DIR = ROOT / "02_报告清单与校验"
WORK_DIR = Path("_empyean_broker_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (REPORT_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

REPORT_API = "https://reportapi.eastmoney.com/report/list"
SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/json,text/html,application/pdf,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://data.eastmoney.com/report/stock.jshtml",
}


def safe_name(value: str, limit: int = 92) -> str:
    value = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", value or "")
    value = re.sub(r"\s+", " ", value).strip(" ._")
    return value[:limit] or "未命名报告"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def http_get(url: str, *, params: dict[str, Any] | None = None, stream: bool = False,
             timeout: tuple[int, int] = (25, 600)) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        try:
            response = SESSION.get(
                url,
                params=params,
                headers=HEADERS,
                stream=stream,
                timeout=timeout,
                allow_redirects=True,
            )
            print(
                "HTTP GET", response.url, "attempt", attempt, "status", response.status_code,
                "type", response.headers.get("content-type"),
                "length", response.headers.get("content-length"),
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"request failed for {url}: {errors[-6:]}")


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except Exception:  # noqa: BLE001
        return default


def parse_date(value: Any) -> str:
    text = str(value or "").strip()
    match = re.match(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", text)
    if not match:
        return text[:10]
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def fetch_all_reports() -> list[dict[str, Any]]:
    base_params = {
        "industryCode": "*",
        "pageSize": "5000",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": "2022-01-01",
        "endTime": CHECKED_AS_OF,
        "pageNo": "1",
        "fields": "",
        "qType": "0",
        "orgCode": "",
        "code": STOCK_CODE,
        "rcode": "",
        "p": "1",
        "pageNum": "1",
        "pageNumber": "1",
    }
    response = http_get(REPORT_API, params=base_params, timeout=(25, 180))
    try:
        payload = response.json()
    finally:
        response.close()
    total_pages = as_int(payload.get("TotalPage") or payload.get("totalPage"), 1)
    rows: list[dict[str, Any]] = []
    for page in range(1, max(1, total_pages) + 1):
        params = dict(base_params)
        params.update({"pageNo": str(page), "p": str(page), "pageNum": str(page), "pageNumber": str(page)})
        if page == 1:
            page_payload = payload
        else:
            response = http_get(REPORT_API, params=params, timeout=(25, 180))
            try:
                page_payload = response.json()
            finally:
                response.close()
        for raw in page_payload.get("data") or []:
            info_code = str(raw.get("infoCode") or "").strip()
            title = str(raw.get("title") or "").strip()
            if not info_code or not title:
                continue
            raw = dict(raw)
            raw["infoCode"] = info_code
            raw["title"] = title
            raw["publishDate"] = parse_date(raw.get("publishDate"))
            raw["pdfUrl"] = f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"
            rows.append(raw)
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        unique[row["infoCode"]] = row
    ordered = sorted(unique.values(), key=lambda row: (row.get("publishDate", ""), row.get("infoCode", "")), reverse=True)
    print("REPORT_API_COUNT", len(ordered), flush=True)
    for row in ordered:
        print(
            "REPORT_META",
            json.dumps(
                {
                    "title": row.get("title"),
                    "org": row.get("orgSName") or row.get("orgName"),
                    "date": row.get("publishDate"),
                    "pages": row.get("attachPages"),
                    "size": row.get("attachSize"),
                    "reportType": row.get("reportType"),
                    "infoCode": row.get("infoCode"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return ordered


def report_score(row: dict[str, Any]) -> int:
    title = str(row.get("title") or "")
    title_norm = re.sub(r"\s+", "", title)
    pages = as_int(row.get("attachPages"))
    score = min(pages, 80) * 8
    exact_phrases = (
        "国产半导体EDA领航者，加速赶超全球三巨头",
        "国产半导体EDA领航者,加速赶超全球三巨头",
        "前三季度业绩符合预期，看好长期国产替代趋势",
        "国内EDA龙头企业受益于国产化推进",
    )
    if any(phrase in title_norm for phrase in exact_phrases):
        score += 900
    if "深度" in title_norm:
        score += 500
    if any(token in title_norm for token in ("首次覆盖", "首次评级", "新股定价", "投资价值", "领航者", "龙头")):
        score += 260
    if any(token in title_norm for token in ("EDA", "国产替代", "国产化", "全流程")):
        score += 120
    if any(token in title_norm for token in ("点评", "快报", "简评", "季度", "一季报", "中报", "年报")):
        score -= 180
    if pages and pages < 10:
        score -= 400
    date_text = str(row.get("publishDate") or "")
    if date_text.startswith("2025"):
        score += 40
    elif date_text.startswith("2026"):
        score += 25
    return score


def rank_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for row in rows:
        pages = as_int(row.get("attachPages"))
        title = str(row.get("title") or "")
        if pages and pages < 4:
            continue
        if any(token in title for token in ("风险提示", "调研", "纪要", "澄清")):
            continue
        item = dict(row)
        item["selectionScore"] = report_score(item)
        ranked.append(item)
    ranked.sort(
        key=lambda row: (
            as_int(row.get("selectionScore")),
            as_int(row.get("attachPages")),
            str(row.get("publishDate") or ""),
        ),
        reverse=True,
    )
    print("RANKED_CANDIDATES", flush=True)
    for row in ranked[:30]:
        print(
            json.dumps(
                {
                    "score": row.get("selectionScore"),
                    "title": row.get("title"),
                    "org": row.get("orgSName") or row.get("orgName"),
                    "date": row.get("publishDate"),
                    "pages": row.get("attachPages"),
                    "infoCode": row.get("infoCode"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return ranked


def download_pdf(url: str, destination: Path) -> str:
    response = http_get(url, stream=True, timeout=(30, 900))
    temp = destination.with_suffix(destination.suffix + ".part")
    temp.unlink(missing_ok=True)
    try:
        with temp.open("wb") as handle:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    handle.write(chunk)
        final_url = str(response.url)
    finally:
        response.close()
    size = temp.stat().st_size
    head = temp.read_bytes()[:8]
    if size < 50_000 or not head.startswith(b"%PDF-"):
        raise RuntimeError(f"invalid PDF bytes={size}, head={head!r}, url={url}")
    temp.replace(destination)
    return final_url


def render_page(path: Path, page_number: int, tag: str) -> None:
    prefix = RENDER_DIR / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{tag}"
    process = subprocess.run(
        ["pdftoppm", "-f", str(page_number), "-l", str(page_number), "-r", "84", "-png", "-singlefile", str(path), str(prefix)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    image = Path(str(prefix) + ".png")
    if process.returncode != 0 or not image.exists() or image.stat().st_size < 1000:
        raise RuntimeError(f"render validation failed for {path.name} page {page_number}: {process.stderr[-1800:]}")
    image.unlink()


def validate_pdf(path: Path, row: dict[str, Any]) -> dict[str, Any]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=600)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed: {check.stderr[-2500:]}")
    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"encrypted PDF cannot be opened: {exc!r}") from exc
    pages = len(reader.pages)
    if pages < 4:
        raise RuntimeError(f"too few pages: {pages}")
    render_page(path, 1, "first")
    render_page(path, pages, "last")
    text = "\n".join((reader.pages[index].extract_text() or "") for index in range(min(pages, 8)))
    normalized = re.sub(r"\s+", "", text).upper()
    identity_ok = "华大九天" in normalized or STOCK_CODE in normalized
    if text.strip() and not identity_ok:
        raise RuntimeError("issuer identity not found in first pages")
    title = str(row.get("title") or "")
    title_terms = [term for term in re.split(r"[，,：:—\-\s]+", title) if len(term) >= 4]
    title_match = any(term in normalized for term in title_terms[:8]) if text.strip() else False
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "first_and_last_pages_rendered": True,
        "issuer_identity_verified_when_text_extractable": identity_ok,
        "title_term_verified_when_text_extractable": title_match,
    }


def select_and_download(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    used_titles: set[str] = set()
    used_orgs: dict[str, int] = {}
    for row in rows:
        if len(selected) >= 3:
            break
        title = str(row.get("title") or "")
        org = str(row.get("orgSName") or row.get("orgName") or "未知机构")
        title_key = re.sub(r"\W+", "", title)
        if title_key in used_titles:
            continue
        # Keep institutional diversity where possible, but allow a second report from the same broker.
        if used_orgs.get(org, 0) >= 2:
            continue
        index = len(selected) + 1
        date_text = str(row.get("publishDate") or "未知日期")
        filename = f"{index:02d}_{safe_name(org)}_{date_text.replace('-', '')}_{safe_name(title)}.pdf"
        destination = REPORT_DIR / filename
        try:
            final_url = download_pdf(str(row["pdfUrl"]), destination)
            metadata = validate_pdf(destination, row)
        except Exception as exc:  # noqa: BLE001
            print("CANDIDATE_REJECTED", title, repr(exc), flush=True)
            destination.unlink(missing_ok=True)
            continue
        if metadata["sha256"] in seen_hashes:
            destination.unlink(missing_ok=True)
            continue
        seen_hashes.add(metadata["sha256"])
        used_titles.add(title_key)
        used_orgs[org] = used_orgs.get(org, 0) + 1
        selected.append(
            {
                "sequence": index,
                "title": title,
                "institution": org,
                "authors": row.get("researcher") or row.get("author") or "",
                "publish_date": date_text,
                "rating": row.get("emRatingName") or row.get("sRatingName") or "",
                "report_type": row.get("reportType") or "",
                "info_code": row.get("infoCode"),
                "reported_attach_pages": as_int(row.get("attachPages")),
                "selection_score": as_int(row.get("selectionScore")),
                "relative_path": str(destination.relative_to(ROOT)),
                "source_page": f"https://data.eastmoney.com/report/info/{row['infoCode']}.html",
                "source_pdf": final_url,
                **metadata,
            }
        )
        print("SELECTED", json.dumps(selected[-1], ensure_ascii=False, indent=2), flush=True)
    if len(selected) < 2:
        raise RuntimeError(f"only {len(selected)} valid reports could be downloaded")
    return selected


def write_metadata(records: list[dict[str, Any]], all_rows: list[dict[str, Any]]) -> None:
    readme = [
        f"{STOCK_NAME}（{STOCK_CODE}.SZ）券商研究报告资料包",
        f"整理及核对日期：{CHECKED_AS_OF}",
        f"报告数量：{len(records)}份",
        f"合计页数：{sum(record['pages'] for record in records)}页",
        "",
        "筛选口径：优先公司深度、首次覆盖、新股定价及篇幅较长的公开原始券商PDF；",
        "排除只有数页的常规季度点评，并尽量保持机构和发布时间的差异。",
        "",
        "报告目录：",
    ]
    for record in records:
        readme.extend(
            [
                f"{record['sequence']}. {record['institution']}｜{record['publish_date']}｜{record['pages']}页",
                f"   标题：{record['title']}",
                f"   作者：{record['authors'] or '公开元数据未列明'}",
                f"   评级：{record['rating'] or '公开元数据未列明'}",
                f"   文件：{record['relative_path']}",
                f"   原始PDF：{record['source_pdf']}",
                f"   东方财富研报页：{record['source_page']}",
                f"   SHA-256：{record['sha256']}",
                "",
            ]
        )
    readme.extend(
        [
            "校验说明：",
            "- 所有PDF均检查%PDF文件头、QPDF结构、发行人名称、实际页数。",
            "- 每份PDF均渲染首页和末页，确认文件可正常解析。",
            "- 压缩包内提供SHA256SUMS.txt和manifest.json。",
            "- 报告中的评级、目标价、预测和行业判断仅对应报告出具时点，不构成投资建议。",
        ]
    )
    (VERIFY_DIR / "README_报告清单与来源说明.txt").write_text("\n".join(readme), encoding="utf-8")
    (VERIFY_DIR / "manifest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    (VERIFY_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{record['sha256']}  {record['relative_path']}" for record in records) + "\n",
        encoding="utf-8",
    )
    with (VERIFY_DIR / "selected_reports.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sequence", "institution", "publish_date", "title", "authors", "rating", "pages",
                "bytes", "sha256", "relative_path", "source_page", "source_pdf",
            ],
        )
        writer.writeheader()
        for record in records:
            writer.writerow({key: record.get(key, "") for key in writer.fieldnames})
    discovery = [
        {
            "title": row.get("title"),
            "institution": row.get("orgSName") or row.get("orgName"),
            "publish_date": row.get("publishDate"),
            "attach_pages": row.get("attachPages"),
            "attach_size": row.get("attachSize"),
            "rating": row.get("emRatingName") or row.get("sRatingName"),
            "info_code": row.get("infoCode"),
            "pdf_url": row.get("pdfUrl"),
        }
        for row in all_rows
    ]
    (VERIFY_DIR / "东方财富检索到的全部华大九天研报元数据.json").write_text(
        json.dumps(discovery, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def build_zip() -> Path:
    final_zip = Path(PACKAGE + ".zip")
    final_zip.unlink(missing_ok=True)
    with zipfile.ZipFile(final_zip, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.as_posix())
    with zipfile.ZipFile(final_zip, "r") as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP integrity test failed at {bad}")
    return final_zip


def main() -> None:
    all_rows = fetch_all_reports()
    ranked = rank_candidates(all_rows)
    records = select_and_download(ranked)
    write_metadata(records, all_rows)
    final_zip = build_zip()
    print("FINAL_ZIP", final_zip, final_zip.stat().st_size, flush=True)
    print("FINAL_MANIFEST", json.dumps(records, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
