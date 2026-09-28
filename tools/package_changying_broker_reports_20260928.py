from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from pypdf import PdfReader

COMPANY = "长盈精密"
CODE = "300115"
ROOT = Path("长盈精密_300115_券商深度报告_3份")
REPORT_DIR = ROOT / "01_券商深度报告"
NOTES_DIR = ROOT / "02_资料说明"
TMP_DIR = Path("_tmp_changying_broker_reports")
PREVIEW_DIR = Path("_previews_changying_broker_reports")
ZIP_PATH = Path("长盈精密_300115_券商深度报告_3份.zip")
RESULT_JSON = Path("changying_broker_reports_result.json")

REPORT_API = "https://reportapi.eastmoney.com/report/list"

CANDIDATES = [
    {
        "priority": 1,
        "title_contains": "精密制造全球龙头，全面拥抱新兴产业",
        "institution_expected": "华鑫证券",
        "min_pages": 15,
    },
    {
        "priority": 2,
        "title_contains": "双支柱战略格局形成",
        "institution_expected": "西部证券",
        "min_pages": 15,
    },
    {
        "priority": 3,
        "title_contains": "引擎切换，新动能助推进入快车道",
        "institution_expected": "信达证券",
        "min_pages": 15,
    },
    {
        "priority": 4,
        "title_contains": "消费电子、新能源双轮驱动",
        "institution_expected": "华鑫证券",
        "min_pages": 12,
    },
    {
        "priority": 5,
        "title_contains": "新能源汽车，机器人积极布局",
        "institution_expected": "中邮证券",
        "min_pages": 5,
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_title(value: str) -> str:
    return re.sub(r"\s+", "", html.unescape(value or "")).replace("：", ":")


def clean_url(value: str) -> str:
    value = html.unescape(value).replace("\\/", "/")
    value = value.strip().strip('"\'')
    return value.rstrip("\\,;)]}")


def parse_json_or_jsonp(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)
    match = re.search(r"^[^(]+\((.*)\)\s*;?\s*$", stripped, flags=re.S)
    if not match:
        raise RuntimeError("研报接口返回内容不是JSON或JSONP")
    return json.loads(match.group(1))


def fetch_report_inventory(session: requests.Session) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for year in range(2019, 2027):
        params = {
            "cb": "datatable",
            "pageSize": "200",
            "pageNo": "1",
            "qType": "0",
            "orgCode": "",
            "code": CODE,
            "industryCode": "",
            "industry": "",
            "rating": "",
            "ratingchange": "",
            "beginTime": f"{year}-01-01",
            "endTime": f"{year}-12-31",
            "fields": "",
            "p": "1",
            "pageNum": "1",
            "pageNumber": "1",
        }
        response = session.get(
            REPORT_API,
            params=params,
            headers={**HEADERS, "Accept": "application/json,text/javascript,*/*;q=0.8"},
            timeout=120,
        )
        print("REPORT_LIST", year, response.status_code, response.url, len(response.content), flush=True)
        response.raise_for_status()
        data = parse_json_or_jsonp(response.text)
        rows = data.get("data") or data.get("result") or data.get("reports") or []
        if isinstance(rows, dict):
            rows = rows.get("data") or rows.get("list") or rows.get("rows") or []
        if not isinstance(rows, list):
            rows = []
        print("REPORT_COUNT", year, len(rows), flush=True)
        inventory.extend(row for row in rows if isinstance(row, dict))

    dedup: dict[str, dict[str, Any]] = {}
    for row in inventory:
        info_code = str(row.get("infoCode") or row.get("info_code") or row.get("artCode") or "")
        if info_code:
            dedup[info_code] = row
    result = list(dedup.values())
    print("INVENTORY_TOTAL", len(result), flush=True)
    return result


def select_candidates(inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        needle = normalize_title(candidate["title_contains"])
        matches: list[dict[str, Any]] = []
        for row in inventory:
            title = str(row.get("title") or row.get("reportTitle") or row.get("name") or "")
            if needle in normalize_title(title):
                matches.append(row)
        if not matches:
            print("CANDIDATE_NOT_FOUND", candidate["title_contains"], flush=True)
            continue
        matches.sort(key=lambda row: str(row.get("publishDate") or row.get("publish_date") or ""), reverse=True)
        row = matches[0]
        info_code = str(row.get("infoCode") or row.get("info_code") or row.get("artCode") or "")
        institution = str(row.get("orgSName") or row.get("orgName") or row.get("org") or candidate["institution_expected"])
        date = str(row.get("publishDate") or row.get("publish_date") or "")[:10]
        title = str(row.get("title") or row.get("reportTitle") or candidate["title_contains"])
        authors = str(row.get("researcher") or row.get("author") or "")
        rating = str(row.get("emRatingName") or row.get("ratingName") or row.get("rating") or "")
        record = {
            **candidate,
            "info_code": info_code,
            "institution": institution,
            "date": date,
            "title": title,
            "authors": authors,
            "rating": rating,
            "raw_inventory_row": row,
        }
        print("CANDIDATE_SELECTED", json.dumps({k: record[k] for k in ("priority", "info_code", "institution", "date", "title", "authors", "rating")}, ensure_ascii=False), flush=True)
        selected.append(record)
    return selected


def discover_pdf_urls(session: requests.Session, report: dict[str, Any]) -> list[str]:
    code = report["info_code"]
    page_url = f"https://data.eastmoney.com/report/info/{code}.html"
    urls: list[str] = []
    try:
        response = session.get(
            page_url,
            headers={**HEADERS, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
            timeout=120,
        )
        print("REPORT_PAGE", code, response.status_code, response.url, len(response.content), flush=True)
        response.raise_for_status()
        text = html.unescape(response.text).replace("\\/", "/")
        patterns = [
            r"https?://pdf\.dfcfw\.com/pdf/[^\s\"'<>]+",
            r"//pdf\.dfcfw\.com/pdf/[^\s\"'<>]+",
            rf"https?://[^\s\"'<>]*{re.escape(code)}[^\s\"'<>]*\.pdf[^\s\"'<>]*",
        ]
        for pattern in patterns:
            for match in re.findall(pattern, text, flags=re.I):
                url = clean_url(match)
                if url.startswith("//"):
                    url = "https:" + url
                elif url.startswith("/"):
                    url = urljoin(str(response.url), url)
                if code in url and url not in urls:
                    urls.append(url)
    except Exception as exc:
        print("REPORT_PAGE_WARNING", code, repr(exc), flush=True)

    stamp = int(time.time() * 1000)
    constructed = [
        f"https://pdf.dfcfw.com/pdf/H3_{code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{code}_1.pdf?{stamp}.pdf=",
        f"https://pdf.dfcfw.com/pdf/H3_{code}_1.pdf?{stamp}",
        f"https://pdf.dfcfw.com/pdf/H3_{code}_1.pdf?{code}.pdf=",
    ]
    for url in constructed:
        if url not in urls:
            urls.append(url)
    print("PDF_CANDIDATES", code, json.dumps(urls, ensure_ascii=False), flush=True)
    return urls


def safe_filename(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", "", value)
    return value[:85]


def download_pdf(session: requests.Session, report: dict[str, Any], destination: Path) -> str:
    page_url = f"https://data.eastmoney.com/report/info/{report['info_code']}.html"
    last_error: Exception | None = None
    for url in discover_pdf_urls(session, report):
        for attempt in range(1, 4):
            part = destination.with_suffix(destination.suffix + ".part")
            try:
                if part.exists():
                    part.unlink()
                headers = {
                    **HEADERS,
                    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
                    "Referer": page_url,
                }
                with session.get(url, headers=headers, stream=True, timeout=(45, 240), allow_redirects=True) as response:
                    print(
                        "PDF_RESPONSE",
                        report["info_code"],
                        attempt,
                        response.status_code,
                        response.url,
                        response.headers.get("content-type"),
                        response.headers.get("content-length"),
                        flush=True,
                    )
                    response.raise_for_status()
                    with part.open("wb") as stream:
                        for chunk in response.iter_content(1024 * 1024):
                            if chunk:
                                stream.write(chunk)
                size = part.stat().st_size
                if size < 120_000:
                    raise RuntimeError(f"PDF文件过小：{size}")
                with part.open("rb") as stream:
                    if stream.read(5) != b"%PDF-":
                        raise RuntimeError("下载内容不是PDF")
                part.replace(destination)
                print("PDF_DOWNLOADED", destination, size, url, flush=True)
                return url
            except Exception as exc:
                last_error = exc
                print("PDF_RETRY", report["info_code"], attempt, url, repr(exc), flush=True)
                time.sleep(attempt * 2)
    raise RuntimeError(f"无法下载{report['title']}：{last_error!r}")


def validate_pdf(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < int(report["min_pages"]):
        raise RuntimeError(f"{path.name}页数仅{pages}，不符合候选深度报告的最低页数要求")

    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=240,
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf校验失败：{path.name}: {qpdf.stderr[-1000:]}")

    text_parts: list[str] = []
    for page in reader.pages[: min(pages, 14)]:
        try:
            text_parts.append(page.extract_text() or "")
        except Exception as exc:
            print("TEXT_EXTRACT_WARNING", path.name, repr(exc), flush=True)
    compact_text = re.sub(r"\s+", "", "".join(text_parts))
    identity_match = COMPANY in compact_text or CODE in compact_text
    institution_match = report["institution"] in compact_text or report["institution_expected"] in compact_text
    if len(compact_text) > 500 and not identity_match:
        raise RuntimeError(f"报告文本未识别到{COMPANY}或{CODE}：{path.name}")

    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    preview_base = PREVIEW_DIR / path.stem
    subprocess.run(
        ["pdftoppm", "-f", "1", "-singlefile", "-png", "-r", "140", str(path), str(preview_base)],
        check=True,
        timeout=240,
        capture_output=True,
    )
    preview = preview_base.with_suffix(".png")
    if not preview.exists() or preview.stat().st_size < 8_000:
        raise RuntimeError(f"首页渲染失败：{path.name}")

    result = {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "identity_text_match": identity_match,
        "institution_text_match": institution_match,
        "first_page_preview": str(preview),
    }
    print("PDF_VALIDATED", path.name, json.dumps(result, ensure_ascii=False), flush=True)
    return result


def reset_outputs() -> None:
    for path in (ROOT, TMP_DIR, PREVIEW_DIR):
        if path.exists():
            shutil.rmtree(path)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    if RESULT_JSON.exists():
        RESULT_JSON.unlink()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)


def build_package() -> None:
    reset_outputs()
    session = requests.Session()
    session.headers.update(HEADERS)

    inventory = fetch_report_inventory(session)
    candidates = select_candidates(inventory)
    if len(candidates) < 3:
        raise RuntimeError(f"公开研报目录仅匹配到{len(candidates)}个候选，无法组成3份报告")

    selected: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    used_institutions: set[str] = set()

    for report in candidates:
        if len(selected) >= 3:
            break
        # 优先保持券商来源多样；但若后续候选不足，不强制排除重复机构。
        if report["institution"] in used_institutions and len(candidates) - report["priority"] >= 1:
            print("DIVERSITY_SKIP", report["institution"], report["title"], flush=True)
            continue
        temp_name = f"{report['priority']:02d}_{safe_filename(report['institution'])}_{report['date']}_{safe_filename(report['title'])}.pdf"
        temp_path = TMP_DIR / temp_name
        try:
            source_pdf_url = download_pdf(session, report, temp_path)
            validation = validate_pdf(temp_path, report)
            final_number = len(selected) + 1
            final_name = f"{final_number:02d}_{safe_filename(report['institution'])}_{report['date']}_{safe_filename(report['title'])}.pdf"
            final_path = REPORT_DIR / final_name
            shutil.move(str(temp_path), str(final_path))
            record = {
                **{k: v for k, v in report.items() if k != "raw_inventory_row"},
                **validation,
                "filename": str(final_path.relative_to(ROOT)),
                "report_page_url": f"https://data.eastmoney.com/report/info/{report['info_code']}.html",
                "source_pdf_url": source_pdf_url,
                "document_type": "券商原始排版PDF",
            }
            selected.append(record)
            used_institutions.add(report["institution"])
        except Exception as exc:
            errors.append({"info_code": report["info_code"], "title": report["title"], "error": repr(exc)})
            print("REPORT_FAILED", report["info_code"], repr(exc), flush=True)

    # 若多样性规则导致不足，补抓之前跳过的候选。
    if len(selected) < 3:
        selected_codes = {item["info_code"] for item in selected}
        for report in candidates:
            if len(selected) >= 3:
                break
            if report["info_code"] in selected_codes:
                continue
            temp_name = f"{report['priority']:02d}_{safe_filename(report['institution'])}_{report['date']}_{safe_filename(report['title'])}.pdf"
            temp_path = TMP_DIR / temp_name
            try:
                source_pdf_url = download_pdf(session, report, temp_path)
                validation = validate_pdf(temp_path, report)
                final_number = len(selected) + 1
                final_name = f"{final_number:02d}_{safe_filename(report['institution'])}_{report['date']}_{safe_filename(report['title'])}.pdf"
                final_path = REPORT_DIR / final_name
                shutil.move(str(temp_path), str(final_path))
                record = {
                    **{k: v for k, v in report.items() if k != "raw_inventory_row"},
                    **validation,
                    "filename": str(final_path.relative_to(ROOT)),
                    "report_page_url": f"https://data.eastmoney.com/report/info/{report['info_code']}.html",
                    "source_pdf_url": source_pdf_url,
                    "document_type": "券商原始排版PDF",
                }
                selected.append(record)
                selected_codes.add(report["info_code"])
            except Exception as exc:
                errors.append({"info_code": report["info_code"], "title": report["title"], "error": repr(exc)})
                print("REPORT_FAILED_FALLBACK", report["info_code"], repr(exc), flush=True)

    if len(selected) < 3:
        raise RuntimeError(f"仅成功取得{len(selected)}份报告；错误：{errors}")

    manifest = {
        "company": COMPANY,
        "stock_code": f"{CODE}.SZ",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "report_count": len(selected),
        "reports": selected,
        "fallback_errors": errors,
        "validation": "PDF文件头、页数、qpdf结构、文本身份匹配（可提取时）及首页渲染均已检查。",
    }
    (NOTES_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (NOTES_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{item['sha256']}  {item['filename']}" for item in selected) + "\n",
        encoding="utf-8",
    )

    lines = [
        f"公司：{COMPANY}（{CODE}.SZ）",
        f"券商深度报告：{len(selected)}份",
        "",
    ]
    for index, item in enumerate(selected, start=1):
        size_mb = item["bytes"] / 1024 / 1024
        lines.extend(
            [
                f"{index}. {item['institution']}《{item['title']}》",
                f"   日期：{item['date']}；作者：{item['authors'] or '公开目录未列全'}；评级：{item['rating'] or '公开目录未列'}",
                f"   页数：{item['pages']}页；文件大小：{size_mb:.2f} MB",
                f"   东方财富研报编号：{item['info_code']}",
                f"   文件：{item['filename']}",
                "",
            ]
        )
    lines.extend(
        [
            "文件说明：",
            "- 压缩包仅收录券商原始排版PDF，不以网页摘要或自制整理版替代。",
            "- 各PDF均完成文件头、页数、结构、公司名称匹配和首页渲染检查。",
            "- 来源页和原始PDF地址记录在manifest.json中。",
        ]
    )
    (NOTES_DIR / "资料清单与来源说明.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.as_posix())
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise RuntimeError(f"ZIP完整性检查失败：{bad_member}")

    result = {
        "zip_filename": ZIP_PATH.name,
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256(ZIP_PATH),
        "report_count": len(selected),
        "reports": selected,
        "fallback_errors": errors,
    }
    RESULT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PACKAGE_COMPLETE", json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    build_package()
