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
COMPANY = "传艺科技"
FULL_COMPANY = "江苏传艺科技股份有限公司"
STOCK_CODE = "002866"
PACKAGE = "传艺科技_002866_2020-2025年报_2026最新季报及半年报"
ROOT = Path(PACKAGE)
ANNUAL_DIR = ROOT / "01_年度报告"
QUARTERLY_DIR = ROOT / "02_最新季报"
SUPPLEMENT_DIR = ROOT / "03_补充定期报告"
VERIFY_DIR = ROOT / "04_说明与校验"
WORK_DIR = Path("_chuanyi_002866_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (ANNUAL_DIR, QUARTERLY_DIR, SUPPLEMENT_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.cninfo.com.cn/",
}

TARGETS: list[dict[str, Any]] = [
    {
        "period": "2020",
        "type": "年度报告",
        "title": "2020年年度报告",
        "publication_date": "2021-04-30",
        "url": "https://static.cninfo.com.cn/finalpage/2021-04-30/1209869643.PDF",
        "destination": ANNUAL_DIR / "2020_传艺科技_年度报告.pdf",
        "min_pages": 80,
        "notes": "年度报告全文",
    },
    {
        "period": "2021",
        "type": "年度报告",
        "title": "2021年年度报告（更新后）",
        "publication_date": "2022-03-21",
        "url": "https://static.cninfo.com.cn/finalpage/2022-03-21/1212629013.PDF",
        "destination": ANNUAL_DIR / "2021_传艺科技_年度报告_更新后.pdf",
        "min_pages": 80,
        "notes": "采用公司后续披露的更新后版本；已取消版本未收录",
    },
    {
        "period": "2022",
        "type": "年度报告",
        "title": "2022年年度报告（更新后）",
        "publication_date": "2023-09-28",
        "url": "https://static.cninfo.com.cn/finalpage/2023-09-28/1217971076.PDF",
        "destination": ANNUAL_DIR / "2022_传艺科技_年度报告_更新后.pdf",
        "min_pages": 80,
        "notes": "采用公司后续披露的更新后版本；更新前版本未收录",
    },
    {
        "period": "2023",
        "type": "年度报告",
        "title": "2023年年度报告",
        "publication_date": "2024-03-30",
        "url": "https://static.cninfo.com.cn/finalpage/2024-03-30/1219472308.PDF",
        "destination": ANNUAL_DIR / "2023_传艺科技_年度报告.pdf",
        "min_pages": 80,
        "notes": "年度报告全文",
    },
    {
        "period": "2024",
        "type": "年度报告",
        "title": "2024年年度报告",
        "publication_date": "2025-04-29",
        "url": "https://static.cninfo.com.cn/finalpage/2025-04-29/1223360319.PDF",
        "destination": ANNUAL_DIR / "2024_传艺科技_年度报告.pdf",
        "min_pages": 80,
        "notes": "年度报告全文",
    },
    {
        "period": "2025",
        "type": "年度报告",
        "title": "2025年年度报告",
        "publication_date": "2026-03-31",
        "url": "https://static.cninfo.com.cn/finalpage/2026-03-31/1225056663.PDF",
        "destination": ANNUAL_DIR / "2025_传艺科技_年度报告.pdf",
        "min_pages": 80,
        "notes": "年度报告全文",
    },
    {
        "period": "2026Q1",
        "type": "第一季度报告",
        "title": "2026年一季度报告",
        "publication_date": "2026-04-30",
        "url": "https://static.cninfo.com.cn/finalpage/2026-04-30/1225255190.PDF",
        "destination": QUARTERLY_DIR / "2026Q1_传艺科技_第一季度报告.pdf",
        "min_pages": 5,
        "notes": "截至核对日的最新季度报告；2026年10月1日至10月4日未检索到2026年三季度报告",
    },
    {
        "period": "2026H1",
        "type": "半年度报告（补充）",
        "title": "2026年半年度报告",
        "publication_date": "2026-08-15",
        "url": "https://static.cninfo.com.cn/finalpage/2026-08-15/1225473987.PDF",
        "destination": SUPPLEMENT_DIR / "2026H1_传艺科技_半年度报告.pdf",
        "min_pages": 60,
        "notes": "披露时间晚于一季报，作为更新的完整定期报告补充收录；不将其称为季报",
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_pdf(url: str, destination: Path) -> str:
    errors: list[str] = []
    temp = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(1, 7):
        temp.unlink(missing_ok=True)
        try:
            response = SESSION.get(
                url,
                headers=HEADERS,
                timeout=(25, 420),
                stream=True,
                allow_redirects=True,
            )
            print(
                "DOWNLOAD", destination.name, "attempt", attempt,
                "status", response.status_code,
                "type", response.headers.get("content-type"),
                "length", response.headers.get("content-length"),
                "final", response.url,
                flush=True,
            )
            response.raise_for_status()
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
            if size < 80_000 or not head.startswith(b"%PDF-"):
                raise RuntimeError(f"invalid PDF: size={size}, head={head!r}")
            temp.replace(destination)
            return final_url
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            temp.unlink(missing_ok=True)
            time.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"download failed for {destination.name}: {errors[-6:]}")


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
        and png.stat().st_size > 2500
        and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(
            f"render failed for {path.name} page {page_number}: "
            f"return={process.returncode}, stderr={process.stderr[-1500:]}"
        )
    relative = str(png.relative_to(WORK_DIR))
    png.unlink()
    return relative


def extract_sample_text(reader: PdfReader, pages: int) -> str:
    indices = sorted({0, 1, 2, min(5, pages - 1), max(0, pages // 2), pages - 1})
    parts: list[str] = []
    for index in indices:
        try:
            parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_EXTRACT_WARNING", index + 1, repr(exc), flush=True)
    return "\n".join(parts)


def validate_pdf(path: Path, target: dict[str, Any]) -> dict[str, Any]:
    check = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {check.stderr[-2500:]}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < int(target["min_pages"]):
        raise RuntimeError(
            f"unexpectedly short report {path.name}: pages={pages}, "
            f"minimum={target['min_pages']}"
        )

    rendered_pages = sorted({1, pages})
    for page_number in rendered_pages:
        render_page(path, page_number, f"p{page_number}")

    text = extract_sample_text(reader, pages)
    normalized = re.sub(r"\s+", "", text)
    identity_ok = any(marker in normalized for marker in (COMPANY, FULL_COMPANY, STOCK_CODE))
    if text.strip() and not identity_ok:
        raise RuntimeError(f"issuer identity missing from sampled text: {path.name}")

    year = target["period"][:4]
    if text.strip() and year not in normalized:
        raise RuntimeError(f"period year {year} missing from sampled text: {path.name}")

    first_text = "\n".join((reader.pages[i].extract_text() or "") for i in range(min(4, pages)))
    first_normalized = re.sub(r"\s+", "", first_text)
    report_type = target["type"]
    if report_type == "年度报告":
        if "年度报告摘要" in first_normalized:
            raise RuntimeError(f"annual report summary detected instead of full report: {path.name}")
        if first_text.strip() and "年度报告" not in first_normalized:
            raise RuntimeError(f"annual report marker missing: {path.name}")
    elif report_type == "第一季度报告":
        if first_text.strip() and not any(x in first_normalized for x in ("第一季度报告", "一季度报告")):
            raise RuntimeError(f"Q1 report marker missing: {path.name}")
    elif report_type.startswith("半年度报告"):
        if "半年度报告摘要" in first_normalized:
            raise RuntimeError(f"half-year summary detected instead of full report: {path.name}")
        if first_text.strip() and "半年度报告" not in first_normalized:
            raise RuntimeError(f"half-year report marker missing: {path.name}")

    return {
        "bytes": path.stat().st_size,
        "pages": pages,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "identity_text_verified_when_extractable": identity_ok,
        "rendered_pages": rendered_pages,
        "sample_text_extractable": bool(text.strip()),
    }


records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()
for target in TARGETS:
    final_url = download_pdf(target["url"], target["destination"])
    metadata = validate_pdf(target["destination"], target)
    if metadata["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate PDF detected: {target['destination'].name}")
    seen_hashes.add(metadata["sha256"])
    record = {
        "period": target["period"],
        "document_type": target["type"],
        "title": target["title"],
        "publication_date": target["publication_date"],
        "source": "巨潮资讯网（深交所法定信息披露平台）",
        "source_url": target["url"],
        "download_final_url": final_url,
        "relative_path": str(target["destination"].relative_to(ROOT)),
        "notes": target["notes"],
        **metadata,
    }
    records.append(record)
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

manifest = {
    "package_name": PACKAGE,
    "company": COMPANY,
    "full_company_name": FULL_COMPANY,
    "stock_code": STOCK_CODE,
    "checked_as_of": CHECKED_AS_OF,
    "annual_report_count": 6,
    "latest_quarterly_report": "2026年一季度报告",
    "supplementary_latest_periodic_report": "2026年半年度报告",
    "q3_status": "截至2026年10月4日，巨潮资讯未检索到传艺科技2026年三季度报告",
    "pdf_count": len(records),
    "records": records,
}
(ROOT / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as fh:
    writer = csv.writer(fh)
    writer.writerow([
        "文件", "期间", "文件类型", "公告标题", "披露日期", "页数",
        "字节数", "SHA-256", "来源", "来源网址", "说明",
    ])
    for record in records:
        writer.writerow([
            record["relative_path"], record["period"], record["document_type"],
            record["title"], record["publication_date"], record["pages"],
            record["bytes"], record["sha256"], record["source"],
            record["source_url"], record["notes"],
        ])

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as fh:
    for record in records:
        fh.write(f"{record['sha256']}  {record['relative_path']}\n")

readme = f"""{FULL_COMPANY}（{STOCK_CODE}）定期报告文件包

核对日期：{CHECKED_AS_OF}

收录内容：
1. 2020-2025年度报告全文，共6份；
2. 2026年一季度报告，共1份；
3. 2026年半年度报告，共1份，作为披露时间更晚的完整定期报告补充收录。

版本说明：
- 2021年年度报告采用“更新后”版本，未收录已取消版本；
- 2022年年度报告采用2023年9月28日披露的“更新后”版本，未收录更新前版本；
- 其余年度报告均采用正式全文版本，未以年度报告摘要替代。

最新季报口径：
- 截至2026年10月4日，巨潮资讯未检索到传艺科技2026年三季度报告；
- 因此最新季度报告为2026年一季度报告；
- 2026年半年度报告披露时间更晚，但半年报不属于季度报告，故单列为补充定期报告。

校验说明：
- 所有PDF均来自巨潮资讯网官方静态披露文件；
- 每份PDF均完成文件头、文件大小、qpdf结构和最低页数检查；
- 使用PDF解析器核对公司名称/股票代码、报告年度和报告类型；
- 每份PDF的第一页和最后一页均已实际渲染为PNG检查可读性；
- 所有文件已进行SHA-256去重，压缩包完成CRC完整性测试；
- 详细页数、来源网址和哈希值见文件清单.csv、SHA256SUMS.txt及manifest.json。
"""
(VERIFY_DIR / "README.txt").write_text(readme, encoding="utf-8")

zip_path = Path(PACKAGE + ".zip")
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
    if pdf_count != len(records):
        raise RuntimeError(f"ZIP PDF count mismatch: expected {len(records)}, got {pdf_count}")

print(
    "FINAL_ZIP", zip_path,
    "bytes", zip_path.stat().st_size,
    "sha256", sha256(zip_path),
    flush=True,
)
print(json.dumps({
    "package_name": PACKAGE,
    "annual_reports": 6,
    "latest_quarterly_report": "2026年一季度报告",
    "supplementary_report": "2026年半年度报告",
    "pdf_count": len(records),
    "zip_bytes": zip_path.stat().st_size,
    "zip_sha256": sha256(zip_path),
}, ensure_ascii=False, indent=2), flush=True)
