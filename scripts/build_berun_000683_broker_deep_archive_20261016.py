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

CODE = "000683"
CURRENT_COMPANY = "博源化工"
CURRENT_FULL_COMPANY = "内蒙古博源化工股份有限公司"
HISTORICAL_COMPANY = "远兴能源"
HISTORICAL_FULL_COMPANY = "内蒙古远兴能源股份有限公司"
AS_OF_DATE = "2026-10-16"
BJ = timezone(timedelta(hours=8))

ROOT = Path.cwd()
WORK_ROOT = ROOT / "_build_berun_000683_broker"
PACKAGE_ROOT = WORK_ROOT / f"{CURRENT_COMPANY}_{CODE}_券商深度报告_3份"
PDF_DIR = PACKAGE_ROOT / "01_完整原始PDF"
VERIFY_DIR = WORK_ROOT / "_verify"
ZIP_PATH = ROOT / "berun_chemical_000683_broker_deep_reports_3.zip"

REPORTS: list[dict[str, Any]] = [
    {
        "info_code": "AP202406201636709862",
        "report_date": "2024-06-20",
        "broker": "国信证券",
        "broker_full": "国信证券股份有限公司",
        "analysts": "杨林、张玮航",
        "title": "资源稀缺且优势突出的天然碱行业龙头",
        "filename_title": "资源稀缺且优势突出的天然碱行业龙头",
        "title_tokens": ["资源稀缺", "天然碱行业龙头"],
        "classification": "公司深度研究",
        "rating": "优于大市（平台同时标注增持）",
        "expected_pages": 53,
    },
    {
        "info_code": "AP202201121539930185",
        "report_date": "2022-01-12",
        "broker": "开源证券",
        "broker_full": "开源证券股份有限公司",
        "analysts": "金益腾、张晓锋、毕挥",
        "title": "公司首次覆盖报告：天然碱稀缺龙头，大型天然碱项目将拔地而起",
        "filename_title": "天然碱稀缺龙头，大型天然碱项目将拔地而起",
        "title_tokens": ["天然碱稀缺龙头", "大型天然碱项目"],
        "classification": "公司首次覆盖报告",
        "rating": "买入",
        "expected_pages": 30,
    },
    {
        "info_code": "AP202009021406244294",
        "report_date": "2020-09-02",
        "broker": "信达证券",
        "broker_full": "信达证券股份有限公司",
        "analysts": "张燕生、洪英东",
        "title": "深度报告：800万吨天然碱矿大发现，纯碱十年新征程正起航！",
        "filename_title": "800万吨天然碱矿大发现，纯碱十年新征程正起航",
        "title_tokens": ["800万吨天然碱矿", "纯碱十年新征程"],
        "classification": "公司深度报告",
        "rating": "买入",
        "expected_pages": 29,
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


def request_with_retry(session: requests.Session, url: str, *, timeout: int = 120) -> requests.Response:
    last_error: Exception | None = None
    headers = {
        **HEADERS,
        "Accept": "application/pdf,*/*;q=0.8",
        "Referer": "https://data.eastmoney.com/report/stock.jshtml",
    }
    for attempt in range(1, 6):
        try:
            response = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            log("HTTP", attempt, response.status_code, response.headers.get("content-type"), len(response.content), response.url)
            if response.status_code == 200 and response.content.startswith(b"%PDF-") and len(response.content) > 50_000:
                return response
            last_error = RuntimeError(
                f"Unexpected response: status={response.status_code}, content_type={response.headers.get('content-type')}, bytes={len(response.content)}"
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(min(2**attempt, 12))
    raise RuntimeError(f"Failed to download {url}: {last_error!r}")


def query_metadata(session: requests.Session) -> dict[str, dict[str, Any]]:
    by_code: dict[str, dict[str, Any]] = {}
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
            headers={
                **HEADERS,
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://data.eastmoney.com/report/stock.jshtml",
            },
            timeout=90,
        )
        response.raise_for_status()
        rows = response.json().get("data") or []
        log("METADATA_PAGE", page_no, "COUNT", len(rows))
        for row in rows:
            info_code = str(row.get("infoCode") or "")
            if info_code:
                by_code[info_code] = row
        if not rows:
            break
    return by_code


def extract_opening_text(path: Path, pages: int) -> str:
    result = subprocess.run(
        ["pdftotext", "-f", "1", "-l", str(min(8, pages)), "-enc", "UTF-8", str(path), "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pdftotext failed for {path}: {result.stderr[-1000:]}")
    return result.stdout


def render_selected_pages(path: Path, page_count: int) -> tuple[list[int], list[str]]:
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    selected = sorted(set([1, (page_count + 1) // 2, page_count]))
    rendered: list[str] = []
    for page_no in selected:
        prefix = VERIFY_DIR / f"{path.stem}_p{page_no}"
        result = subprocess.run(
            ["pdftoppm", "-f", str(page_no), "-l", str(page_no), "-singlefile", "-png", "-r", "120", str(path), str(prefix)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Render failed for {path}, page {page_no}: {result.stderr[-1000:]}")
        image_path = prefix.with_suffix(".png")
        data = image_path.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 10_000:
            raise RuntimeError(f"Invalid render output: {image_path}")
        rendered.append(str(image_path))
    return selected, rendered


def validate_pdf(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    data = path.read_bytes()
    if not data.startswith(b"%PDF-") or len(data) < 50_000:
        raise RuntimeError(f"Invalid PDF: {path}, bytes={len(data)}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages != report["expected_pages"]:
        raise RuntimeError(f"Unexpected page count for {path}: expected {report['expected_pages']}, got {pages}")

    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, check=False)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf validation failed for {path}: {(qpdf.stdout + qpdf.stderr)[-2000:]}")

    text = extract_opening_text(path, pages)
    compact = re.sub(r"\s+", "", text)
    identity_verified = any(
        token in compact
        for token in (
            CURRENT_COMPANY,
            CURRENT_FULL_COMPANY,
            HISTORICAL_COMPANY,
            HISTORICAL_FULL_COMPANY,
            CODE,
        )
    )
    broker_verified = report["broker"] in compact or report["broker_full"] in compact
    title_verified = any(token.replace(" ", "") in compact for token in report["title_tokens"])
    if not identity_verified:
        raise RuntimeError(f"Company identity check failed for {path}")
    if not broker_verified:
        raise RuntimeError(f"Broker identity check failed for {path}")
    if not title_verified:
        raise RuntimeError(f"Title check failed for {path}")

    rendered_pages, render_files = render_selected_pages(path, pages)
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
        f"{CURRENT_COMPANY}（{CODE}，历史简称：{HISTORICAL_COMPANY}）券商深度报告资料包",
        "",
        f"检索与核验截止日期：{AS_OF_DATE}",
        "",
        "收录原则：",
        "1. 仅收录完整公司深度、首次覆盖或系统性公司研究报告。",
        "2. 排除财报点评、季报点评、事件快评、行业周报、网页摘要和残缺预览版。",
        "3. 公司在这些报告发布时使用证券简称“远兴能源”，证券代码始终为000683；现简称为“博源化工”。",
        "4. 每份PDF均核验实际页数、公司名称或证券代码、券商署名、标题，并渲染首页/中间页/末页进行检查。",
        "5. PDF来源为东方财富公开研报镜像；版权归原券商及相关权利人所有，仅供研究学习。",
        "",
        "文件清单：",
    ]
    for idx, row in enumerate(records, 1):
        lines.extend(
            [
                f"{idx}. {row['broker']}，{row['report_date']}",
                f"   标题：{row['title']}",
                f"   类型：{row['classification']}；评级：{row['rating']}",
                f"   分析师：{row['analysts']}",
                f"   页数：{row['pages']}；大小：{row['bytes']}字节",
                f"   文件：{row['relative_path']}",
                f"   来源：{row['source_url']}",
                f"   SHA-256：{row['sha256']}",
                "",
            ]
        )
    (PACKAGE_ROOT / "README.txt").write_text("\n".join(lines), encoding="utf-8")

    fields = [
        "report_date",
        "broker",
        "broker_full",
        "analysts",
        "title",
        "classification",
        "rating",
        "info_code",
        "pages",
        "bytes",
        "sha256",
        "relative_path",
        "source_url",
        "metadata_page",
        "identity_verified",
        "broker_verified",
        "title_verified",
    ]
    with (PACKAGE_ROOT / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "current_company": CURRENT_COMPANY,
        "historical_company": HISTORICAL_COMPANY,
        "stock_code": CODE,
        "as_of_date": AS_OF_DATE,
        "generated_at": datetime.now(tz=BJ).isoformat(),
        "selection_standard": "完整公司深度/首次覆盖/系统性公司研究PDF；排除短篇点评、摘要和残缺预览",
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
    PACKAGE_ROOT.mkdir(parents=True)
    PDF_DIR.mkdir(parents=True)

    session = requests.Session()
    session.trust_env = False
    metadata = query_metadata(session)
    records: list[dict[str, Any]] = []

    for report in REPORTS:
        row = metadata.get(report["info_code"])
        if not row:
            raise RuntimeError(f"Metadata row missing: {report['info_code']}")
        if str(row.get("stockCode") or "") != CODE:
            raise RuntimeError(f"Stock code mismatch: {row}")
        if str(row.get("stockName") or "") not in {CURRENT_COMPANY, HISTORICAL_COMPANY}:
            raise RuntimeError(f"Company metadata mismatch: {row}")
        if report["broker"] not in str(row.get("orgSName") or row.get("orgName") or ""):
            raise RuntimeError(f"Broker metadata mismatch: {row}")
        if int(row.get("attachPages") or 0) != report["expected_pages"]:
            raise RuntimeError(f"Page metadata mismatch: {row}")

        source_url = f"https://pdf.dfcfw.com/pdf/H3_{report['info_code']}_1.pdf"
        filename = (
            f"{report['report_date'].replace('-', '')}_{report['broker']}_"
            f"{report['filename_title']}_{report['expected_pages']}页.pdf"
        )
        path = PDF_DIR / filename
        response = request_with_retry(session, source_url)
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
            "eastmoney_stock_name": row.get("stockName"),
        }
        log("VALIDATED", json.dumps(record, ensure_ascii=False))
        records.append(record)
        time.sleep(0.5)

    if len(records) != 3:
        raise RuntimeError(f"Expected 3 complete reports, got {len(records)}")
    if len({row["sha256"] for row in records}) != 3:
        raise RuntimeError("Duplicate PDF files detected")

    write_support_files(records)
    build_zip()


if __name__ == "__main__":
    main()
