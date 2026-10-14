from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

COMPANY = "亚香股份"
CODE = "301220"
AS_OF_DATE = "2026-10-14"
BJ = timezone(timedelta(hours=8))
WORK_ROOT = Path("_build_yaxiang_301220_broker_deep")
PACKAGE_ROOT = WORK_ROOT / f"{COMPANY}_{CODE}_券商深度报告_2份"
PDF_DIR = PACKAGE_ROOT / "01_完整原始PDF"
VERIFY_DIR = WORK_ROOT / "_verify"
ZIP_PATH = Path(f"{COMPANY}_{CODE}_券商深度报告_2份.zip")

REPORTS: list[dict[str, Any]] = [
    {
        "report_date": "2024-11-15",
        "publish_date": "2024-11-15",
        "broker": "民生证券",
        "broker_full": "民生证券股份有限公司",
        "analysts": "刘海荣、李金凤",
        "title": "深度报告：全球香精香料细分龙头，泰国工厂助力业绩迈入新台阶",
        "short_title": "全球香精香料细分龙头_泰国工厂助力业绩迈入新台阶",
        "classification": "公司深度报告（首次覆盖）",
        "rating": "推荐",
        "info_code": "AP202411151640909508",
        "expected_pages": 43,
    },
    {
        "report_date": "2023-08-13",
        "publish_date": "2023-08-14",
        "broker": "东吴证券",
        "broker_full": "东吴证券股份有限公司",
        "analysts": "陈淑娴、陈李、郭晶晶、何亦桢",
        "title": "立足香料中高端市场，泰国项目成长可期",
        "short_title": "立足香料中高端市场_泰国项目成长可期",
        "classification": "公司深度研究（首次覆盖）",
        "rating": "买入",
        "info_code": "AP202308131594342630",
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
    params = {
        "pageSize": "200",
        "pageNo": "1",
        "code": CODE,
        "qType": "0",
        "industryCode": "*",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": "2022-01-01",
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
    by_code = {str(row.get("infoCode") or ""): row for row in rows}
    log("METADATA_ROWS", len(rows))
    return by_code


def extract_text(path: Path, pages: int) -> str:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        return ""
    result = subprocess.run(
        [pdftotext, "-f", "1", "-l", str(min(4, pages)), "-enc", "UTF-8", str(path), "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


def render_pages(path: Path, pages: int, stem: str) -> list[str]:
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise RuntimeError("pdftoppm is unavailable")
    selected = sorted(set([1, (pages + 1) // 2, pages]))
    rendered: list[str] = []
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    for page in selected:
        output_prefix = VERIFY_DIR / f"{stem}_p{page}"
        subprocess.run(
            [pdftoppm, "-f", str(page), "-l", str(page), "-singlefile", "-png", "-r", "130", str(path), str(output_prefix)],
            check=True,
            capture_output=True,
        )
        image_path = output_prefix.with_suffix(".png")
        data = image_path.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 10_000:
            raise RuntimeError(f"Rendered page validation failed: {image_path}")
        rendered.append(str(image_path))
    return rendered


def validate_pdf(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    data = path.read_bytes()
    if not data.startswith(b"%PDF-"):
        raise RuntimeError(f"Not a PDF: {path}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages != report["expected_pages"]:
        raise RuntimeError(f"Unexpected page count for {path}: expected {report['expected_pages']}, got {pages}")

    qpdf_result = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, check=False)
    if qpdf_result.returncode not in (0, 3):
        raise RuntimeError(f"qpdf validation failed for {path}: {(qpdf_result.stdout + qpdf_result.stderr)[-2000:]}")

    text = extract_text(path, pages)
    identity_verified = COMPANY in text or CODE in text
    broker_verified = report["broker"] in text or report["broker_full"] in text
    title_tokens = [token for token in report["short_title"].split("_") if len(token) >= 4]
    title_verified = any(token in text for token in title_tokens)
    if not identity_verified:
        raise RuntimeError(f"Company identity not found in extracted opening pages: {path}")
    if not broker_verified:
        raise RuntimeError(f"Broker identity not found in extracted opening pages: {path}")

    rendered = render_pages(path, pages, path.stem)
    return {
        "pages": pages,
        "bytes": len(data),
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf_result.returncode,
        "identity_verified": identity_verified,
        "broker_verified": broker_verified,
        "title_verified": title_verified,
        "rendered_pages": [1, (pages + 1) // 2, pages],
        "render_files": rendered,
    }


def write_metadata(records: list[dict[str, Any]]) -> None:
    readme = [
        f"{COMPANY}（{CODE}）券商深度报告资料包",
        "",
        f"检索与核验截止日期：{AS_OF_DATE}",
        "",
        "收录原则：",
        "1. 优先公司深度报告或首次覆盖报告，不使用短篇财报点评、事件快评或网页摘要凑数。",
        "2. 本资料包收录2份可公开直接取得、可验证为完整原始排版的券商PDF。",
        "3. 每份PDF均核验实际页数、公司名称或股票代码、券商署名、PDF结构，并渲染首页/中间页/末页进行检查。",
        "4. 文件来源为东方财富公开研报PDF镜像；报告版权归原券商及相关权利人所有，仅供研究学习。",
        "",
        "文件清单：",
    ]
    for idx, row in enumerate(records, 1):
        readme.extend(
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
    (PACKAGE_ROOT / "README.txt").write_text("\n".join(readme), encoding="utf-8")

    fields = [
        "report_date",
        "publish_date",
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
        "identity_verified",
        "broker_verified",
        "title_verified",
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
        "selection_standard": "完整公司深度/首次覆盖PDF优先；排除短篇点评、摘要和预览版",
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
            raise RuntimeError(f"Eastmoney metadata row missing: {report['info_code']}")
        if str(row.get("stockCode")) != CODE or str(row.get("stockName")) != COMPANY:
            raise RuntimeError(f"Company metadata mismatch: {row}")
        if report["broker"] not in str(row.get("orgSName") or row.get("orgName") or ""):
            raise RuntimeError(f"Broker metadata mismatch: {row}")
        if report["short_title"].split("_")[0] not in str(row.get("title") or ""):
            raise RuntimeError(f"Title metadata mismatch: {row}")

        url = f"https://pdf.dfcfw.com/pdf/H3_{report['info_code']}_1.pdf"
        filename = f"{report['report_date'].replace('-', '')}_{report['broker']}_{report['short_title']}_{report['expected_pages']}页.pdf"
        path = PDF_DIR / filename
        response = request_with_retry(session, url)
        path.write_bytes(response.content)
        validation = validate_pdf(path, report)
        record = {
            **report,
            **validation,
            "source_url": url,
            "metadata_page": f"https://data.eastmoney.com/report/info/{report['info_code']}.html",
            "relative_path": str(path.relative_to(PACKAGE_ROOT)),
            "eastmoney_title": row.get("title"),
            "eastmoney_publish_date": row.get("publishDate"),
            "eastmoney_attach_pages": row.get("attachPages"),
        }
        log("VALIDATED", json.dumps(record, ensure_ascii=False))
        records.append(record)
        time.sleep(0.6)

    if len(records) != 2:
        raise RuntimeError(f"Expected 2 complete reports, got {len(records)}")
    if len({row["sha256"] for row in records}) != 2:
        raise RuntimeError("Duplicate report PDFs detected")

    write_metadata(records)
    build_zip()


if __name__ == "__main__":
    main()
