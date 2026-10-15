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

COMPANY = "若羽臣"
FULL_COMPANY = "广州若羽臣科技股份有限公司"
CODE = "003010"
AS_OF_DATE = "2026-10-15"
BJ = timezone(timedelta(hours=8))

ROOT = Path.cwd()
WORK_ROOT = ROOT / "_build_ruochen_003010_broker"
PACKAGE_NAME = f"{COMPANY}_{CODE}_券商深度报告_3份"
PACKAGE_ROOT = WORK_ROOT / PACKAGE_NAME
PDF_DIR = PACKAGE_ROOT / "01_完整原始PDF"
VERIFY_DIR = WORK_ROOT / "_verify"
ZIP_PATH = ROOT / f"{PACKAGE_NAME}.zip"

TARGETS: list[dict[str, Any]] = [
    {
        "info_code": "AP202606101823424637",
        "report_date": "2026-06-10",
        "broker": "开源证券",
        "broker_full": "开源证券股份有限公司",
        "analysts": "黄泽鹏、李昕恬",
        "title": "公司首次覆盖报告：“若”聚微光、“羽”化成蝶：缔造高端品牌新生态",
        "classification": "公司首次覆盖报告",
        "rating": "买入",
        "expected_pages": 39,
    },
    {
        "info_code": "AP202509111741763966",
        "report_date": "2025-09-11",
        "broker": "信达证券",
        "broker_full": "信达证券股份有限公司",
        "analysts": "蔡昕妤",
        "title": "公司深度报告：转型自有品牌业务进展顺利，业绩高增长",
        "classification": "公司深度报告",
        "rating": "买入",
        "expected_pages": 28,
    },
    {
        "info_code": "AP202502281643595958",
        "report_date": "2025-02-28",
        "broker": "中邮证券",
        "broker_full": "中邮证券有限责任公司",
        "analysts": "李媛媛",
        "title": "深度报告：绽家放量，斐萃初见成效，代运营企稳回升",
        "classification": "公司深度报告",
        "rating": "买入",
        "expected_pages": 31,
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
    value = re.sub(r"\s+", "", value)
    return value[:150]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_with_retry(session: requests.Session, url: str, *, require_pdf: bool = False) -> requests.Response:
    last_error: Exception | None = None
    headers = {
        **HEADERS,
        "Accept": "application/pdf,*/*;q=0.8" if require_pdf else "application/json,text/plain,*/*",
        "Referer": "https://data.eastmoney.com/report/stock.jshtml",
    }
    for attempt in range(1, 6):
        try:
            response = session.get(url, headers=headers, timeout=120, allow_redirects=True)
            log("HTTP", attempt, response.status_code, response.headers.get("content-type"), len(response.content), response.url)
            response.raise_for_status()
            if require_pdf and (not response.content.startswith(b"%PDF-") or len(response.content) < 50_000):
                raise RuntimeError(f"Invalid PDF response: {len(response.content)} bytes")
            return response
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(min(2**attempt, 12))
    raise RuntimeError(f"Failed to fetch {url}: {last_error!r}")


def load_metadata(session: requests.Session) -> dict[str, dict[str, Any]]:
    params = {
        "pageSize": "200",
        "pageNo": "1",
        "code": CODE,
        "qType": "0",
        "industryCode": "*",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": "2020-01-01",
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


def opening_text(path: Path, pages: int) -> str:
    result = subprocess.run(
        ["pdftotext", "-f", "1", "-l", str(min(8, pages)), "-enc", "UTF-8", str(path), "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pdftotext failed for {path}: {result.stderr[-1000:]}")
    return result.stdout


def render_pages(path: Path, page_count: int) -> tuple[list[int], list[str]]:
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
            raise RuntimeError(f"Invalid render: {image_path}")
        rendered.append(str(image_path))
    return selected, rendered


def validate_pdf(path: Path, target: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    data = path.read_bytes()
    if not data.startswith(b"%PDF-"):
        raise RuntimeError(f"Not a PDF: {path}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    expected = int(target["expected_pages"])
    metadata_pages = int(metadata.get("attachPages") or 0)
    if pages != expected:
        raise RuntimeError(f"Page count mismatch: expected {expected}, got {pages}")
    if metadata_pages and pages != metadata_pages:
        raise RuntimeError(f"Metadata page mismatch: expected {metadata_pages}, got {pages}")

    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, check=False)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed: {(qpdf.stdout + qpdf.stderr)[-2000:]}")

    compact = re.sub(r"\s+", "", opening_text(path, pages))
    identity_verified = any(token in compact for token in (COMPANY, FULL_COMPANY, CODE))
    broker_verified = any(token in compact for token in (target["broker"], target["broker_full"]))
    title_parts = [
        token for token in re.split(r"[：，、“”‘’+（）()\s]+", target["title"])
        if len(token) >= 4
    ]
    title_hits = sum(token in compact for token in title_parts)
    title_verified = title_hits >= 1
    if not identity_verified:
        raise RuntimeError(f"Company identity check failed for {path}")
    if not broker_verified:
        raise RuntimeError(f"Broker identity check failed for {path}")
    if not title_verified:
        raise RuntimeError(f"Title check failed for {path}: {title_parts}")

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
        "收录规则：",
        "1. 只收录完整公司深度报告或首次覆盖报告；排除财报点评、事件快评、网页摘要和残缺预览版。",
        "2. 每份报告均核验PDF结构、实际页数、公司名称/代码、券商署名及标题关键词。",
        "3. 每份PDF均渲染首页、中间页和末页进行可视检查。",
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
            f"   页数：{row['pages']}；文件：{row['relative_path']}",
            f"   SHA-256：{row['sha256']}",
            "",
        ])
    (PACKAGE_ROOT / "README.txt").write_text("\n".join(lines), encoding="utf-8")

    fields = [
        "report_date", "publish_date", "broker", "broker_full", "analysts", "title",
        "classification", "rating", "info_code", "pages", "bytes", "sha256",
        "relative_path", "source_url", "metadata_page", "identity_verified",
        "broker_verified", "title_verified"
    ]
    with (PACKAGE_ROOT / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "company": COMPANY,
        "full_company_name": FULL_COMPANY,
        "stock_code": CODE,
        "as_of_date": AS_OF_DATE,
        "generated_at": datetime.now(tz=BJ).isoformat(),
        "selection_standard": "完整公司深度/首次覆盖PDF；排除短篇点评、摘要及预览版",
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
                archive.write(path, arcname=str(Path(PACKAGE_NAME) / path.relative_to(PACKAGE_ROOT)))
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
    metadata_by_code = load_metadata(session)
    records: list[dict[str, Any]] = []

    for target in TARGETS:
        metadata = metadata_by_code.get(target["info_code"])
        if not metadata:
            raise RuntimeError(f"Missing Eastmoney metadata: {target['info_code']}")
        if str(metadata.get("stockCode") or "") != CODE or COMPANY not in str(metadata.get("stockName") or ""):
            raise RuntimeError(f"Stock identity mismatch: {metadata}")
        if target["broker"] not in str(metadata.get("orgSName") or metadata.get("orgName") or ""):
            raise RuntimeError(f"Broker mismatch: {metadata}")
        metadata_title = str(metadata.get("title") or "")
        if not metadata_title:
            raise RuntimeError(f"Missing title: {metadata}")

        url = f"https://pdf.dfcfw.com/pdf/H3_{target['info_code']}_1.pdf"
        filename = f"{target['report_date'].replace('-', '')}_{target['broker']}_{safe_name(target['title'])}_{target['expected_pages']}页.pdf"
        path = PDF_DIR / filename
        response = get_with_retry(session, url, require_pdf=True)
        path.write_bytes(response.content)
        validation = validate_pdf(path, target, metadata)
        record = {
            **target,
            **validation,
            "publish_date": str(metadata.get("publishDate") or "")[:10],
            "source_url": url,
            "metadata_page": f"https://data.eastmoney.com/report/info/{target['info_code']}.html",
            "relative_path": str(path.relative_to(PACKAGE_ROOT)),
            "eastmoney_title": metadata_title,
            "eastmoney_attach_pages": metadata.get("attachPages"),
            "eastmoney_attach_size_kb": metadata.get("attachSize"),
        }
        log("VALIDATED", json.dumps(record, ensure_ascii=False))
        records.append(record)
        time.sleep(0.5)

    if len(records) != 3:
        raise RuntimeError(f"Expected 3 records, got {len(records)}")
    if len({row["sha256"] for row in records}) != len(records):
        raise RuntimeError("Duplicate PDFs detected")

    write_support_files(records)
    build_zip()


if __name__ == "__main__":
    main()
