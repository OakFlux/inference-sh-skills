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

COMPANY = "首航新能"
FULL_COMPANY = "深圳市首航新能源股份有限公司"
CODE = "301658"
AS_OF_DATE = "2026-10-15"
BJ = timezone(timedelta(hours=8))

ROOT = Path.cwd()
WORK_ROOT = ROOT / "_build_shouhang_301658_broker"
PACKAGE_NAME = f"{COMPANY}_{CODE}_券商研究报告_2份"
PACKAGE_ROOT = WORK_ROOT / PACKAGE_NAME
PDF_DIR = PACKAGE_ROOT / "01_完整原始PDF"
VERIFY_DIR = WORK_ROOT / "_verify"
ZIP_PATH = ROOT / "shouhang_xinneng_301658_broker_reports_2.zip"

REPORTS: list[dict[str, Any]] = [
    {
        "info_code": "AP202509051739226214",
        "report_date": "2025-09-05",
        "broker": "爱建证券",
        "broker_full": "爱建证券有限责任公司",
        "analysts": "朱攀",
        "title": "首航新能首次覆盖：布局工商储+大储，受益澳洲户储增长",
        "classification": "公司首次覆盖报告",
        "rating": "增持",
        "expected_pages": 6,
    },
    {
        "info_code": "AP202503161644423188",
        "report_date": "2025-03-16",
        "broker": "华金证券",
        "broker_full": "华金证券股份有限公司",
        "analysts": "李蕙",
        "title": "新股覆盖研究：首航新能",
        "classification": "新股覆盖研究",
        "rating": "未评级",
        "expected_pages": 11,
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def log(*args: Any) -> None:
    print(*args, flush=True)


def safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    return re.sub(r"\s+", " ", value).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_metadata(session: requests.Session) -> dict[str, dict[str, Any]]:
    params = {
        "pageSize": "200",
        "pageNo": "1",
        "code": CODE,
        "qType": "0",
        "industryCode": "*",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": "2024-01-01",
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
    rows = response.json().get("data") or []
    log("METADATA_COUNT", len(rows))
    return {str(row.get("infoCode") or ""): row for row in rows}


def get_pdf(session: requests.Session, url: str) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = session.get(
                url,
                headers={**HEADERS, "Accept": "application/pdf,*/*;q=0.8", "Referer": "https://data.eastmoney.com/report/stock.jshtml"},
                timeout=120,
                allow_redirects=True,
            )
            log("HTTP", attempt, response.status_code, response.headers.get("content-type"), len(response.content), response.url)
            if response.status_code == 200 and response.content.startswith(b"%PDF-") and len(response.content) > 50_000:
                return response
            last_error = RuntimeError(f"Unexpected response: {response.status_code}, {response.headers.get('content-type')}, {len(response.content)} bytes")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(min(2**attempt, 10))
    raise RuntimeError(f"Failed to download {url}: {last_error!r}")


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


def render_selected_pages(path: Path, pages: int) -> tuple[list[int], list[str]]:
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    selected = sorted(set([1, (pages + 1) // 2, pages]))
    outputs: list[str] = []
    for page in selected:
        prefix = VERIFY_DIR / f"{path.stem}_p{page}"
        result = subprocess.run(
            ["pdftoppm", "-f", str(page), "-l", str(page), "-singlefile", "-png", "-r", "130", str(path), str(prefix)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Render failed for {path}, page {page}: {result.stderr[-1000:]}")
        image_path = prefix.with_suffix(".png")
        data = image_path.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 10_000:
            raise RuntimeError(f"Invalid rendered page: {image_path}")
        outputs.append(str(image_path))
    return selected, outputs


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
        raise RuntimeError(f"qpdf check failed for {path}: {(qpdf.stdout + qpdf.stderr)[-2000:]}")

    text = extract_text(path, pages)
    compact = re.sub(r"\s+", "", text)
    identity_verified = any(token in compact for token in (COMPANY, FULL_COMPANY, CODE))
    broker_verified = report["broker"] in compact or report["broker_full"] in compact
    title_parts = [part for part in re.split(r"[：，,+/（）()\s]+", report["title"]) if len(part) >= 4]
    title_hits = sum(part in compact for part in title_parts)
    title_verified = title_hits >= 1
    if not identity_verified:
        raise RuntimeError(f"Company identity check failed for {path}")
    if not broker_verified:
        raise RuntimeError(f"Broker identity check failed for {path}")
    if not title_verified:
        raise RuntimeError(f"Title check failed for {path}: parts={title_parts}, hits={title_hits}")

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
        f"{COMPANY}（{CODE}）券商研究报告资料包",
        "",
        f"检索与核验截止日期：{AS_OF_DATE}",
        "",
        "收录说明：",
        "1. 公开研报数据库中可直接取得并完整验证的公司覆盖研究共2份。",
        "2. 爱建证券报告为6页首次覆盖；华金证券报告为11页新股覆盖研究。二者均非20页以上的传统长篇公司深度报告，文件类型已如实标注。",
        "3. 未使用季度点评、事件快评、网页摘要或残缺预览版凑数。",
        "4. 每份PDF均核验结构、页数、公司与券商身份，并渲染首页、中间页和末页检查。",
        "5. 报告版权归原券商及相关权利人所有，仅供研究学习。",
        "",
        "文件清单：",
    ]
    for idx, row in enumerate(records, 1):
        lines.extend([
            f"{idx}. {row['broker']}，{row['report_date']}",
            f"   标题：{row['title']}",
            f"   类型：{row['classification']}；评级：{row['rating']}",
            f"   研究员：{row['analysts']}",
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
        "identity_verified", "broker_verified", "title_verified",
    ]
    with (PACKAGE_ROOT / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "company": COMPANY,
        "stock_code": CODE,
        "as_of_date": AS_OF_DATE,
        "generated_at": datetime.now(tz=BJ).isoformat(),
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
    metadata_by_code = get_metadata(session)
    records: list[dict[str, Any]] = []

    for report in REPORTS:
        metadata = metadata_by_code.get(report["info_code"])
        if not metadata:
            raise RuntimeError(f"Missing metadata for {report['info_code']}")
        if str(metadata.get("stockCode") or "") != CODE or COMPANY not in str(metadata.get("stockName") or ""):
            raise RuntimeError(f"Company metadata mismatch: {metadata}")
        broker_text = str(metadata.get("orgSName") or "") + " " + str(metadata.get("orgName") or "")
        if report["broker"] not in broker_text and report["broker_full"] not in broker_text:
            raise RuntimeError(f"Broker metadata mismatch: {metadata}")
        if str(metadata.get("title") or "").strip() != report["title"]:
            raise RuntimeError(f"Title metadata mismatch: {metadata}")

        source_url = f"https://pdf.dfcfw.com/pdf/H3_{report['info_code']}_1.pdf"
        filename = safe_name(f"{report['report_date'].replace('-', '')}_{report['broker']}_{report['title']}_{report['expected_pages']}页.pdf")
        path = PDF_DIR / filename
        response = get_pdf(session, source_url)
        path.write_bytes(response.content)
        validation = validate_pdf(path, report)
        record = {
            **report,
            **validation,
            "source_url": source_url,
            "metadata_page": f"https://data.eastmoney.com/report/info/{report['info_code']}.html",
            "relative_path": str(path.relative_to(PACKAGE_ROOT)),
            "eastmoney_attach_pages": metadata.get("attachPages"),
            "eastmoney_attach_size_kb": metadata.get("attachSize"),
        }
        log("VALIDATED", json.dumps(record, ensure_ascii=False))
        records.append(record)
        time.sleep(0.5)

    if len(records) != 2:
        raise RuntimeError(f"Expected 2 reports, got {len(records)}")
    if len({row["sha256"] for row in records}) != 2:
        raise RuntimeError("Duplicate report PDFs detected")

    write_support_files(records)
    build_zip()


if __name__ == "__main__":
    main()
