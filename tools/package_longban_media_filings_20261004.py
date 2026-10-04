from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

COMPANY_SHORT = "龙版传媒"
COMPANY_FULL = "黑龙江出版传媒股份有限公司"
STOCK_CODE = "605577"

ROOT = Path("龙版传媒_605577_所有年报_招股说明书及最新季报")
ANNUAL_DIR = ROOT / "01_年度报告"
PROSPECTUS_DIR = ROOT / "02_招股说明书"
QUARTER_DIR = ROOT / "03_最新季报"
HALF_DIR = ROOT / "04_补充_最新半年度报告"
NOTES_DIR = ROOT / "05_资料说明"
TMP_DIR = Path("_tmp_longban_media_filings")
PREVIEW_DIR = Path("_previews_longban_media_filings")
ZIP_PATH = Path("龙版传媒_605577_所有年报_招股说明书及最新季报.zip")
RESULT_JSON = Path("longban_media_filings_result.json")

CNINFO_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STATIC_ROOT = "https://static.cninfo.com.cn/"
DATE_RANGE = "2019-01-01~2026-12-31"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Referer": "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
    "Origin": "https://www.cninfo.com.cn",
}

MARKET_STRATEGIES = [
    ("sse", "sh"),
    ("szse", "sh"),
    ("sse", ""),
    ("szse", ""),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_title(title: str) -> str:
    title = re.sub(r"<[^>]+>", "", title or "")
    title = title.replace("&nbsp;", " ")
    return re.sub(r"\s+", "", title)


def safe_filename(text: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]", "_", text)
    text = re.sub(r"\s+", "", text)
    return text.strip("._")


def announcement_date(ms: int | None) -> str:
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def reset_outputs() -> None:
    for path in (ROOT, TMP_DIR, PREVIEW_DIR):
        if path.exists():
            shutil.rmtree(path)
    for path in (ZIP_PATH, RESULT_JSON):
        if path.exists():
            path.unlink()
    for path in (ANNUAL_DIR, PROSPECTUS_DIR, QUARTER_DIR, HALF_DIR, NOTES_DIR, TMP_DIR, PREVIEW_DIR):
        path.mkdir(parents=True, exist_ok=True)


def query_once(
    session: requests.Session,
    *,
    category: str,
    searchkey: str,
    column: str,
    plate: str,
    date_range: str = DATE_RANGE,
    max_pages: int = 20,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_fingerprints: set[tuple[str, ...]] = set()
    page_num = 1
    while True:
        data = {
            "pageNum": str(page_num),
            "pageSize": "50",
            "column": column,
            "tabName": "fulltext",
            "plate": plate,
            "stock": "",
            "searchkey": searchkey,
            "secid": "",
            "category": category,
            "trade": "",
            "seDate": date_range,
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        response = session.post(CNINFO_QUERY_URL, data=data, headers=HEADERS, timeout=(30, 120))
        print(
            "QUERY",
            category or "ALL",
            searchkey,
            column,
            plate or "NONE",
            page_num,
            response.status_code,
            len(response.content),
            flush=True,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("announcements") or []
        print("QUERY_ROWS", category or "ALL", searchkey, column, plate or "NONE", page_num, len(rows), flush=True)
        fingerprint = tuple(str(row.get("announcementId") or row.get("adjunctUrl") or "") for row in rows)
        if fingerprint and fingerprint in seen_fingerprints:
            print("QUERY_REPEATED_PAGE_BREAK", category or "ALL", searchkey, column, plate or "NONE", page_num, flush=True)
            break
        if fingerprint:
            seen_fingerprints.add(fingerprint)
        records.extend(rows)
        total_pages = int(payload.get("totalpages") or 1)
        if page_num >= total_pages or not rows:
            break
        page_num += 1
        if page_num > max_pages:
            print("QUERY_SAFETY_BREAK", category or "ALL", searchkey, column, plate or "NONE", page_num, flush=True)
            break
    return records


def row_matches_company(row: dict[str, Any], allow_unlisted: bool) -> bool:
    sec_code = str(row.get("secCode") or "")
    if sec_code == STOCK_CODE:
        return True
    if not allow_unlisted:
        return False
    sec_name = clean_title(str(row.get("secName") or ""))
    title = clean_title(str(row.get("announcementTitle") or row.get("shortTitle") or ""))
    combined = sec_name + title
    return any(token in combined for token in (COMPANY_SHORT, "黑龙江出版传媒", COMPANY_FULL))


def query_company(session: requests.Session, category: str, *, allow_unlisted: bool = False) -> list[dict[str, Any]]:
    search_terms = [
        COMPANY_SHORT,
        "黑龙江出版传媒",
        COMPANY_FULL,
        STOCK_CODE,
    ]
    if allow_unlisted:
        search_terms.extend(
            [
                "龙版传媒招股说明书",
                "黑龙江出版传媒招股说明书",
                "首次公开发行股票招股说明书",
            ]
        )
    combined: dict[str, dict[str, Any]] = {}
    categories = [category]
    if allow_unlisted and category:
        categories.append("")

    for cat in categories:
        for column, plate in MARKET_STRATEGIES:
            for term in search_terms:
                rows = query_once(
                    session,
                    category=cat,
                    searchkey=term,
                    column=column,
                    plate=plate,
                )
                for row in rows:
                    if not row_matches_company(row, allow_unlisted=allow_unlisted):
                        continue
                    key = str(row.get("announcementId") or row.get("adjunctUrl") or "")
                    if key:
                        combined[key] = row
            if combined and not allow_unlisted:
                break
        if combined and not allow_unlisted:
            break
    print("QUERY_COMPANY_RESULT", category or "ALL", len(combined), flush=True)
    return list(combined.values())


def normalized_record(row: dict[str, Any]) -> dict[str, Any]:
    title = clean_title(str(row.get("announcementTitle") or row.get("shortTitle") or ""))
    adjunct = str(row.get("adjunctUrl") or "").lstrip("/")
    return {
        "title": title,
        "announcement_id": str(row.get("announcementId") or ""),
        "announcement_time_ms": int(row.get("announcementTime") or 0),
        "announcement_date": announcement_date(int(row.get("announcementTime") or 0)),
        "adjunct_size_kb": int(row.get("adjunctSize") or 0),
        "source_url": CNINFO_STATIC_ROOT + adjunct if adjunct else "",
        "adjunct_url": adjunct,
        "sec_code": str(row.get("secCode") or ""),
        "sec_name": clean_title(str(row.get("secName") or "")),
        "source_provider": "巨潮资讯网官方披露PDF",
    }


def select_all_annuals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_year: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        rec = normalized_record(row)
        title = rec["title"]
        match = re.search(r"(20\d{2})年年度报告", title)
        if not match:
            continue
        if any(token in title for token in ("摘要", "英文版", "取消", "问询函", "回复", "提示性公告", "关于")):
            continue
        year = int(match.group(1))
        by_year.setdefault(year, []).append(rec)
    if not by_year:
        raise RuntimeError("未找到完整年度报告")

    selected: list[dict[str, Any]] = []
    for year in sorted(by_year):
        candidates = by_year[year]

        def score(item: dict[str, Any]) -> tuple[int, int, int, int]:
            title = item["title"]
            corrected = 1 if any(token in title for token in ("更正后", "修订版", "更新版")) else 0
            exact = 1 if title == f"{year}年年度报告" else 0
            return (corrected, exact, int(item["announcement_time_ms"]), int(item["adjunct_size_kb"]))

        chosen = max(candidates, key=score)
        selected.append(chosen)
        print("SELECT_ANNUAL", year, json.dumps(chosen, ensure_ascii=False), flush=True)
    return selected


def select_prospectus(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        rec = normalized_record(row)
        title = rec["title"]
        if "招股说明书" not in title:
            continue
        if any(
            token in title
            for token in (
                "摘要",
                "招股意向书",
                "上市公告书",
                "提示性公告",
                "更正公告",
                "问询",
                "回复",
                "确认意见",
                "保荐书",
                "保荐工作报告",
                "法律意见",
                "律师工作报告",
            )
        ):
            continue
        if not rec["source_url"]:
            continue
        candidates.append(rec)
    if not candidates:
        sample = [normalized_record(row)["title"] for row in rows[:80]]
        print("PROSPECTUS_TITLES_SAMPLE", json.dumps(sample, ensure_ascii=False), flush=True)
        raise RuntimeError("未找到最终版招股说明书")

    def score(item: dict[str, Any]) -> tuple[int, int, int, int, int]:
        title = item["title"]
        final_exact = 1 if "首次公开发行股票招股说明书" in title or "首次公开发行股票并上市招股说明书" in title else 0
        ipo = 1 if "首次公开发行" in title else 0
        final_version = 1 if not any(token in title for token in ("申报稿", "预披露", "注册稿")) else 0
        return (
            final_exact,
            ipo,
            final_version,
            int(item["announcement_time_ms"]),
            int(item["adjunct_size_kb"]),
        )

    chosen = max(candidates, key=score)
    print("SELECT_PROSPECTUS", json.dumps(chosen, ensure_ascii=False), flush=True)
    return chosen


def is_quarter_report(title: str) -> bool:
    if "季度报告" not in title:
        return False
    if any(token in title for token in ("摘要", "正文", "取消", "更正公告", "提示性公告", "关于")):
        return False
    return any(token in title for token in ("一季度", "第一季度", "三季度", "第三季度"))


def select_latest_quarter(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [normalized_record(row) for row in rows if is_quarter_report(normalized_record(row)["title"])]
    if not candidates:
        raise RuntimeError("未找到最新季度报告")

    def score(item: dict[str, Any]) -> tuple[int, int, int]:
        title = item["title"]
        corrected = 1 if any(token in title for token in ("更正后", "修订版", "更新版")) else 0
        return (int(item["announcement_time_ms"]), corrected, int(item["adjunct_size_kb"]))

    chosen = max(candidates, key=score)
    print("SELECT_QUARTER", json.dumps(chosen, ensure_ascii=False), flush=True)
    return chosen


def select_latest_half_year(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        rec = normalized_record(row)
        title = rec["title"]
        if "半年度报告" not in title:
            continue
        if any(token in title for token in ("摘要", "英文版", "取消", "更正公告", "提示性公告", "关于")):
            continue
        candidates.append(rec)
    if not candidates:
        return None
    chosen = max(candidates, key=lambda item: (int(item["announcement_time_ms"]), int(item["adjunct_size_kb"])))
    print("SELECT_HALF", json.dumps(chosen, ensure_ascii=False), flush=True)
    return chosen


def download_pdf(session: requests.Session, record: dict[str, Any], destination: Path) -> None:
    if not record.get("source_url"):
        raise RuntimeError(f"缺少PDF来源：{record['title']}")
    last_error: Exception | None = None
    destination.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, 5):
        part = destination.with_suffix(destination.suffix + ".part")
        try:
            if part.exists():
                part.unlink()
            headers = {
                **HEADERS,
                "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
                "Referer": "https://www.cninfo.com.cn/",
            }
            with session.get(record["source_url"], headers=headers, stream=True, timeout=(30, 240), allow_redirects=True) as response:
                print(
                    "DOWNLOAD_RESPONSE",
                    record["title"],
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
            if size < 60_000:
                raise RuntimeError(f"PDF文件过小：{size}")
            with part.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise RuntimeError("下载内容不是PDF")
            part.replace(destination)
            return
        except Exception as exc:
            last_error = exc
            print("DOWNLOAD_RETRY", record["title"], attempt, repr(exc), flush=True)
            time.sleep(attempt * 2)
    raise RuntimeError(f"无法下载{record['title']}：{last_error!r}")


def validate_pdf(path: Path, min_pages: int) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size < 60_000:
        raise RuntimeError(f"PDF缺失或过小：{path}")
    if path.read_bytes()[:5] != b"%PDF-":
        raise RuntimeError(f"PDF文件头异常：{path}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"{path.name}页数仅{pages}，低于最低要求{min_pages}")

    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=240,
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf校验失败：{path.name}: {qpdf.stderr[-1200:]}")

    text_result = subprocess.run(
        ["pdftotext", "-f", "1", "-l", str(min(pages, 10)), str(path), "-"],
        capture_output=True,
        timeout=180,
    )
    extracted = text_result.stdout.decode("utf-8", errors="ignore") if text_result.stdout else ""
    compact = re.sub(r"\s+", "", extracted)
    identity_match = STOCK_CODE in compact or COMPANY_SHORT in compact or "黑龙江出版传媒" in compact
    if len(compact) > 500 and not identity_match:
        raise RuntimeError(f"报告文本未识别到公司名称或证券代码：{path.name}")

    first_stem = PREVIEW_DIR / path.stem
    subprocess.run(
        ["pdftoppm", "-f", "1", "-singlefile", "-png", "-r", "120", str(path), str(first_stem)],
        check=True,
        timeout=240,
        capture_output=True,
    )
    first_png = first_stem.with_suffix(".png")
    if not first_png.exists() or first_png.stat().st_size < 8_000:
        raise RuntimeError(f"首页渲染失败：{path.name}")

    last_stem = PREVIEW_DIR / f"{path.stem}_last"
    subprocess.run(
        ["pdftoppm", "-f", str(pages), "-l", str(pages), "-singlefile", "-png", "-r", "90", str(path), str(last_stem)],
        check=True,
        timeout=240,
        capture_output=True,
    )
    last_png = last_stem.with_suffix(".png")
    if not last_png.exists() or last_png.stat().st_size < 4_000:
        raise RuntimeError(f"末页渲染失败：{path.name}")

    validation = {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "identity_text_match": identity_match,
        "first_page_preview": str(first_png),
        "last_page_preview": str(last_png),
    }
    print("VALIDATED", path.name, json.dumps(validation, ensure_ascii=False), flush=True)
    return validation


def save_document(
    session: requests.Session,
    record: dict[str, Any],
    category: str,
    destination_dir: Path,
    filename: str,
    min_pages: int,
) -> dict[str, Any]:
    tmp_path = TMP_DIR / filename
    download_pdf(session, record, tmp_path)
    validation = validate_pdf(tmp_path, min_pages)
    final_path = destination_dir / filename
    shutil.move(str(tmp_path), str(final_path))
    return {
        "category": category,
        **record,
        **validation,
        "filename": str(final_path.relative_to(ROOT)),
    }


def build_package() -> None:
    reset_outputs()
    session = requests.Session()
    session.headers.update(HEADERS)

    annual_rows = query_company(session, "category_ndbg_szsh")
    quarter_rows = query_company(session, "category_yjdbg_szsh")
    half_rows = query_company(session, "category_bndbg_szsh")
    prospectus_rows = query_company(session, "category_zgsms_szsh", allow_unlisted=True)

    annuals = select_all_annuals(annual_rows)
    prospectus = select_prospectus(prospectus_rows)
    latest_quarter = select_latest_quarter(quarter_rows)
    latest_half = select_latest_half_year(half_rows)

    documents: list[dict[str, Any]] = []
    for record in annuals:
        year_match = re.search(r"(20\d{2})年", record["title"])
        if not year_match:
            raise RuntimeError(f"无法识别年报年份：{record['title']}")
        year = year_match.group(1)
        filename = f"{year}_{COMPANY_SHORT}_{safe_filename(record['title'])}.pdf"
        documents.append(save_document(session, record, "年度报告", ANNUAL_DIR, filename, 50))

    prospectus_filename = f"{COMPANY_SHORT}_{safe_filename(prospectus['title'])}.pdf"
    documents.append(save_document(session, prospectus, "招股说明书", PROSPECTUS_DIR, prospectus_filename, 150))

    quarter_filename = f"最新季报_{COMPANY_SHORT}_{safe_filename(latest_quarter['title'])}.pdf"
    documents.append(save_document(session, latest_quarter, "最新季度报告", QUARTER_DIR, quarter_filename, 5))

    if latest_half and int(latest_half["announcement_time_ms"]) > int(latest_quarter["announcement_time_ms"]):
        half_filename = f"补充_{COMPANY_SHORT}_{safe_filename(latest_half['title'])}.pdf"
        documents.append(save_document(session, latest_half, "补充_最新半年度报告", HALF_DIR, half_filename, 30))

    annual_years = []
    for item in documents:
        if item["category"] == "年度报告":
            match = re.search(r"(20\d{2})年", item["title"])
            if match:
                annual_years.append(int(match.group(1)))

    manifest = {
        "company": COMPANY_FULL,
        "short_name": COMPANY_SHORT,
        "stock_code": STOCK_CODE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "document_count": len(documents),
        "annual_report_count": len(annual_years),
        "annual_years": sorted(annual_years),
        "prospectus_count": sum(1 for item in documents if item["category"] == "招股说明书"),
        "latest_quarter_title": latest_quarter["title"],
        "latest_quarter_announcement_date": latest_quarter["announcement_date"],
        "supplemental_half_year_count": sum(1 for item in documents if item["category"] == "补充_最新半年度报告"),
        "documents": documents,
        "validation": "已检查PDF文件头、实际页数、qpdf结构、公司名称或证券代码、首页与末页渲染，并完成ZIP CRC完整性测试。",
    }
    (NOTES_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (NOTES_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{item['sha256']}  {item['filename']}" for item in documents) + "\n",
        encoding="utf-8",
    )

    lines = [
        f"公司：{COMPANY_FULL}（{COMPANY_SHORT}，{STOCK_CODE}.SH）",
        f"文件总数：{len(documents)}份",
        "",
        "收录范围：",
        f"- 完整年度报告：{len(annual_years)}份，年份为{', '.join(str(year) for year in sorted(annual_years))}；",
        f"- 招股说明书：{prospectus['title']}；",
        f"- 最新正式季度报告：{latest_quarter['title']}，披露日期{latest_quarter['announcement_date']}；",
    ]
    if latest_half and int(latest_half["announcement_time_ms"]) > int(latest_quarter["announcement_time_ms"]):
        lines.append(f"- 补充收录披露时间更晚的{latest_half['title']}，披露日期{latest_half['announcement_date']}。")
    lines.extend(["", "文件明细："])
    for index, item in enumerate(documents, start=1):
        lines.append(
            f"{index}. {item['title']} | {item['announcement_date']} | {item['pages']}页 | "
            f"{item['bytes'] / 1024 / 1024:.2f} MB | {item['filename']}"
        )
        lines.append(f"   来源：{item.get('source_provider', '巨潮资讯网官方披露PDF')} | {item['source_url']}")
    lines.extend(
        [
            "",
            "校验说明：",
            "- 年度报告已排除摘要和提示性公告，仅收录完整报告；",
            "- 招股说明书优先选择最终发行版，排除招股意向书、申报稿及中介文件；",
            "- 已检查PDF文件头、页数、结构、公司名称/证券代码及首末页可渲染性；",
            "- SHA-256见SHA256SUMS.txt，详细元数据见manifest.json。",
        ]
    )
    (NOTES_DIR / "资料清单与官方来源.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.as_posix())
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC校验失败：{bad}")

    result = {
        "zip_filename": ZIP_PATH.name,
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256(ZIP_PATH),
        "document_count": len(documents),
        "annual_report_count": len(annual_years),
        "annual_years": sorted(annual_years),
        "prospectus_count": sum(1 for item in documents if item["category"] == "招股说明书"),
        "latest_quarter_title": latest_quarter["title"],
        "supplemental_half_year_count": sum(1 for item in documents if item["category"] == "补充_最新半年度报告"),
        "documents": documents,
    }
    RESULT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PACKAGE_COMPLETE", json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    build_package()
