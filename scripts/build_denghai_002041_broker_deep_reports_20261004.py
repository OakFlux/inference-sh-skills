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

CHECKED_AS_OF = "2026-10-04"
COMPANY = "登海种业"
FULL_COMPANY = "山东登海种业股份有限公司"
STOCK_CODE = "002041"
PACKAGE_NAME = "登海种业_002041_券商深度报告_3份"
ROOT = Path(PACKAGE_NAME)
REPORT_DIR = ROOT / "01_券商深度报告"
VERIFY_DIR = ROOT / "02_说明与校验"
WORK_DIR = Path("_denghai_002041_broker_reports_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (REPORT_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

REPORTS: list[dict[str, Any]] = [
    {
        "date": "2022-04-27",
        "broker": "开源证券",
        "broker_tokens": ["开源证券", "KYSEC"],
        "title": "公司首次覆盖报告：周期上行叠加转基因落地，玉米种子龙头业绩可期",
        "title_tokens": ["周期上行叠加转基因落地", "玉米种子龙头业绩可期"],
        "authors": "陈雪丽、李怡然",
        "info_code": "AP202204271561894887",
        "filename": "20220427_开源证券_周期上行叠加转基因落地_玉米种子龙头业绩可期.pdf",
        "min_pages": 18,
    },
    {
        "date": "2022-05-31",
        "broker": "申港证券",
        "broker_tokens": ["申港证券", "SHENGANG"],
        "title": "仓廪实天下安，玉米种子龙头再起航",
        "title_tokens": ["仓廪实天下安", "玉米种子龙头再起航"],
        "authors": "曹旭特",
        "info_code": "AP202205311569044620",
        "filename": "20220531_申港证券_仓廪实天下安_玉米种子龙头再起航.pdf",
        "min_pages": 20,
    },
    {
        "date": "2022-08-28",
        "broker": "华安证券",
        "broker_tokens": ["华安证券", "HAZQ"],
        "title": "玉米种子领军企业，优质受体品种业绩可期",
        "title_tokens": ["玉米种子领军企业", "优质受体品种业绩可期"],
        "authors": "王莺",
        "info_code": "AP202208281577744088",
        "filename": "20220828_华安证券_玉米种子领军企业_优质受体品种业绩可期.pdf",
        "min_pages": 20,
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request_pdf(url: str, referer: str, timeout: tuple[int, int] = (20, 420)) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        headers = dict(HEADERS)
        headers["Referer"] = referer
        try:
            response = SESSION.get(
                url, headers=headers, stream=True, timeout=timeout, allow_redirects=True
            )
            print(
                "HTTP", url, "attempt", attempt,
                "status", response.status_code,
                "type", response.headers.get("content-type"),
                "length", response.headers.get("content-length"),
                "final", response.url,
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"request failed for {url}: {errors[-6:]}")


def download_report(report: dict[str, Any], destination: Path) -> tuple[str, list[str]]:
    info_code = report["info_code"]
    referer = f"https://data.eastmoney.com/report/info/{info_code}.html"
    candidates = [
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf?download=1",
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf?{int(time.time() * 1000)}.pdf",
    ]
    errors: list[str] = []
    for url in candidates:
        temp = destination.with_suffix(destination.suffix + ".part")
        temp.unlink(missing_ok=True)
        try:
            response = request_pdf(url, referer)
            try:
                with temp.open("wb") as fh:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            fh.write(chunk)
                final_url = str(response.url)
            finally:
                response.close()
            size = temp.stat().st_size
            head = temp.read_bytes()[:8]
            if size < 100_000 or not head.startswith(b"%PDF-"):
                raise RuntimeError(f"not a valid PDF: bytes={size}, head={head!r}")
            temp.replace(destination)
            print("DOWNLOADED", destination, size, final_url, flush=True)
            return final_url, errors
        except Exception as exc:  # noqa: BLE001
            temp.unlink(missing_ok=True)
            errors.append(f"{url} | {exc!r}")
            print("DOWNLOAD_FAILED", url, repr(exc), flush=True)
    raise RuntimeError(f"all download candidates failed for {destination.name}: {errors}")


def render_page(path: Path, page_number: int, suffix: str) -> str:
    prefix = RENDER_DIR / f"{path.stem}_{suffix}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
            "-r", "100", "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    png = Path(str(prefix) + ".png")
    valid = (
        process.returncode == 0
        and png.exists()
        and png.stat().st_size > 2000
        and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(
            f"render validation failed for {path.name} page {page_number}: "
            f"return={process.returncode}, stderr={process.stderr[-1500:]}"
        )
    relative = str(png.relative_to(WORK_DIR))
    print("RENDERED", path.name, page_number, relative, png.stat().st_size, flush=True)
    return relative


def validate_report(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    check = subprocess.run(
        ["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300
    )
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-2500:]}")

    reader = PdfReader(str(path), strict=False)
    page_count = len(reader.pages)
    if page_count < int(report["min_pages"]):
        raise RuntimeError(
            f"report too short for deep-report standard: {path.name}, "
            f"pages={page_count}, expected>={report['min_pages']}"
        )

    page_numbers = sorted({1, max(1, (page_count + 1) // 2), page_count})
    render_files = [
        render_page(path, page_number, f"p{page_number}") for page_number in page_numbers
    ]

    sample_indices = sorted(
        set(range(min(12, page_count)))
        | {max(0, page_count // 2), page_count - 1}
    )
    text_parts: list[str] = []
    for index in sample_indices:
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_EXTRACT_WARNING", path.name, index + 1, repr(exc), flush=True)
    sample_text = "\n".join(text_parts)
    normalized = re.sub(r"\s+", "", sample_text)

    company_ok = any(token in normalized for token in (COMPANY, FULL_COMPANY, STOCK_CODE))
    broker_ok = any(token in normalized for token in report["broker_tokens"])
    title_ok = any(token in normalized for token in report["title_tokens"])
    deep_marker_ok = any(
        marker in normalized
        for marker in (
            "首次覆盖", "公司深度", "深度报告", "深度研究", "公司研究",
            "投资要点", "盈利预测", "估值", "投资评级",
        )
    )

    if sample_text.strip() and not company_ok:
        raise RuntimeError(f"company identity not found in sampled text: {path.name}")
    if sample_text.strip() and not broker_ok:
        raise RuntimeError(f"broker identity not found in sampled text: {path.name}")
    if sample_text.strip() and not title_ok:
        raise RuntimeError(f"report title not found in sampled text: {path.name}")
    if sample_text.strip() and not deep_marker_ok:
        raise RuntimeError(f"deep/company research marker not found in sampled text: {path.name}")

    return {
        "pages": page_count,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "rendered_pages": page_numbers,
        "render_files": render_files,
        "company_identity_verified_when_text_extractable": company_ok,
        "broker_identity_verified_when_text_extractable": broker_ok,
        "title_verified_when_text_extractable": title_ok,
        "deep_report_marker_verified_when_text_extractable": deep_marker_ok,
        "sample_text_extractable": bool(sample_text.strip()),
    }


records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()
for report in REPORTS:
    destination = REPORT_DIR / report["filename"]
    source_url, failed_candidates = download_report(report, destination)
    metadata = validate_report(destination, report)
    if metadata["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate report detected: {destination.name}")
    seen_hashes.add(metadata["sha256"])
    record = {
        "date": report["date"],
        "broker": report["broker"],
        "authors": report["authors"],
        "title": report["title"],
        "stock_code": STOCK_CODE,
        "info_code": report["info_code"],
        "relative_path": str(destination.relative_to(ROOT)),
        "source": "东方财富研报原文PDF镜像",
        "report_page_url": f"https://data.eastmoney.com/report/info/{report['info_code']}.html",
        "source_url": source_url,
        "failed_download_candidates_before_success": failed_candidates,
        **metadata,
    }
    records.append(record)
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

manifest = {
    "package_name": PACKAGE_NAME,
    "company": COMPANY,
    "stock_code": STOCK_CODE,
    "checked_as_of": CHECKED_AS_OF,
    "selection_standard": (
        "完整公司深度或首次覆盖报告；优先不同券商；排除短篇财报点评、季报点评和网页摘要"
    ),
    "report_count": len(records),
    "records": records,
}
(ROOT / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as fh:
    writer = csv.writer(fh)
    writer.writerow([
        "日期", "券商", "作者", "标题", "文件", "页数", "字节数",
        "SHA-256", "研报页面", "PDF来源",
    ])
    for record in records:
        writer.writerow([
            record["date"], record["broker"], record["authors"], record["title"],
            record["relative_path"], record["pages"], record["bytes"],
            record["sha256"], record["report_page_url"], record["source_url"],
        ])

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as fh:
    for record in records:
        fh.write(f"{record['sha256']}  {record['relative_path']}\n")

readme_lines = [
    f"{COMPANY}（{STOCK_CODE}）券商深度报告文件包",
    "",
    f"核对日期：{CHECKED_AS_OF}",
    "",
    "筛选原则：",
    "- 仅收录完整公司深度或首次覆盖报告；",
    "- 优先选取不同券商，避免同一逻辑的重复报告；",
    "- 排除短篇年报/季报点评、行情点评和网页摘要；",
    "",
    "收录报告：",
]
for index, record in enumerate(records, start=1):
    readme_lines.append(
        f"{index}. {record['date']}｜{record['broker']}｜《{record['title']}》｜{record['pages']}页"
    )
readme_lines.extend([
    "",
    "校验说明：",
    "- 检查PDF文件头、文件大小和qpdf结构；",
    "- 使用PDF解析器核验页数、公司名称、股票代码、券商署名和报告标题；",
    "- 每份PDF均实际渲染首页、中间页和末页；",
    "- 完成SHA-256去重及ZIP完整性测试；",
    "- 详细来源及逐文件校验值见文件清单.csv、SHA256SUMS.txt和manifest.json。",
])
(VERIFY_DIR / "README.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

zip_path = Path(PACKAGE_NAME + ".zip")
zip_path.unlink(missing_ok=True)
with zipfile.ZipFile(
    zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True
) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, path.as_posix())

with zipfile.ZipFile(zip_path, "r") as archive:
    bad_member = archive.testzip()
    if bad_member:
        raise RuntimeError(f"ZIP integrity test failed at {bad_member}")
    pdf_count = sum(1 for name in archive.namelist() if name.lower().endswith(".pdf"))
    if pdf_count != len(REPORTS):
        raise RuntimeError(f"ZIP PDF count mismatch: expected {len(REPORTS)}, got {pdf_count}")

print(
    "FINAL_ZIP", zip_path,
    "bytes", zip_path.stat().st_size,
    "sha256", sha256(zip_path),
    flush=True,
)
