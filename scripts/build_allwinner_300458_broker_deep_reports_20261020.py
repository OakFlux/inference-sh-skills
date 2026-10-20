#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-10-20"
COMPANY = "全志科技"
FULL_COMPANY = "珠海全志科技股份有限公司"
STOCK_CODE = "300458"
PACKAGE = "全志科技_300458_券商深度报告_3份"
ROOT = Path("dist")
PACKAGE_ROOT = ROOT / PACKAGE
REPORT_DIR = PACKAGE_ROOT / "01_券商深度报告"
VERIFY_DIR = PACKAGE_ROOT / "02_说明与校验"
WORK_DIR = ROOT / "_allwinner_broker_report_work"
RENDER_DIR = WORK_DIR / "renders"
ZIP_PATH = ROOT / f"{PACKAGE}_截至20261020.zip"
SUMMARY_PATH = ROOT / "package_summary.json"

REPORTS: list[dict[str, Any]] = [
    {
        "date": "2025-09-23",
        "broker": "西南证券",
        "broker_full": "西南证券股份有限公司",
        "authors": "王谋,徐一丹",
        "title": "2025年半年报点评：专注SoC+技术领先，多点布局静待绽放",
        "info_code": "AP202509231749170619",
        "expected_pages": 13,
        "filename": "20250923_西南证券_专注SoC技术领先_多点布局静待绽放.pdf",
        "title_keywords": ["专注", "SoC", "多点布局"],
        "selection_reason": "2025年首次覆盖、篇幅13页，系统梳理SoC平台、机器人、车载和智能视觉等业务。",
    },
    {
        "date": "2021-09-23",
        "broker": "东亚前海证券",
        "broker_full": "东亚前海证券有限责任公司",
        "authors": "王刚",
        "title": "首次覆盖报告：SoC龙头平台化发展，乘风AIoT黄金赛道",
        "info_code": "AP202109231518032273",
        "expected_pages": 46,
        "filename": "20210923_东亚前海证券_首次覆盖_SoC龙头平台化发展_乘风AIoT黄金赛道.pdf",
        "title_keywords": ["SoC", "平台化", "AIoT"],
        "selection_reason": "46页首次覆盖报告，篇幅最长，覆盖行业空间、产品平台、竞争格局和估值。",
    },
    {
        "date": "2021-05-19",
        "broker": "东吴证券",
        "broker_full": "东吴证券股份有限公司",
        "authors": "王平阳",
        "title": "多元化SoC产品布局，受益智能物联市场成长",
        "info_code": "AP202105191492563835",
        "expected_pages": 25,
        "filename": "20210519_东吴证券_多元化SoC产品布局_受益智能物联市场成长.pdf",
        "title_keywords": ["多元化", "SoC", "智能物联"],
        "selection_reason": "25页公司研究报告，重点分析多产品线布局、AIoT需求及盈利预测。",
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/155 Safari/537.36",
    "Accept": "application/json,text/plain,application/pdf,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": f"https://data.eastmoney.com/report/{STOCK_CODE}.html",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request(session: requests.Session, method: str, url: str, *, timeout: tuple[int, int] = (20, 420), **kwargs: Any) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        try:
            response = session.request(method, url, timeout=timeout, allow_redirects=True, **kwargs)
            print(
                "HTTP", method, attempt, response.status_code,
                response.headers.get("content-type"), response.headers.get("content-length"),
                response.url, flush=True,
            )
            if response.status_code in {429, 500, 502, 503, 504}:
                response.close()
                time.sleep(min(attempt * 2, 10))
                continue
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            time.sleep(min(attempt * 2, 10))
    raise RuntimeError(f"request failed for {method} {url}: {errors[-3:]}")


def verify_api_metadata(session: requests.Session, report: dict[str, Any]) -> dict[str, Any]:
    params = {
        "industryCode": "*",
        "pageSize": "100",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": report["date"],
        "endTime": report["date"],
        "pageNo": "1",
        "fields": "",
        "qType": "0",
        "orgCode": "",
        "code": STOCK_CODE,
        "rcode": "",
        "p": "1",
        "pageNum": "1",
        "pageNumber": "1",
    }
    response = request(
        session,
        "GET",
        "https://reportapi.eastmoney.com/report/list",
        params=params,
        headers=HEADERS,
        timeout=(20, 120),
    )
    try:
        rows = response.json().get("data") or []
    finally:
        response.close()

    row = next((item for item in rows if str(item.get("infoCode") or "") == report["info_code"]), None)
    if not row:
        raise RuntimeError(f"metadata record not found for {report['info_code']}")

    title = str(row.get("title") or "")
    broker = str(row.get("orgSName") or row.get("orgName") or "")
    pages = int(row.get("attachPages") or 0)
    stock_name = str(row.get("stockName") or "")
    stock_code = str(row.get("stockCode") or "")

    if COMPANY not in stock_name and STOCK_CODE not in stock_code:
        raise RuntimeError(f"stock identity mismatch in metadata: {row}")
    if report["broker"] not in broker:
        raise RuntimeError(f"broker mismatch: expected {report['broker']}, got {broker}")
    if pages != int(report["expected_pages"]):
        raise RuntimeError(f"page metadata mismatch: expected {report['expected_pages']}, got {pages}")
    if not all(keyword in title for keyword in report["title_keywords"]):
        raise RuntimeError(f"title mismatch: {title}")

    return {
        "api_title": title,
        "api_broker": broker,
        "api_researcher": str(row.get("researcher") or ""),
        "api_pages": pages,
        "api_attach_size_kb": row.get("attachSize"),
        "api_rating": row.get("emRatingName"),
    }


def download_report(session: requests.Session, report: dict[str, Any], destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    candidates = [
        f"https://pdf.dfcfw.com/pdf/H3_{report['info_code']}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H2_{report['info_code']}_1.pdf",
    ]
    errors: list[str] = []
    for url in candidates:
        temp = destination.with_suffix(destination.suffix + ".part")
        temp.unlink(missing_ok=True)
        try:
            response = request(
                session,
                "GET",
                url,
                stream=True,
                headers={
                    **HEADERS,
                    "Referer": f"https://data.eastmoney.com/report/info/{report['info_code']}.html",
                },
                timeout=(25, 600),
            )
            try:
                with temp.open("wb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            handle.write(chunk)
                final_url = str(response.url)
            finally:
                response.close()

            size = temp.stat().st_size if temp.exists() else 0
            head = temp.read_bytes()[:8] if temp.exists() else b""
            if size < 150_000 or not head.startswith(b"%PDF-"):
                raise RuntimeError(f"invalid PDF bytes={size}, head={head!r}")
            temp.replace(destination)
            return final_url
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc!r}")
            temp.unlink(missing_ok=True)
    raise RuntimeError(f"all PDF candidates failed for {report['info_code']}: {errors}")


def render_page(path: Path, page_number: int, label: str) -> str:
    prefix = RENDER_DIR / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{label}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
            "-r", "110", "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    image = Path(str(prefix) + ".png")
    valid = (
        process.returncode == 0
        and image.exists()
        and image.stat().st_size > 5000
        and image.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(
            f"render validation failed for {path.name} page {page_number}: {process.stderr[-1500:]}"
        )
    return str(image.relative_to(WORK_DIR))


def validate_pdf(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-2500:]}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages != int(report["expected_pages"]):
        raise RuntimeError(
            f"actual page mismatch for {path.name}: expected {report['expected_pages']}, got {pages}"
        )

    render_pages = sorted({1, max(1, (pages + 1) // 2), pages})
    render_files = [render_page(path, number, f"p{number}") for number in render_pages]

    sample_indices = sorted({0, 1, min(2, pages - 1), pages // 2, pages - 1})
    text_parts: list[str] = []
    for index in sample_indices:
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_EXTRACT_WARNING", path.name, index + 1, repr(exc), flush=True)
    sample_text = "\n".join(text_parts)
    normalized = re.sub(r"\s+", "", sample_text)
    company_ok = COMPANY in normalized or FULL_COMPANY in normalized or STOCK_CODE in normalized
    broker_ok = report["broker"] in normalized or report["broker_full"] in normalized
    keyword_hits = sum(1 for keyword in report["title_keywords"] if keyword in normalized)

    if sample_text.strip() and not company_ok:
        raise RuntimeError(f"company identity not found in sampled text: {path.name}")
    if sample_text.strip() and not broker_ok:
        raise RuntimeError(f"broker identity not found in sampled text: {path.name}")
    if sample_text.strip() and keyword_hits == 0:
        raise RuntimeError(f"title keywords not found in sampled text: {path.name}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": check.returncode,
        "rendered_pages": render_pages,
        "render_files": render_files,
        "sample_text_extractable": bool(sample_text.strip()),
        "company_verified_when_text_extractable": company_ok,
        "broker_verified_when_text_extractable": broker_ok,
        "title_keyword_hits": keyword_hits,
    }


def write_supporting_files(records: list[dict[str, Any]]) -> None:
    manifest = {
        "package_name": PACKAGE,
        "company": FULL_COMPANY,
        "short_name": COMPANY,
        "stock_code": STOCK_CODE,
        "checked_as_of": CHECKED_AS_OF,
        "document_count": len(records),
        "selection_note": (
            "收录3份来自不同券商的完整原始PDF；优先选择明确首次覆盖、篇幅较长或系统覆盖行业、业务、"
            "竞争力、盈利预测与风险提示的公司研究。保留一份2025年较新报告，并以两份25页以上深度报告补充长期研究框架。"
        ),
        "records": records,
    }
    (PACKAGE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "文件", "发布日期", "券商", "作者", "标题", "页数", "文件大小（字节）", "SHA-256",
            "来源详情页", "PDF来源", "入选理由",
        ])
        for record in records:
            writer.writerow([
                record["relative_path"], record["date"], record["broker"], record["authors"],
                record["title"], record["pages"], record["bytes"], record["sha256"],
                record["source_detail_url"], record["source_pdf_url"], record["selection_reason"],
            ])

    with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(f"{record['sha256']}  {record['relative_path']}\n")

    lines = [
        f"{COMPANY}（{STOCK_CODE}）券商深度报告文件包",
        "",
        f"核对日期：{CHECKED_AS_OF}",
        f"收录数量：{len(records)}份完整券商原始PDF",
        "",
        "收录报告：",
    ]
    for index, record in enumerate(records, 1):
        lines.append(
            f"{index}. {record['date']} | {record['broker']} | {record['title']} | {record['pages']}页"
        )
        lines.append(f"   入选理由：{record['selection_reason']}")
    lines.extend([
        "",
        "筛选与校验：",
        "- 三份报告来自不同券商，排除网页摘要、普通新闻和重复文件；",
        "- 已核对东方财富研报数据库中的标题、券商、作者、发布日期与页数；",
        "- 已检查PDF文件头、qpdf结构、实际页数、公司与券商身份；",
        "- 每份PDF均完成首页、中间页和末页渲染测试，并生成SHA-256校验值；",
        "- 报告内容仅供研究参考，不构成投资建议。",
    ])
    (PACKAGE_ROOT / "00_文件清单与范围说明.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def create_zip() -> None:
    ZIP_PATH.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(PACKAGE_ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(ROOT))
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    for directory in (REPORT_DIR, VERIFY_DIR, RENDER_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.trust_env = False
    session.headers.update(HEADERS)

    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for report in REPORTS:
        metadata = verify_api_metadata(session, report)
        destination = REPORT_DIR / report["filename"]
        final_url = download_report(session, report, destination)
        validation = validate_pdf(destination, report)
        if validation["sha256"] in seen_hashes:
            raise RuntimeError(f"duplicate PDF detected: {destination.name}")
        seen_hashes.add(validation["sha256"])

        record = {
            "date": report["date"],
            "broker": report["broker"],
            "authors": report["authors"],
            "title": report["title"],
            "info_code": report["info_code"],
            "selection_reason": report["selection_reason"],
            "relative_path": str(destination.relative_to(PACKAGE_ROOT)),
            "source_detail_url": f"https://data.eastmoney.com/report/info/{report['info_code']}.html",
            "source_pdf_url": final_url,
            **metadata,
            **validation,
        }
        records.append(record)
        print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

    write_supporting_files(records)
    create_zip()

    summary = {
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256_file(ZIP_PATH),
        "pdf_count": len(records),
        "reports": [
            {
                "date": record["date"],
                "broker": record["broker"],
                "title": record["title"],
                "pages": record["pages"],
                "bytes": record["bytes"],
                "sha256": record["sha256"],
            }
            for record in records
        ],
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PACKAGE_SUMMARY=" + json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
