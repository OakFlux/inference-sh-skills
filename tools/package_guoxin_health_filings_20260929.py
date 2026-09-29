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

COMPANY = "国新健康"
CODE = "000503"
ORG_ID = "gssz0000503"
TODAY = "2026-09-29"
ROOT = Path("国新健康_000503_2020-2025年报及最新季报")
ANNUAL_DIR = ROOT / "01_年度报告"
QUARTER_DIR = ROOT / "02_最新季报"
SUPPLEMENT_DIR = ROOT / "03_补充_最新半年度报告"
NOTES_DIR = ROOT / "04_资料说明"
TMP_DIR = Path("_tmp_guoxin_health_filings")
PREVIEW_DIR = Path("_previews_guoxin_health_filings")
ZIP_PATH = Path("国新健康_000503_2020-2025年报及最新季报.zip")
RESULT_JSON = Path("guoxin_health_filings_result.json")

CNINFO_BASE = "https://www.cninfo.com.cn"
STATIC_BASE = "https://static.cninfo.com.cn/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Referer": f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={CODE}&orgId={ORG_ID}",
    "X-Requested-With": "XMLHttpRequest",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def reset_outputs() -> None:
    for path in (ROOT, TMP_DIR, PREVIEW_DIR):
        if path.exists():
            shutil.rmtree(path)
    for path in (ZIP_PATH, RESULT_JSON):
        if path.exists():
            path.unlink()
    for path in (ANNUAL_DIR, QUARTER_DIR, SUPPLEMENT_DIR, NOTES_DIR, TMP_DIR, PREVIEW_DIR):
        path.mkdir(parents=True, exist_ok=True)


def query_announcements(session: requests.Session, category: str) -> list[dict[str, Any]]:
    data = {
        "pageNum": "1",
        "pageSize": "100",
        "column": "szse",
        "tabName": "fulltext",
        "plate": "sz",
        "stock": f"{CODE},{ORG_ID}",
        "searchkey": "",
        "secid": "",
        "category": category,
        "trade": "",
        "seDate": f"2020-01-01~{TODAY}",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    response = session.post(
        CNINFO_BASE + "/new/hisAnnouncement/query",
        data=data,
        timeout=90,
    )
    print("QUERY", category, response.status_code, len(response.content), flush=True)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("announcements") or []
    print("QUERY_ROWS", category, len(rows), flush=True)
    return rows


def clean_title(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()


def select_exact(rows: list[dict[str, Any]], title: str) -> dict[str, Any]:
    exact = [row for row in rows if clean_title(str(row.get("announcementTitle", ""))) == title]
    if not exact:
        raise RuntimeError(f"未找到公告：{title}")
    exact.sort(key=lambda row: int(row.get("announcementTime") or 0), reverse=True)
    return exact[0]


def select_latest_quarter(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        title = clean_title(str(row.get("announcementTitle", "")))
        if "季度报告" not in title:
            continue
        if any(token in title for token in ("摘要", "正文")):
            continue
        candidates.append(row)
    if not candidates:
        raise RuntimeError("未找到最新季度报告")
    candidates.sort(key=lambda row: int(row.get("announcementTime") or 0), reverse=True)
    return candidates[0]


def announcement_url(row: dict[str, Any]) -> str:
    adjunct = str(row.get("adjunctUrl") or "").lstrip("/")
    if not adjunct:
        raise RuntimeError(f"公告缺少附件地址：{row}")
    return STATIC_BASE + adjunct


def download_pdf(session: requests.Session, row: dict[str, Any], destination: Path) -> str:
    url = announcement_url(row)
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, 5):
        part = destination.with_suffix(destination.suffix + ".part")
        try:
            if part.exists():
                part.unlink()
            with session.get(
                url,
                headers={
                    **HEADERS,
                    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
                },
                stream=True,
                timeout=(30, 180),
                allow_redirects=True,
            ) as response:
                print(
                    "DOWNLOAD_RESPONSE",
                    clean_title(str(row.get("announcementTitle", ""))),
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
            if part.stat().st_size < 40_000:
                raise RuntimeError(f"PDF文件过小：{part.stat().st_size}")
            with part.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise RuntimeError("下载内容不是PDF")
            part.replace(destination)
            return url
        except Exception as exc:
            last_error = exc
            print("DOWNLOAD_RETRY", destination.name, attempt, repr(exc), flush=True)
            time.sleep(attempt * 2)
    raise RuntimeError(f"无法下载{destination.name}：{last_error!r}")


def validate_pdf(path: Path, title: str) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 3:
        raise RuntimeError(f"{path.name}页数异常：{pages}")

    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf校验失败：{path.name}: {qpdf.stderr[-1000:]}")

    text_result = subprocess.run(
        ["pdftotext", "-f", "1", "-l", str(min(pages, 5)), str(path), "-"],
        capture_output=True,
        timeout=90,
    )
    extracted = text_result.stdout.decode("utf-8", errors="ignore") if text_result.stdout else ""
    compact = re.sub(r"\s+", "", extracted)
    identity_match = COMPANY in compact or CODE in compact
    if len(compact) > 300 and not identity_match:
        raise RuntimeError(f"报告首页未识别到{COMPANY}或{CODE}：{path.name}")

    preview_base = PREVIEW_DIR / path.stem
    subprocess.run(
        ["pdftoppm", "-f", "1", "-singlefile", "-png", "-r", "120", str(path), str(preview_base)],
        check=True,
        capture_output=True,
        timeout=180,
    )
    preview = preview_base.with_suffix(".png")
    if not preview.exists() or preview.stat().st_size < 8_000:
        raise RuntimeError(f"首页渲染失败：{path.name}")

    result = {
        "title": title,
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "identity_text_match": identity_match,
        "first_page_preview": str(preview),
    }
    print("VALIDATED", path.name, json.dumps(result, ensure_ascii=False), flush=True)
    return result


def build_record(row: dict[str, Any], path: Path, category: str, source_url: str) -> dict[str, Any]:
    title = clean_title(str(row.get("announcementTitle", "")))
    validation = validate_pdf(path, title)
    return {
        "category": category,
        "title": title,
        "announcement_id": row.get("announcementId"),
        "announcement_time_ms": row.get("announcementTime"),
        "adjunct_size_kb": row.get("adjunctSize"),
        "filename": str(path.relative_to(ROOT)),
        "source_url": source_url,
        **validation,
    }


def build_package() -> None:
    reset_outputs()
    session = requests.Session()
    session.headers.update(HEADERS)

    annual_rows = query_announcements(session, "category_ndbg_szsh")
    quarter_rows = query_announcements(session, "category_yjdbg_szsh")
    half_rows = query_announcements(session, "category_bndbg_szsh")

    records: list[dict[str, Any]] = []
    for year in range(2020, 2026):
        title = f"{year}年年度报告"
        row = select_exact(annual_rows, title)
        filename = f"{year}_国新健康_{year}年年度报告.pdf"
        temp_path = TMP_DIR / filename
        source_url = download_pdf(session, row, temp_path)
        final_path = ANNUAL_DIR / filename
        shutil.move(str(temp_path), str(final_path))
        records.append(build_record(row, final_path, "年度报告", source_url))

    latest_quarter = select_latest_quarter(quarter_rows)
    quarter_title = clean_title(str(latest_quarter.get("announcementTitle", "")))
    quarter_filename = f"最新季报_国新健康_{quarter_title}.pdf"
    quarter_temp = TMP_DIR / quarter_filename
    quarter_url = download_pdf(session, latest_quarter, quarter_temp)
    quarter_final = QUARTER_DIR / quarter_filename
    shutil.move(str(quarter_temp), str(quarter_final))
    records.append(build_record(latest_quarter, quarter_final, "最新季度报告", quarter_url))

    supplemental: list[dict[str, Any]] = []
    try:
        half_candidates = []
        for row in half_rows:
            title = clean_title(str(row.get("announcementTitle", "")))
            if "半年度报告" in title and "摘要" not in title:
                half_candidates.append(row)
        if half_candidates:
            half_candidates.sort(key=lambda row: int(row.get("announcementTime") or 0), reverse=True)
            latest_half = half_candidates[0]
            half_title = clean_title(str(latest_half.get("announcementTitle", "")))
            half_filename = f"补充_国新健康_{half_title}.pdf"
            half_temp = TMP_DIR / half_filename
            half_url = download_pdf(session, latest_half, half_temp)
            half_final = SUPPLEMENT_DIR / half_filename
            shutil.move(str(half_temp), str(half_final))
            half_record = build_record(latest_half, half_final, "补充_最新半年度报告", half_url)
            records.append(half_record)
            supplemental.append(half_record)
    except Exception as exc:
        print("HALF_YEAR_WARNING", repr(exc), flush=True)

    records.sort(key=lambda item: item["filename"])
    manifest = {
        "company": COMPANY,
        "stock_code": CODE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_scope": "2020-2025年年度报告及最新季报",
        "latest_quarter_title": quarter_title,
        "supplemental_half_year_count": len(supplemental),
        "document_count": len(records),
        "documents": records,
        "source": "巨潮资讯网（深圳证券交易所法定信息披露平台）",
        "validation": "PDF文件头、页数、qpdf结构、公司名称/代码文本匹配及首页渲染均已检查。",
    }
    (NOTES_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (NOTES_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{item['sha256']}  {item['filename']}" for item in records) + "\n",
        encoding="utf-8",
    )

    lines = [
        f"公司：{COMPANY}（{CODE}.SZ）",
        "资料来源：巨潮资讯网官方公告PDF",
        "",
        "本次收录：",
        "- 2020年至2025年年度报告，共6份；",
        f"- 最新正式季度报告：{quarter_title}，共1份；",
    ]
    if supplemental:
        lines.append(f"- 补充收录更晚披露的{supplemental[0]['title']}，共1份。该文件不是季度报告，单独置于补充目录。")
    lines.extend(["", "文件明细："])
    for index, item in enumerate(records, start=1):
        lines.append(
            f"{index}. {item['title']} | {item['pages']}页 | {item['bytes'] / 1024 / 1024:.2f} MB | {item['filename']}"
        )
    lines.extend(
        [
            "",
            "校验说明：",
            "- 每份PDF已检查文件头、页数和qpdf结构；",
            "- 已检查首页文本中的公司名称或证券代码；",
            "- 已完成首页渲染；",
            "- SHA-256校验值见SHA256SUMS.txt，详细来源见manifest.json。",
        ]
    )
    (NOTES_DIR / "资料清单与来源说明.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.as_posix())
    with zipfile.ZipFile(ZIP_PATH) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP成员损坏：{bad}")

    result = {
        "zip_filename": ZIP_PATH.name,
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256(ZIP_PATH),
        "document_count": len(records),
        "latest_quarter_title": quarter_title,
        "supplemental_half_year_count": len(supplemental),
        "documents": records,
    }
    RESULT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PACKAGE_COMPLETE", json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    build_package()
