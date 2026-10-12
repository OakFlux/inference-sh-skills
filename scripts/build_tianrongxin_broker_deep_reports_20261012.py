from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

COMPANY = "天融信"
CODE = "002212"
AS_OF = "2026-10-12"
ROOT = Path(f"{COMPANY}_{CODE}_券商深度报告")
REPORT_DIR = ROOT / "01_券商深度报告"
VERIFY_DIR = Path("_verify_tianrongxin_broker_reports")
ZIP_PATH = Path(f"{COMPANY}_{CODE}_券商深度报告_20261012.zip")

for directory in (REPORT_DIR, VERIFY_DIR):
    directory.mkdir(parents=True, exist_ok=True)

CANDIDATES: list[dict[str, Any]] = [
    {
        "info_code": "AP202211201580402166",
        "publish_date": "2022-11-20",
        "institution": "国金证券",
        "analyst": "孟灿",
        "title": "国内防火墙龙头，云计算打开新增长空间",
        "report_type": "公司深度/首次覆盖",
        "priority": 100,
    },
    {
        "info_code": "AP202208181577343486",
        "publish_date": "2022-08-18",
        "institution": "华安证券",
        "analyst": "尹沿技、王奇珏、张旭光",
        "title": "雄踞硬件、借力新场景，网安元老步步为营",
        "report_type": "公司深度/首次覆盖",
        "priority": 95,
    },
    {
        "info_code": "AP202205251567737025",
        "publish_date": "2022-05-25",
        "institution": "开源证券",
        "analyst": "陈宝健、刘逍遥",
        "title": "公司首次覆盖报告：立足基础安全，强势进军新兴领域",
        "report_type": "首次覆盖报告",
        "priority": 90,
    },
]

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/152.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request(url: str, *, referer: str | None = None) -> requests.Response:
    headers: dict[str, str] = {}
    if referer:
        headers["Referer"] = referer
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = SESSION.get(url, headers=headers, timeout=(20, 180), allow_redirects=True)
            print(
                "HTTP",
                attempt,
                response.status_code,
                response.headers.get("content-type"),
                len(response.content),
                response.url,
                flush=True,
            )
            if response.status_code in {429, 500, 502, 503, 504}:
                time.sleep(attempt * 2)
                continue
            return response
        except Exception as exc:
            last_error = exc
            if attempt < 5:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Request failed: {url}: {last_error}")


def safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", "", value)
    return value[:110].strip("._")


def resolve_pdf(report: dict[str, Any]) -> tuple[bytes, str, str]:
    info_code = str(report["info_code"])
    detail_url = f"https://data.eastmoney.com/report/info/{info_code}.html"
    detail = request(detail_url)
    if detail.status_code != 200:
        raise RuntimeError(f"Detail page returned HTTP {detail.status_code}: {info_code}")
    detail_text = detail.text
    normalized_detail = re.sub(r"\s+", "", detail_text)
    normalized_title = re.sub(r"\s+", "", str(report["title"]))
    title_probe = normalized_title.replace("：", "").replace("，", "")[:10]
    if title_probe not in normalized_detail.replace("：", "").replace("，", ""):
        raise RuntimeError(f"Title validation failed for {info_code}")
    if COMPANY not in detail_text or CODE not in detail_text:
        raise RuntimeError(f"Company identity missing from detail page for {info_code}")
    if str(report["institution"]) not in detail_text:
        raise RuntimeError(f"Institution identity missing from detail page for {info_code}")

    explicit_urls = re.findall(r"https?://[^\"'<>]+?\.pdf(?:\?[^\"'<>]*)?", detail_text, flags=re.I)
    generated_urls: list[str] = []
    for host_prefix in ("H3", "H1", "H2", "H4", "H5", "H0"):
        for suffix in ("_1.pdf", "_2.pdf", "_0.pdf"):
            generated_urls.append(f"https://pdf.dfcfw.com/pdf/{host_prefix}_{info_code}{suffix}")

    urls: list[str] = []
    for url in explicit_urls + generated_urls:
        cleaned = url.replace("\\/", "/")
        if cleaned not in urls:
            urls.append(cleaned)

    for url in urls:
        response = request(url, referer=detail_url)
        if (
            response.status_code == 200
            and response.content.startswith(b"%PDF")
            and len(response.content) > 100_000
        ):
            return response.content, response.url, detail_url
    raise RuntimeError(f"No public complete PDF found for {info_code}")


def inspect_pdf(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 15:
        raise RuntimeError(f"Report is too short for the deep-report package: {path.name}: {pages} pages")

    sample_indices = sorted(set([0, 1, min(2, pages - 1), pages - 1]))
    text_parts: list[str] = []
    for index in sample_indices:
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception:
            pass
    sample_text = "\n".join(text_parts)
    company_ok = COMPANY in sample_text or CODE in sample_text
    institution_ok = str(report["institution"]) in sample_text
    if len(sample_text.strip()) > 300 and not company_ok:
        raise RuntimeError(f"Company identity not found in PDF sample: {path.name}")
    if len(sample_text.strip()) > 300 and not institution_ok:
        raise RuntimeError(f"Institution identity not found in PDF sample: {path.name}")

    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf validation failed: {path.name}: {qpdf.stderr}")

    for page_number, label in ((1, "first"), (pages, "last")):
        output_base = VERIFY_DIR / f"{path.stem}_{label}"
        rendered = subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-r",
                "72",
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-singlefile",
                str(path),
                str(output_base),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        png_path = Path(str(output_base) + ".png")
        if rendered.returncode != 0 or not png_path.exists() or png_path.stat().st_size < 1_000:
            raise RuntimeError(f"Page render failed: {path.name}, page {page_number}: {rendered.stderr}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "first_last_page_rendered": True,
        "company_text_verified_when_extractable": bool(company_ok or len(sample_text.strip()) <= 300),
        "institution_text_verified_when_extractable": bool(institution_ok or len(sample_text.strip()) <= 300),
    }


def main() -> None:
    validated: list[dict[str, Any]] = []
    temp_dir = Path("_tianrongxin_candidate_pdfs")
    temp_dir.mkdir(exist_ok=True)

    for report in CANDIDATES:
        try:
            content, pdf_url, detail_url = resolve_pdf(report)
            temp_path = temp_dir / f"{report['info_code']}.pdf"
            temp_path.write_bytes(content)
            metadata = inspect_pdf(temp_path, report)
            record = {
                **report,
                **metadata,
                "pdf_url": pdf_url,
                "detail_url": detail_url,
                "temp_path": temp_path,
            }
            validated.append(record)
            print("CANDIDATE_VALID", json.dumps(record, ensure_ascii=False, default=str), flush=True)
        except Exception as exc:
            print("CANDIDATE_FAILED", report["info_code"], repr(exc), flush=True)

    if len(validated) < 2:
        raise RuntimeError(f"Only {len(validated)} qualifying public full reports were available")

    validated.sort(key=lambda item: (int(item["priority"]), item["publish_date"]), reverse=True)
    selected = validated[:3]

    records: list[dict[str, Any]] = []
    for rank, item in enumerate(selected, start=1):
        filename = (
            f"{rank:02d}_{item['publish_date'].replace('-', '')}_{item['institution']}_"
            f"{safe_name(item['title'])}.pdf"
        )
        destination = REPORT_DIR / filename
        shutil.copy2(item["temp_path"], destination)
        records.append(
            {
                "relative_path": destination.relative_to(ROOT).as_posix(),
                "filename": destination.name,
                "company": COMPANY,
                "stock_code": CODE,
                "publish_date": item["publish_date"],
                "institution": item["institution"],
                "analyst": item["analyst"],
                "title": item["title"],
                "report_type": item["report_type"],
                "info_code": item["info_code"],
                "detail_url": item["detail_url"],
                "pdf_url": item["pdf_url"],
                "source": "东方财富研报中心公开历史档案及公开PDF端点",
                "pages": item["pages"],
                "bytes": destination.stat().st_size,
                "sha256": sha256_file(destination),
                "qpdf_return_code": item["qpdf_return_code"],
                "first_last_page_rendered": True,
            }
        )

    readme_lines = [
        f"{COMPANY}（{CODE}）券商深度报告包",
        "",
        f"资料整理日期：{AS_OF}",
        "",
        "筛选口径：",
        "1. 仅收录公开可直接取得的完整PDF，不使用网页摘要、预览页或受限附件冒充全文。",
        "2. 优先收录公司深度、首次覆盖及具备完整行业—公司—财务—估值框架的长篇报告。",
        "3. 本包所收报告实际页数均不少于15页。",
        "",
        "收录文件：",
    ]
    for record in records:
        readme_lines.append(
            f"- {record['publish_date']}｜{record['institution']}｜{record['title']}｜{record['pages']}页"
        )
    readme_lines.extend(
        [
            "",
            "校验项目：PDF文件头、实际页数、公司及券商身份文本（可提取时）、qpdf结构、首末页渲染和ZIP CRC。",
            "报告版权归相应证券研究机构及作者所有，仅供个人研究参考，不构成投资建议。",
        ]
    )
    (ROOT / "00_文件清单与来源说明.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

    with (ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "relative_path",
            "publish_date",
            "institution",
            "analyst",
            "title",
            "report_type",
            "pages",
            "bytes",
            "sha256",
            "info_code",
            "detail_url",
            "pdf_url",
            "source",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "company": COMPANY,
        "stock_code": CODE,
        "as_of": AS_OF,
        "document_count": len(records),
        "selection_method": "公开完整PDF中精选公司深度或首次覆盖报告",
        "documents": records,
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{record['sha256']}  {record['relative_path']}" for record in records) + "\n",
        encoding="utf-8",
    )

    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=f"{ROOT.name}/{path.relative_to(ROOT).as_posix()}")

    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC test failed at {bad}")
        pdf_count = sum(name.lower().endswith(".pdf") for name in archive.namelist())
        if pdf_count != len(records):
            raise RuntimeError(f"ZIP PDF count mismatch: {pdf_count} != {len(records)}")

    print("FINAL_ZIP", ZIP_PATH.name, ZIP_PATH.stat().st_size, sha256_file(ZIP_PATH), flush=True)
    print("FINAL_RECORDS", json.dumps(records, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
