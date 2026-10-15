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

COMPANY = "瑞达期货"
FULL_COMPANY = "瑞达期货股份有限公司"
CODE = "002961"
AS_OF_DATE = "2026-10-15"
BJ = timezone(timedelta(hours=8))

WORK_ROOT = Path("_build_ruida_002961_broker")
PACKAGE_NAME = f"{COMPANY}_{CODE}_券商深度报告_2份"
PACKAGE_ROOT = WORK_ROOT / PACKAGE_NAME
PDF_DIR = PACKAGE_ROOT / "01_完整原始PDF"
VERIFY_DIR = WORK_ROOT / "_verify"
ZIP_PATH = Path(PACKAGE_NAME + ".zip")

TARGETS: list[dict[str, Any]] = [
    {
        "info_code": "AP202603201820674839",
        "report_date": "2026-03-20",
        "broker": "国信证券",
        "broker_full": "国信证券股份有限公司",
        "analysts": "孔祥、王德坤",
        "title": "资管与投资双击，受益商品弹性",
        "classification": "公司深度研究",
        "rating": "优于大市",
        "expected_pages": 22,
    },
    {
        "info_code": "AP202106101497123685",
        "report_date": "2021-06-10",
        "broker": "华鑫证券",
        "broker_full": "华鑫证券有限责任公司",
        "analysts": "曹愻川",
        "title": "全牌照期货公司，期货业CTA领跑者",
        "classification": "公司深度研究/首次覆盖",
        "rating": "推荐",
        "expected_pages": 24,
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
    return value[:180]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_with_retry(
    session: requests.Session,
    url: str,
    *,
    headers: dict[str, str],
    timeout: int = 120,
    require_pdf: bool = False,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            log("HTTP", attempt, response.status_code, response.headers.get("content-type"), len(response.content), response.url)
            response.raise_for_status()
            if require_pdf and (not response.content.startswith(b"%PDF-") or len(response.content) < 50_000):
                raise RuntimeError(
                    f"Invalid PDF response: {len(response.content)} bytes, {response.headers.get('content-type')}"
                )
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
        "beginTime": "2019-01-01",
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
    log("METADATA_COUNT", len(rows))
    return {str(row.get("infoCode") or ""): row for row in rows}


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
            [
                "pdftoppm",
                "-f", str(page_no),
                "-l", str(page_no),
                "-singlefile",
                "-png",
                "-r", "130",
                str(path),
                str(prefix),
            ],
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


def validate_pdf(path: Path, target: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    data = path.read_bytes()
    if not data.startswith(b"%PDF-"):
        raise RuntimeError(f"Not a PDF: {path}")

    reader = PdfReader(str(path), strict=False)
    page_count = len(reader.pages)
    expected_pages = int(metadata.get("attachPages") or target["expected_pages"])
    if page_count != expected_pages or page_count != target["expected_pages"]:
        raise RuntimeError(
            f"Page count mismatch for {path}: expected {target['expected_pages']}, metadata {expected_pages}, got {page_count}"
        )
    if page_count < 15:
        raise RuntimeError(f"Report too short for deep-report package: {path}, pages={page_count}")

    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, check=False)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path}: {(qpdf.stdout + qpdf.stderr)[-2000:]}")

    text = extract_opening_text(path, page_count)
    compact = re.sub(r"\s+", "", text)
    identity_verified = any(token in compact for token in (COMPANY, FULL_COMPANY, CODE))
    broker_verified = any(token in compact for token in (target["broker"], target["broker_full"]))
    title_keywords = [
        item for item in re.split(r"[，：,+/（）()\s]+", target["title"])
        if len(item) >= 4
    ]
    title_hits = sum(keyword in compact for keyword in title_keywords)
    title_verified = title_hits >= 1
    if not identity_verified:
        raise RuntimeError(f"Company identity check failed for {path}")
    if not broker_verified:
        raise RuntimeError(f"Broker identity check failed for {path}")
    if not title_verified:
        raise RuntimeError(f"Title keyword check failed for {path}: {title_keywords}")

    rendered_pages, render_files = render_selected_pages(path, page_count)
    return {
        "pages": page_count,
        "bytes": len(data),
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "identity_verified": identity_verified,
        "broker_verified": broker_verified,
        "title_verified": title_verified,
        "rendered_pages": rendered_pages,
        "render_files": render_files,
    }


def write_metadata(records: list[dict[str, Any]]) -> None:
    lines = [
        f"{COMPANY}（{CODE}）券商深度报告资料包",
        "",
        f"检索与核验截止日期：{AS_OF_DATE}",
        "",
        "收录原则：",
        "1. 优先收录公司深度研究或首次覆盖报告，不用短篇财报点评、事件快评或网页摘要凑数。",
        "2. 本资料包收录2份可公开直接取得、可验证为完整原始排版的券商PDF。",
        "3. 每份PDF均核验实际页数、公司名称或股票代码、券商署名、PDF结构，并渲染首页/中间页/末页检查。",
        "4. 文件来源为东方财富公开研报PDF镜像；报告版权归原券商及相关权利人所有，仅供研究学习。",
        "",
        "文件清单：",
    ]
    for index, record in enumerate(records, 1):
        lines.extend(
            [
                f"{index}. {record['broker']}，{record['report_date']}",
                f"   标题：{record['title']}",
                f"   类型：{record['classification']}；评级：{record['rating']}",
                f"   分析师：{record['analysts']}",
                f"   页数：{record['pages']}；大小：{record['bytes']}字节",
                f"   文件：{record['relative_path']}",
                f"   来源：{record['source_url']}",
                f"   SHA-256：{record['sha256']}",
                "",
            ]
        )
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
        "selection_standard": "完整公司深度/首次覆盖PDF优先；排除短篇点评、摘要和预览版",
        "records": records,
    }
    (PACKAGE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (PACKAGE_ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{record['sha256']}  {record['relative_path']}" for record in records) + "\n",
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
            raise RuntimeError(f"Missing Eastmoney metadata for {target['info_code']}")
        if str(metadata.get("stockCode") or "") != CODE:
            raise RuntimeError(f"Stock-code mismatch: {metadata}")
        if COMPANY not in str(metadata.get("stockName") or ""):
            raise RuntimeError(f"Stock-name mismatch: {metadata}")
        if target["broker"] not in str(metadata.get("orgSName") or metadata.get("orgName") or ""):
            raise RuntimeError(f"Broker mismatch: {metadata}")
        if target["title"] != str(metadata.get("title") or "").strip():
            raise RuntimeError(f"Title mismatch: expected {target['title']!r}, metadata {metadata.get('title')!r}")

        source_url = f"https://pdf.dfcfw.com/pdf/H3_{target['info_code']}_1.pdf"
        filename = f"{target['report_date'].replace('-', '')}_{target['broker']}_{safe_name(target['title'])}_{target['expected_pages']}页.pdf"
        path = PDF_DIR / filename
        response = get_with_retry(
            session,
            source_url,
            headers={
                **HEADERS,
                "Accept": "application/pdf,*/*;q=0.8",
                "Referer": f"https://data.eastmoney.com/report/info/{target['info_code']}.html",
            },
            require_pdf=True,
        )
        path.write_bytes(response.content)
        validation = validate_pdf(path, target, metadata)
        record = {
            **target,
            **validation,
            "publish_date": str(metadata.get("publishDate") or "")[:10],
            "source_url": source_url,
            "download_final_url": response.url,
            "metadata_page": f"https://data.eastmoney.com/report/info/{target['info_code']}.html",
            "relative_path": str(path.relative_to(PACKAGE_ROOT)),
            "eastmoney_attach_pages": metadata.get("attachPages"),
            "eastmoney_attach_size_kb": metadata.get("attachSize"),
        }
        log("VALIDATED", json.dumps(record, ensure_ascii=False))
        records.append(record)
        time.sleep(0.5)

    if len(records) != 2:
        raise RuntimeError(f"Expected 2 complete reports, got {len(records)}")
    if len({record["sha256"] for record in records}) != 2:
        raise RuntimeError("Duplicate report PDFs detected")

    write_metadata(records)
    build_zip()


if __name__ == "__main__":
    main()
