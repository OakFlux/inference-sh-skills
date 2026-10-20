from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

COMPANY = "海兰信"
FULL_COMPANY = "北京海兰信数据科技股份有限公司"
CODE = "300065"
AS_OF_DATE = "2026-10-20"
BJ = timezone(timedelta(hours=8))
ROOT = Path.cwd()
WORK_ROOT = ROOT / "_build_hailanxin_300065_broker"
PACKAGE_ROOT = WORK_ROOT / f"{COMPANY}_{CODE}_券商深度报告_3份"
PDF_DIR = PACKAGE_ROOT / "01_完整原始PDF"
VERIFY_DIR = WORK_ROOT / "_verify"
ZIP_PATH = ROOT / "hailanxin_300065_broker_deep_reports_3.zip"

REPORTS: list[dict[str, Any]] = [
    {
        "info_code": "AP202407151637921679",
        "report_date": "2024-07-15",
        "broker": "东吴证券",
        "broker_full": "东吴证券股份有限公司",
        "analysts": "苏立赞、许牧、高正泰",
        "title": "深度布局智能船舶，启航智慧海洋新蓝海",
        "filename_title": "深度布局智能船舶，启航智慧海洋新蓝海",
        "title_tokens": ["深度布局智能船舶", "启航智慧海洋新蓝海"],
        "classification": "公司深度研究",
        "rating": "增持",
        "expected_pages": 27,
    },
    {
        "info_code": "AP202209071578123195",
        "report_date": "2022-09-07",
        "broker": "中航证券",
        "broker_full": "中航证券有限公司",
        "analysts": "张超",
        "title": "军品UDC齐发力，海中娇兰可期盛放",
        "filename_title": "军品UDC齐发力，海中娇兰可期盛放",
        "title_tokens": ["军品UDC齐发力", "海中娇兰可期盛放"],
        "classification": "公司深度研究",
        "rating": "买入",
        "expected_pages": 30,
    },
    {
        "info_code": "AP202202211548310816",
        "report_date": "2022-02-21",
        "broker": "国元证券",
        "broker_full": "国元证券股份有限公司",
        "analysts": "耿军军",
        "title": "首次覆盖报告：热数据的东数海算，数字新基建加速落地",
        "filename_title": "热数据的东数海算，数字新基建加速落地",
        "title_tokens": ["热数据的东数海算", "数字新基建加速落地"],
        "classification": "首次覆盖报告",
        "rating": "买入",
        "expected_pages": 27,
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def log(*args: Any) -> None:
    print(*args, flush=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request_pdf(session: requests.Session, url: str) -> requests.Response:
    last_error: Exception | None = None
    headers = {
        **HEADERS,
        "Accept": "application/pdf,*/*;q=0.8",
        "Referer": "https://data.eastmoney.com/report/stock.jshtml",
    }
    for attempt in range(1, 6):
        try:
            response = session.get(url, headers=headers, timeout=120, allow_redirects=True)
            log("HTTP", attempt, response.status_code, response.headers.get("content-type"), len(response.content), response.url)
            if response.status_code == 200 and response.content.startswith(b"%PDF-") and len(response.content) > 50_000:
                return response
            last_error = RuntimeError(
                f"Unexpected response status={response.status_code}, type={response.headers.get('content-type')}, bytes={len(response.content)}"
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(min(2**attempt, 12))
    raise RuntimeError(f"Failed to download {url}: {last_error!r}")


def query_metadata(session: requests.Session) -> dict[str, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page_no in range(1, 4):
        params = {
            "pageSize": "100",
            "pageNo": str(page_no),
            "code": CODE,
            "qType": "0",
            "industryCode": "*",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": "2010-01-01",
            "endTime": AS_OF_DATE,
            "orgCode": "",
            "rcode": "",
            "fields": "",
        }
        response = session.get(
            "https://reportapi.eastmoney.com/report/list",
            params=params,
            headers={**HEADERS, "Accept": "application/json,text/plain,*/*", "Referer": "https://data.eastmoney.com/report/stock.jshtml"},
            timeout=90,
        )
        response.raise_for_status()
        page_rows = response.json().get("data") or []
        rows.extend(page_rows)
        log("METADATA_PAGE", page_no, "COUNT", len(page_rows))
        if len(page_rows) < 100:
            break
    return {str(row.get("infoCode") or ""): row for row in rows}


def extract_text(path: Path, pages: int) -> str:
    result = subprocess.run(
        ["pdftotext", "-f", "1", "-l", str(min(6, pages)), "-enc", "UTF-8", str(path), "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pdftotext failed for {path}: {result.stderr[-1000:]}")
    return result.stdout


def render_pages(path: Path, pages: int) -> tuple[list[int], list[str]]:
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    selected = sorted(set([1, (pages + 1) // 2, pages]))
    rendered: list[str] = []
    for page in selected:
        prefix = VERIFY_DIR / f"{path.stem}_p{page}"
        result = subprocess.run(
            ["pdftoppm", "-f", str(page), "-l", str(page), "-singlefile", "-png", "-r", "120", str(path), str(prefix)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Render failed for {path} page {page}: {result.stderr[-1000:]}")
        image = prefix.with_suffix(".png")
        data = image.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 10_000:
            raise RuntimeError(f"Invalid render output: {image}")
        rendered.append(str(image))
    return selected, rendered


def validate_pdf(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    data = path.read_bytes()
    if not data.startswith(b"%PDF-"):
        raise RuntimeError(f"Not a PDF: {path}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages != report["expected_pages"]:
        raise RuntimeError(f"Unexpected page count for {path}: expected {report['expected_pages']}, got {pages}")

    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, check=False)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf validation failed for {path}: {(qpdf.stdout + qpdf.stderr)[-2000:]}")

    text = extract_text(path, pages)
    compact = re.sub(r"\s+", "", text)
    identity_verified = any(token in compact for token in (COMPANY, FULL_COMPANY, CODE))
    broker_verified = report["broker"] in compact or report["broker_full"] in compact
    title_verified = any(token.replace(" ", "") in compact for token in report["title_tokens"])
    if not identity_verified:
        raise RuntimeError(f"Company identity not found in opening pages: {path}")
    if not broker_verified:
        raise RuntimeError(f"Broker identity not found in opening pages: {path}")
    if not title_verified:
        raise RuntimeError(f"Title keywords not found in opening pages: {path}")

    rendered_pages, render_files = render_pages(path, pages)
    return {
        "pages": pages,
        "bytes": len(data),
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "identity_verified": identity_verified,
        "broker_verified": broker_verified,
        "title_verified": title_verified,
        "rendered_pages": rendered_pages,
        "render_files": render_files,
    }


def write_support_files(records: list[dict[str, Any]]) -> None:
    lines = [
        f"{COMPANY}（{CODE}）券商深度报告资料包",
        "",
        f"检索与核验截止日期：{AS_OF_DATE}",
        "",
        "收录标准：",
        "1. 优先公司深度、首次覆盖或系统性公司研究，不使用季报点评、事件快评、行业周报或网页摘要凑数。",
        "2. 仅收录可取得的完整原始排版PDF。",
        "3. 每份PDF均核验页数、公司身份、券商署名、标题关键词、PDF结构，并渲染首页/中间页/末页检查。",
        "4. 报告版权归原券商及相关权利人所有，仅供研究学习。",
        "",
        "文件清单：",
    ]
    for i, row in enumerate(records, 1):
        lines.extend([
            f"{i}. {row['broker']}，{row['report_date']}",
            f"   标题：{row['title']}",
            f"   类型：{row['classification']}；评级：{row['rating']}",
            f"   分析师：{row['analysts']}",
            f"   页数：{row['pages']}；大小：{row['bytes']}字节",
            f"   文件：{row['relative_path']}",
            f"   来源：{row['source_url']}",
            f"   SHA-256：{row['sha256']}",
            "",
        ])
    (PACKAGE_ROOT / "README.txt").write_text("\n".join(lines), encoding="utf-8")

    fields = [
        "report_date", "broker", "broker_full", "analysts", "title", "classification", "rating",
        "info_code", "pages", "bytes", "sha256", "relative_path", "source_url", "metadata_page",
        "identity_verified", "broker_verified", "title_verified"
    ]
    with (PACKAGE_ROOT / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "company": COMPANY,
        "company_full_name": FULL_COMPANY,
        "stock_code": CODE,
        "as_of_date": AS_OF_DATE,
        "generated_at": datetime.now(tz=BJ).isoformat(),
        "selection_standard": "完整公司深度、首次覆盖或系统性公司研究优先；排除短篇点评和残缺预览",
        "records": records,
    }
    (PACKAGE_ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (PACKAGE_ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{row['sha256']}  {row['relative_path']}" for row in records) + "\n",
        encoding="utf-8",
    )


def build_zip() -> None:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(PACKAGE_ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(Path(PACKAGE_ROOT.name) / path.relative_to(PACKAGE_ROOT)))
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC validation failed at {bad}")
    log("FINAL_ZIP", ZIP_PATH.name, "bytes", ZIP_PATH.stat().st_size, "sha256", sha256_file(ZIP_PATH))


def main() -> None:
    if WORK_ROOT.exists():
        shutil.rmtree(WORK_ROOT)
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.trust_env = False
    metadata = query_metadata(session)
    records: list[dict[str, Any]] = []

    for report in REPORTS:
        row = metadata.get(report["info_code"])
        if not row:
            raise RuntimeError(f"Metadata row missing: {report['info_code']}")
        if str(row.get("stockCode") or "") != CODE or str(row.get("stockName") or "") != COMPANY:
            raise RuntimeError(f"Company metadata mismatch: {row}")
        org = str(row.get("orgSName") or row.get("orgName") or "")
        if report["broker"] not in org:
            raise RuntimeError(f"Broker metadata mismatch: {row}")
        if int(row.get("attachPages") or 0) != report["expected_pages"]:
            raise RuntimeError(f"Page metadata mismatch: {row}")

        source_url = f"https://pdf.dfcfw.com/pdf/H3_{report['info_code']}_1.pdf"
        filename = f"{report['report_date'].replace('-', '')}_{report['broker']}_{report['filename_title']}_{report['expected_pages']}页.pdf"
        path = PDF_DIR / filename
        response = request_pdf(session, source_url)
        path.write_bytes(response.content)
        validation = validate_pdf(path, report)
        record = {
            **report,
            **validation,
            "source_url": source_url,
            "metadata_page": f"https://data.eastmoney.com/report/info/{report['info_code']}.html",
            "relative_path": str(path.relative_to(PACKAGE_ROOT)),
            "eastmoney_title": row.get("title"),
            "eastmoney_publish_date": row.get("publishDate"),
            "eastmoney_attach_pages": row.get("attachPages"),
            "eastmoney_attach_size_kb": row.get("attachSize"),
        }
        log("VALIDATED", json.dumps(record, ensure_ascii=False))
        records.append(record)
        time.sleep(0.5)

    if len(records) != 3:
        raise RuntimeError(f"Expected 3 reports, got {len(records)}")
    if len({row["sha256"] for row in records}) != 3:
        raise RuntimeError("Duplicate report PDFs detected")

    write_support_files(records)
    build_zip()


if __name__ == "__main__":
    main()
