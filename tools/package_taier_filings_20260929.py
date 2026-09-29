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

COMPANY_SHORT = "泰尔股份"
COMPANY_FULL = "泰尔重工股份有限公司"
STOCK_CODE = "002347"
ORG_ID = "gssz0002347"
ROOT = Path("泰尔股份_002347_2020-2025年报及最新季报")
ANNUAL_DIR = ROOT / "01_年度报告"
QUARTER_DIR = ROOT / "02_最新季报"
HALF_DIR = ROOT / "03_补充_最新半年度报告"
NOTES_DIR = ROOT / "04_资料说明"
TMP_DIR = Path("_tmp_taier_filings")
PREVIEW_DIR = Path("_previews_taier_filings")
ZIP_PATH = Path("泰尔股份_002347_2020-2025年报及最新季报.zip")
RESULT_JSON = Path("taier_filings_result.json")

CNINFO_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STATIC_ROOT = "https://static.cninfo.com.cn/"
DATE_RANGE = "2020-01-01~2026-12-31"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Referer": "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
    "Origin": "https://www.cninfo.com.cn",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_title(title: str) -> str:
    title = re.sub(r"<[^>]+>", "", title or "")
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
    for path in (ANNUAL_DIR, QUARTER_DIR, HALF_DIR, NOTES_DIR, TMP_DIR, PREVIEW_DIR):
        path.mkdir(parents=True, exist_ok=True)


def query_cninfo(session: requests.Session, category: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page_num = 1
    while True:
        data = {
            "pageNum": str(page_num),
            "pageSize": "50",
            "column": "szse",
            "tabName": "fulltext",
            "plate": "sz",
            "stock": f"{STOCK_CODE},{ORG_ID}",
            "searchkey": "",
            "secid": "",
            "category": category,
            "trade": "",
            "seDate": DATE_RANGE,
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        response = session.post(CNINFO_QUERY_URL, data=data, headers=HEADERS, timeout=(30, 90))
        print("QUERY", category, page_num, response.status_code, len(response.content), flush=True)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("announcements") or []
        print("QUERY_ROWS", category, page_num, len(rows), flush=True)
        records.extend(rows)
        total_pages = int(payload.get("totalpages") or 1)
        if page_num >= total_pages or not rows:
            break
        page_num += 1
        if page_num > 20:
            raise RuntimeError(f"CNINFO pagination exceeded safety limit for {category}")
    return records


def normalized_record(row: dict[str, Any]) -> dict[str, Any]:
    title = clean_title(str(row.get("announcementTitle") or row.get("shortTitle") or ""))
    adjunct = str(row.get("adjunctUrl") or "").lstrip("/")
    return {
        "title": title,
        "announcement_id": str(row.get("announcementId") or ""),
        "announcement_time_ms": int(row.get("announcementTime") or 0),
        "announcement_date": announcement_date(int(row.get("announcementTime") or 0)),
        "adjunct_size_kb": int(row.get("adjunctSize") or 0),
        "source_url": CNINFO_STATIC_ROOT + adjunct,
        "adjunct_url": adjunct,
        "sec_code": str(row.get("secCode") or ""),
        "sec_name": str(row.get("secName") or ""),
    }


def select_annual(rows: list[dict[str, Any]], year: int) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    year_text = str(year)
    for row in rows:
        rec = normalized_record(row)
        title = rec["title"]
        if year_text not in title or "年度报告" not in title:
            continue
        if any(token in title for token in ("摘要", "取消", "关于", "审核问询", "英文版")):
            continue
        if rec["sec_code"] and rec["sec_code"] != STOCK_CODE:
            continue
        candidates.append(rec)
    if not candidates:
        raise RuntimeError(f"未找到{year}年年度报告")

    def score(item: dict[str, Any]) -> tuple[int, int, int]:
        title = item["title"]
        revision = 1 if any(token in title for token in ("修订", "更新", "更正后")) else 0
        exact = 1 if title == f"{year}年年度报告" else 0
        return (revision, exact, int(item["announcement_time_ms"]))

    selected = max(candidates, key=score)
    print("SELECT_ANNUAL", year, json.dumps(selected, ensure_ascii=False), flush=True)
    return selected


def is_full_quarter_title(title: str) -> bool:
    if "季度报告" not in title:
        return False
    if any(token in title for token in ("摘要", "正文", "取消", "更正公告", "关于")):
        return False
    return any(token in title for token in ("一季度", "第一季度", "三季度", "第三季度"))


def select_latest_quarter(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        rec = normalized_record(row)
        if is_full_quarter_title(rec["title"]):
            candidates.append(rec)
    if not candidates:
        raise RuntimeError("未找到最新季度报告")
    selected = max(candidates, key=lambda item: int(item["announcement_time_ms"]))
    print("SELECT_QUARTER", json.dumps(selected, ensure_ascii=False), flush=True)
    return selected


def select_latest_half_year(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        rec = normalized_record(row)
        title = rec["title"]
        if "半年度报告" not in title:
            continue
        if any(token in title for token in ("摘要", "取消", "关于", "英文版")):
            continue
        candidates.append(rec)
    if not candidates:
        return None
    selected = max(candidates, key=lambda item: int(item["announcement_time_ms"]))
    print("SELECT_HALF", json.dumps(selected, ensure_ascii=False), flush=True)
    return selected


def download_pdf(session: requests.Session, record: dict[str, Any], destination: Path) -> None:
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
            with session.get(record["source_url"], headers=headers, stream=True, timeout=(30, 180), allow_redirects=True) as response:
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
            if size < 80_000:
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


def validate_pdf(path: Path, record: dict[str, Any], min_pages: int) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"{path.name}页数仅{pages}，低于最低要求{min_pages}")

    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf校验失败：{path.name}: {qpdf.stderr[-1200:]}")

    text_result = subprocess.run(
        ["pdftotext", "-f", "1", "-l", str(min(pages, 4)), str(path), "-"],
        capture_output=True,
        timeout=120,
    )
    extracted = text_result.stdout.decode("utf-8", errors="ignore") if text_result.stdout else ""
    compact = re.sub(r"\s+", "", extracted)
    identity_match = COMPANY_SHORT in compact or "泰尔重工" in compact or STOCK_CODE in compact
    if len(compact) > 300 and not identity_match:
        raise RuntimeError(f"报告文本未识别到公司名称或证券代码：{path.name}")

    preview_stem = PREVIEW_DIR / path.stem
    subprocess.run(
        ["pdftoppm", "-f", "1", "-singlefile", "-png", "-r", "120", str(path), str(preview_stem)],
        check=True,
        timeout=180,
        capture_output=True,
    )
    preview_first = preview_stem.with_suffix(".png")
    if not preview_first.exists() or preview_first.stat().st_size < 8_000:
        raise RuntimeError(f"首页渲染失败：{path.name}")

    last_stem = PREVIEW_DIR / f"{path.stem}_last"
    subprocess.run(
        ["pdftoppm", "-f", str(pages), "-l", str(pages), "-singlefile", "-png", "-r", "90", str(path), str(last_stem)],
        check=True,
        timeout=180,
        capture_output=True,
    )
    preview_last = last_stem.with_suffix(".png")
    if not preview_last.exists() or preview_last.stat().st_size < 4_000:
        raise RuntimeError(f"末页渲染失败：{path.name}")

    validation = {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "identity_text_match": identity_match,
        "first_page_preview": str(preview_first),
        "last_page_preview": str(preview_last),
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
    validation = validate_pdf(tmp_path, record, min_pages)
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

    annual_rows = query_cninfo(session, "category_ndbg_szsh")
    quarter_rows = query_cninfo(session, "category_yjdbg_szsh")
    half_rows = query_cninfo(session, "category_bndbg_szsh")

    documents: list[dict[str, Any]] = []
    for year in range(2020, 2026):
        record = select_annual(annual_rows, year)
        filename = f"{year}_{COMPANY_SHORT}_{safe_filename(record['title'])}.pdf"
        documents.append(save_document(session, record, "年度报告", ANNUAL_DIR, filename, 50))

    latest_quarter = select_latest_quarter(quarter_rows)
    quarter_filename = f"最新季报_{COMPANY_SHORT}_{safe_filename(latest_quarter['title'])}.pdf"
    documents.append(save_document(session, latest_quarter, "最新季度报告", QUARTER_DIR, quarter_filename, 5))

    latest_half = select_latest_half_year(half_rows)
    if latest_half and int(latest_half["announcement_time_ms"]) > int(latest_quarter["announcement_time_ms"]):
        half_filename = f"补充_{COMPANY_SHORT}_{safe_filename(latest_half['title'])}.pdf"
        documents.append(save_document(session, latest_half, "补充_最新半年度报告", HALF_DIR, half_filename, 30))

    manifest = {
        "company": COMPANY_FULL,
        "short_name": COMPANY_SHORT,
        "stock_code": STOCK_CODE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "document_count": len(documents),
        "latest_quarter_title": latest_quarter["title"],
        "latest_quarter_announcement_date": latest_quarter["announcement_date"],
        "supplemental_half_year_count": sum(1 for item in documents if item["category"] == "补充_最新半年度报告"),
        "documents": documents,
        "validation": "已检查PDF文件头、实际页数、qpdf结构、公司名称或证券代码、首页与末页渲染，并完成ZIP CRC完整性测试。",
        "source": "巨潮资讯网官方披露PDF",
    }
    (NOTES_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (NOTES_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{item['sha256']}  {item['filename']}" for item in documents) + "\n",
        encoding="utf-8",
    )

    lines = [
        f"公司：{COMPANY_FULL}（{COMPANY_SHORT}，{STOCK_CODE}.SZ）",
        "资料来源：巨潮资讯网官方披露PDF",
        f"文件总数：{len(documents)}份",
        "",
        "收录范围：",
        "- 2020—2025年完整年度报告，共6份；",
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
        lines.append(f"   官方来源：{item['source_url']}")
    lines.extend(
        [
            "",
            "校验说明：",
            "- 排除年度报告摘要，仅收录完整年度报告；",
            "- 已检查PDF文件头、页数、结构、公司名称/证券代码及首页和末页可渲染性；",
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
        "latest_quarter_title": latest_quarter["title"],
        "supplemental_half_year_count": sum(1 for item in documents if item["category"] == "补充_最新半年度报告"),
        "documents": documents,
    }
    RESULT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PACKAGE_COMPLETE", json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    build_package()
