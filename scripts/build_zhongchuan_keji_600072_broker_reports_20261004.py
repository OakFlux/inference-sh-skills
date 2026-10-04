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
COMPANY = "中船科技"
FORMER_NAME = "钢构工程"
STOCK_CODE = "600072"
PACKAGE_NAME = "中船科技_600072_券商深度报告_2份"
ROOT = Path(PACKAGE_NAME)
REPORT_DIR = ROOT / "01_券商深度报告"
VERIFY_DIR = ROOT / "02_说明与校验"
WORK_DIR = Path("_zhongchuan_keji_600072_broker_work")
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
        "date": "2022-12-06",
        "broker": "山西证券",
        "broker_tokens": ["山西证券", "SHANXI SECURITIES"],
        "authors": "李孔逸",
        "title": "优质资产拟注入，海风龙头现雏形",
        "info_code": "AP202212061580852250",
        "filename": "20221206_山西证券_优质资产拟注入_海风龙头现雏形.pdf",
        "min_pages": 20,
        "selection_note": "公司深度研究；系统性覆盖重大资产重组、风电资产与盈利预测",
    },
    {
        "date": "2023-06-14",
        "broker": "国信证券",
        "broker_tokens": ["国信证券", "GUOSEN SECURITIES", "GUOSEN"],
        "authors": "陈抒扬",
        "title": "重组注入优质风电资产，产业融合促进持续增长",
        "info_code": "AP202306141590946563",
        "filename": "20230614_国信证券_重组注入优质风电资产_产业融合促进持续增长.pdf",
        "min_pages": 6,
        "selection_note": "完整公司研究报告；聚焦重组完成后的风电资产、订单与盈利预测",
    },
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def request_pdf(url: str, referer: str, timeout: tuple[int, int] = (25, 420)) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        headers = dict(HEADERS)
        headers["Referer"] = referer
        try:
            response = SESSION.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=True)
            print(
                "HTTP", url, "attempt", attempt, "status", response.status_code,
                "type", response.headers.get("content-type"),
                "length", response.headers.get("content-length"),
                "final", response.url,
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(attempt * 2, 10))
    raise RuntimeError(f"request failed for {url}: {errors[-6:]}")


def download_report(report: dict[str, Any], destination: Path) -> tuple[str, list[str]]:
    info_code = report["info_code"]
    page_url = f"https://data.eastmoney.com/report/info/{info_code}.html"
    candidates = [
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf?download=1",
    ]
    errors: list[str] = []
    for url in candidates:
        temp = destination.with_suffix(destination.suffix + ".part")
        temp.unlink(missing_ok=True)
        try:
            response = request_pdf(url, page_url)
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
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-2500:]}")

    reader = PdfReader(str(path), strict=False)
    page_count = len(reader.pages)
    if page_count < int(report["min_pages"]):
        raise RuntimeError(
            f"report too short for selected full-report standard: {path.name}, "
            f"pages={page_count}, expected>={report['min_pages']}"
        )

    page_numbers = sorted({1, max(1, (page_count + 1) // 2), page_count})
    render_files = [render_page(path, p, f"p{p}") for p in page_numbers]

    sample_indices = sorted({0, 1, 2, min(5, page_count - 1), page_count // 2, page_count - 1})
    text_parts: list[str] = []
    for idx in sample_indices:
        try:
            text_parts.append(reader.pages[idx].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_EXTRACT_WARNING", path.name, idx + 1, repr(exc), flush=True)
    sample_text = "\n".join(text_parts)
    normalized = re.sub(r"\s+", "", sample_text)

    company_ok = COMPANY in normalized or FORMER_NAME in normalized or STOCK_CODE in normalized
    broker_ok = any(token.replace(" ", "") in normalized.upper() for token in report["broker_tokens"])
    title_tokens = [token for token in re.split(r"[，、：； ]+", report["title"]) if len(token) >= 4]
    title_hits = sum(1 for token in title_tokens if token in normalized)
    title_ok = title_hits >= min(2, len(title_tokens)) if title_tokens else True
    research_ok = any(marker in normalized for marker in (
        "公司研究", "公司深度", "深度研究", "首次覆盖", "投资要点",
        "盈利预测", "投资建议", "风险提示", "评级",
    ))

    if sample_text.strip() and not company_ok:
        raise RuntimeError(f"company identity not found in sampled text: {path.name}")
    if sample_text.strip() and not broker_ok:
        raise RuntimeError(f"broker identity not found in sampled text: {path.name}")
    if sample_text.strip() and not title_ok:
        raise RuntimeError(f"title identity not found in sampled text: {path.name}")
    if sample_text.strip() and not research_ok:
        raise RuntimeError(f"company-research markers not found in sampled text: {path.name}")

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
        "company_research_marker_verified_when_text_extractable": research_ok,
        "sample_text_extractable": bool(sample_text.strip()),
    }


records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()
for report in REPORTS:
    destination = REPORT_DIR / report["filename"]
    final_url, failures = download_report(report, destination)
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
        "selection_note": report["selection_note"],
        "source": "东方财富研报原文PDF镜像",
        "report_page_url": f"https://data.eastmoney.com/report/info/{report['info_code']}.html",
        "source_url": final_url,
        "failed_download_candidates_before_success": failures,
        **metadata,
    }
    records.append(record)
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

manifest = {
    "package_name": PACKAGE_NAME,
    "company": COMPANY,
    "stock_code": STOCK_CODE,
    "checked_as_of": CHECKED_AS_OF,
    "report_count": len(records),
    "selection_standard": [
        "优先完整公司深度、首次覆盖或围绕重大资产重组开展的系统性公司研究报告。",
        "排除网页摘要、公开预览不完整文件及短篇财报点评。",
        "公开可验证的完整原始PDF仅选取两份，未用摘要凑足三份。",
    ],
    "records": records,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as fh:
    writer = csv.writer(fh)
    writer.writerow([
        "文件", "日期", "券商", "作者", "标题", "页数", "字节数", "SHA-256",
        "选取说明", "研报页面", "PDF来源",
    ])
    for record in records:
        writer.writerow([
            record["relative_path"], record["date"], record["broker"], record["authors"],
            record["title"], record["pages"], record["bytes"], record["sha256"],
            record["selection_note"], record["report_page_url"], record["source_url"],
        ])

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as fh:
    for record in records:
        fh.write(f"{record['sha256']}  {record['relative_path']}\n")

readme_lines = [
    f"{COMPANY}（{STOCK_CODE}）券商深度报告文件包",
    "",
    f"核对日期：{CHECKED_AS_OF}",
    "收录数量：2份完整原始PDF",
    "",
    "收录报告：",
]
for i, record in enumerate(records, 1):
    readme_lines.append(
        f"{i}. {record['date']}｜{record['broker']}｜《{record['title']}》｜{record['pages']}页｜{record['authors']}"
    )
readme_lines.extend([
    "",
    "筛选说明：",
    "- 仅收录能够直接取得并验证完整性的券商原始PDF；",
    "- 长城证券2023年报告和2016—2017年明确标注为深度报告的历史报告，目前公开页面仅能取得预览或摘要，故未纳入；",
    "- 未使用短篇财报点评或网页摘要凑足三份。",
    "",
    "校验说明：",
    "- PDF文件头、文件大小和qpdf结构检查；",
    "- PDF解析器页数核验；",
    "- 公司名称/股票代码、券商署名、标题关键词及公司研究标识核验；",
    "- 每份PDF首页、中间页及末页均实际渲染为PNG检查；",
    "- SHA-256去重及ZIP完整性测试。",
    "",
    "详细来源与校验结果见文件清单.csv、SHA256SUMS.txt及manifest.json。",
])
(VERIFY_DIR / "README.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

zip_path = Path(PACKAGE_NAME + ".zip")
zip_path.unlink(missing_ok=True)
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
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
print(json.dumps({
    "package_name": PACKAGE_NAME,
    "report_count": len(records),
    "records": records,
    "zip_bytes": zip_path.stat().st_size,
    "zip_sha256": sha256(zip_path),
}, ensure_ascii=False, indent=2), flush=True)
