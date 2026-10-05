from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-10-05"
COMPANY = "美诺华"
FULL_COMPANY = "宁波美诺华药业股份有限公司"
STOCK_CODE = "603538"
PACKAGE = "美诺华_603538_券商深度报告_3份"
ROOT = Path(PACKAGE)
REPORT_DIR = ROOT / "01_券商深度报告"
VERIFY_DIR = ROOT / "02_说明与校验"
WORK_DIR = Path("_meinuohua_603538_broker_deep_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (REPORT_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://data.eastmoney.com/report/603538.html",
}

REPORTS: list[dict[str, Any]] = [
    {
        "date": "2022-01-10",
        "broker": "东莞证券",
        "broker_full": "东莞证券股份有限公司",
        "authors": "魏红梅",
        "title": "深度报告：国内一流的特色原料药供应商",
        "info_code": "AP202201101539564933",
        "expected_pages": 24,
        "filename": "20220110_东莞证券_深度报告_国内一流的特色原料药供应商.pdf",
        "title_keywords": ["国内一流", "特色原料药"],
    },
    {
        "date": "2020-03-09",
        "broker": "西南证券",
        "broker_full": "西南证券股份有限公司",
        "authors": "朱国广",
        "title": "“CMO/CDMO+原料药/制剂一体化”驱动下，迈入快速成长期",
        "info_code": "AP202003091375999422",
        "expected_pages": 26,
        "filename": "20200309_西南证券_CMO-CDMO与原料药制剂一体化驱动成长.pdf",
        "title_keywords": ["CMO", "原料药", "制剂"],
    },
    {
        "date": "2019-07-31",
        "broker": "国金证券",
        "broker_full": "国金证券股份有限公司",
        "authors": "李敬雷",
        "title": "“中间体-原料药-制剂”一体化产业升级，原料药和制剂业务双轮驱动",
        "info_code": "AP201907311341669796",
        "expected_pages": 29,
        "filename": "20190731_国金证券_中间体原料药制剂一体化产业升级.pdf",
        "title_keywords": ["中间体", "原料药", "制剂"],
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get(url: str, *, stream: bool = False, referer: str | None = None) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        headers = dict(HEADERS)
        if referer:
            headers["Referer"] = referer
        try:
            response = SESSION.get(url, headers=headers, timeout=(25, 420), stream=stream, allow_redirects=True)
            print("HTTP", attempt, response.status_code, response.headers.get("content-type"), response.headers.get("content-length"), response.url, flush=True)
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            time.sleep(min(attempt * 2, 10))
    raise RuntimeError(f"request failed: {url}; {errors[-3:]}")


def verify_api_metadata(report: dict[str, Any]) -> dict[str, Any]:
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
    response = SESSION.get(
        "https://reportapi.eastmoney.com/report/list",
        params=params,
        headers=HEADERS,
        timeout=90,
    )
    response.raise_for_status()
    rows = response.json().get("data") or []
    row = next((item for item in rows if str(item.get("infoCode") or "") == report["info_code"]), None)
    if not row:
        raise RuntimeError(f"metadata record not found for {report['info_code']}")
    title = str(row.get("title") or "")
    broker = str(row.get("orgSName") or row.get("orgName") or "")
    pages = int(row.get("attachPages") or 0)
    if COMPANY not in str(row.get("stockName") or "") and STOCK_CODE not in str(row.get("stockCode") or ""):
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


def download_report(report: dict[str, Any], destination: Path) -> str:
    candidates = [
        f"https://pdf.dfcfw.com/pdf/H3_{report['info_code']}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H2_{report['info_code']}_1.pdf",
    ]
    errors: list[str] = []
    for url in candidates:
        temp = destination.with_suffix(".pdf.part")
        temp.unlink(missing_ok=True)
        try:
            response = get(url, stream=True, referer=f"https://data.eastmoney.com/report/info/{report['info_code']}.html")
            try:
                with temp.open("wb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            handle.write(chunk)
                final_url = str(response.url)
            finally:
                response.close()
            head = temp.read_bytes()[:8]
            if temp.stat().st_size < 150_000 or not head.startswith(b"%PDF-"):
                raise RuntimeError(f"invalid PDF: bytes={temp.stat().st_size}, head={head!r}")
            temp.replace(destination)
            return final_url
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc!r}")
            temp.unlink(missing_ok=True)
    raise RuntimeError(f"all PDF candidates failed for {report['info_code']}: {errors}")


def render_page(path: Path, page_number: int, label: str) -> str:
    prefix = RENDER_DIR / f"{path.stem}_{label}"
    proc = subprocess.run(
        ["pdftoppm", "-f", str(page_number), "-l", str(page_number), "-r", "120", "-png", "-singlefile", str(path), str(prefix)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    png = Path(str(prefix) + ".png")
    if proc.returncode != 0 or not png.exists() or png.stat().st_size < 5000 or png.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError(f"render failed for {path.name} page {page_number}: {proc.stderr[-1200:]}")
    return str(png.relative_to(WORK_DIR))


def validate_pdf(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {qpdf.stderr[-2000:]}")
    reader = PdfReader(str(path), strict=False)
    page_count = len(reader.pages)
    if page_count != int(report["expected_pages"]):
        raise RuntimeError(f"actual page mismatch for {path.name}: expected {report['expected_pages']}, got {page_count}")
    page_numbers = sorted({1, max(1, (page_count + 1) // 2), page_count})
    renders = [render_page(path, page, f"p{page}") for page in page_numbers]

    sample_indices = sorted({0, 1, min(2, page_count - 1), page_count // 2, page_count - 1})
    text_parts: list[str] = []
    for index in sample_indices:
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_WARNING", path.name, index + 1, repr(exc), flush=True)
    text = re.sub(r"\s+", "", "\n".join(text_parts))
    company_ok = COMPANY in text or FULL_COMPANY in text or STOCK_CODE in text
    broker_ok = report["broker"] in text or report["broker_full"] in text
    keyword_hits = sum(1 for keyword in report["title_keywords"] if keyword in text)
    if text and not company_ok:
        raise RuntimeError(f"company identity missing from sampled text: {path.name}")
    if text and not broker_ok:
        print("BROKER_TEXT_WARNING", path.name, flush=True)
    if text and keyword_hits == 0:
        print("TITLE_TEXT_WARNING", path.name, flush=True)
    return {
        "pages": page_count,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "rendered_pages": page_numbers,
        "render_files": renders,
        "sample_text_extractable": bool(text),
        "company_verified_when_text_extractable": company_ok,
        "broker_verified_when_text_extractable": broker_ok,
        "title_keyword_hits": keyword_hits,
    }


records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()
for report in REPORTS:
    metadata = verify_api_metadata(report)
    destination = REPORT_DIR / report["filename"]
    final_url = download_report(report, destination)
    validation = validate_pdf(destination, report)
    if validation["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate PDF: {destination.name}")
    seen_hashes.add(validation["sha256"])
    record = {
        "date": report["date"],
        "broker": report["broker"],
        "authors": report["authors"],
        "title": report["title"],
        "info_code": report["info_code"],
        "relative_path": str(destination.relative_to(ROOT)),
        "source_detail_url": f"https://data.eastmoney.com/report/info/{report['info_code']}.html",
        "source_pdf_url": final_url,
        **metadata,
        **validation,
    }
    records.append(record)
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

manifest = {
    "package_name": PACKAGE,
    "company": FULL_COMPANY,
    "short_name": COMPANY,
    "stock_code": STOCK_CODE,
    "checked_as_of": CHECKED_AS_OF,
    "document_count": len(records),
    "selection_note": "优先选择明确标注深度报告或篇幅16页以上、具备系统性公司分析的完整券商原始PDF；排除季度点评、年报点评和网页摘要。",
    "records": records,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as handle:
    writer = csv.writer(handle)
    writer.writerow(["文件", "发布日期", "券商", "作者", "标题", "页数", "字节数", "SHA-256", "来源详情页", "PDF来源"])
    for record in records:
        writer.writerow([
            record["relative_path"], record["date"], record["broker"], record["authors"], record["title"],
            record["pages"], record["bytes"], record["sha256"], record["source_detail_url"], record["source_pdf_url"],
        ])

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as handle:
    for record in records:
        handle.write(f"{record['sha256']}  {record['relative_path']}\n")

readme = [
    f"{COMPANY}（{STOCK_CODE}）券商深度报告文件包",
    "",
    f"核对日期：{CHECKED_AS_OF}",
    "收录数量：3份完整券商原始PDF",
    "",
    "收录报告：",
]
for i, record in enumerate(records, 1):
    readme.append(f"{i}. {record['date']} | {record['broker']} | {record['title']} | {record['pages']}页")
readme.extend([
    "",
    "筛选原则：",
    "- 优先选择明确标注深度报告，或篇幅较长且系统覆盖业务、行业、竞争力、盈利预测与风险提示的公司研究；",
    "- 排除季度点评、年报点评、公告点评、网页摘要和非券商自有研究内容；",
    "- 三份报告来自不同券商，便于交叉比较研究框架和历史判断。",
    "",
    "校验项目：",
    "- 东方财富研报数据库中的标题、券商、作者、发布日期和页数元数据；",
    "- PDF文件头、qpdf结构、实际页数、公司身份和SHA-256去重；",
    "- 每份报告首页、中间页和末页均已实际渲染验证；",
    "- ZIP已执行完整性测试。",
])
(VERIFY_DIR / "README.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")

zip_path = Path(PACKAGE + ".zip")
zip_path.unlink(missing_ok=True)
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, path.as_posix())

with zipfile.ZipFile(zip_path, "r") as archive:
    bad = archive.testzip()
    if bad:
        raise RuntimeError(f"ZIP integrity failure: {bad}")
    pdf_count = sum(1 for name in archive.namelist() if name.lower().endswith(".pdf"))
    if pdf_count != 3:
        raise RuntimeError(f"expected 3 PDFs, found {pdf_count}")

print("FINAL_ZIP", zip_path, "bytes", zip_path.stat().st_size, "sha256", sha256(zip_path), flush=True)
print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
