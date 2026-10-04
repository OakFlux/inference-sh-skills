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

COMPANY = "普蕊斯"
CODE = "301257"
AS_OF = "2026-10-04"
ROOT = Path(f"{COMPANY}_{CODE}_券商深度报告_3份")
REPORT_DIR = ROOT / "01_券商深度报告"
VERIFY_DIR = Path("_verify_puruisi_broker_reports")
ZIP_PATH = Path(f"{COMPANY}_{CODE}_券商深度报告_3份_20261004.zip")

for d in (REPORT_DIR, VERIFY_DIR):
    d.mkdir(parents=True, exist_ok=True)

CANDIDATES: list[dict[str, Any]] = [
    {
        "info_code": "AP202310301605950414",
        "publish_date": "2023-10-30",
        "institution": "华鑫证券",
        "analyst": "胡博新",
        "title": "公司深度报告：SMO-研发临床阶段不可或缺的纽带",
        "type": "公司深度报告/首次覆盖",
        "priority": 100,
    },
    {
        "info_code": "AP202310181602003487",
        "publish_date": "2023-10-18",
        "institution": "信达证券",
        "analyst": "唐爱金、史慧颖",
        "title": "公司首次覆盖报告：行业高速发展，行业集中度提升+规模效益驱动SMO龙头高成长",
        "type": "首次覆盖报告",
        "priority": 95,
    },
    {
        "info_code": "AP202306281591769559",
        "publish_date": "2023-06-28",
        "institution": "国金证券",
        "analyst": "袁维",
        "title": "SMO行业先行者，复苏+规模效应共促业绩高增",
        "type": "首次覆盖/公司深度",
        "priority": 90,
    },
    {
        "info_code": "AP202308111594120810",
        "publish_date": "2023-08-11",
        "institution": "开源证券",
        "analyst": "蔡明子、余汝意、汪晋",
        "title": "公司首次覆盖报告：中国SMO领军企业，充沛订单保障高增长",
        "type": "首次覆盖报告",
        "priority": 85,
    },
    {
        "info_code": "AP202211021579801199",
        "publish_date": "2022-11-02",
        "institution": "国元证券",
        "analyst": "马云涛",
        "title": "首次覆盖报告：专注的SMO专家，充沛订单保障高增长",
        "type": "首次覆盖报告",
        "priority": 80,
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
    headers = {}
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
    return value[:100].strip("._")


def resolve_pdf(report: dict[str, Any]) -> tuple[bytes, str, str]:
    info_code = report["info_code"]
    detail_url = f"https://data.eastmoney.com/report/info/{info_code}.html"
    detail = request(detail_url)
    detail_text = detail.text
    if report["title"].replace("+", "")[:8] not in detail_text.replace("+", ""):
        raise RuntimeError(f"Title validation failed for {info_code}")
    if COMPANY not in detail_text or CODE not in detail_text:
        raise RuntimeError(f"Company identity missing from detail page for {info_code}")
    if report["institution"] not in detail_text:
        raise RuntimeError(f"Institution missing from detail page for {info_code}")

    explicit_urls = re.findall(r"https?://[^\"']+\.pdf", detail_text, flags=re.I)
    generated_urls: list[str] = []
    for host_prefix in ("H3", "H1", "H2", "H4", "H5", "H0"):
        for suffix in ("_1.pdf", "_2.pdf", "_0.pdf"):
            generated_urls.append(f"https://pdf.dfcfw.com/pdf/{host_prefix}_{info_code}{suffix}")
    urls: list[str] = []
    for url in explicit_urls + generated_urls:
        if url not in urls:
            urls.append(url)

    for url in urls:
        response = request(url, referer=detail_url)
        if response.status_code == 200 and response.content.startswith(b"%PDF") and len(response.content) > 100_000:
            return response.content, url, detail_url
    raise RuntimeError(f"No public complete PDF found for {info_code}")


def inspect_pdf(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 8:
        raise RuntimeError(f"Report is too short to qualify as deep research: {path.name}: {pages} pages")

    sample_indices = sorted(set([0, 1, min(2, pages - 1), pages - 1]))
    text_parts: list[str] = []
    for index in sample_indices:
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception:
            pass
    sample_text = "\n".join(text_parts)
    identity_ok = COMPANY in sample_text or CODE in sample_text
    institution_ok = report["institution"] in sample_text
    if len(sample_text.strip()) > 300 and not identity_ok:
        raise RuntimeError(f"Company identity not found in extractable sample: {path.name}")
    if len(sample_text.strip()) > 300 and not institution_ok:
        raise RuntimeError(f"Institution identity not found in extractable sample: {path.name}")

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
        "company_text_verified_when_extractable": bool(identity_ok or len(sample_text.strip()) <= 300),
        "institution_text_verified_when_extractable": bool(institution_ok or len(sample_text.strip()) <= 300),
    }


def main() -> None:
    downloaded: list[dict[str, Any]] = []
    temp_dir = Path("_puruisi_candidate_pdfs")
    temp_dir.mkdir(exist_ok=True)

    for report in CANDIDATES:
        try:
            content, pdf_url, detail_url = resolve_pdf(report)
            temp_path = temp_dir / f"{report['info_code']}.pdf"
            temp_path.write_bytes(content)
            metadata = inspect_pdf(temp_path, report)
            downloaded.append(
                {
                    **report,
                    **metadata,
                    "pdf_url": pdf_url,
                    "detail_url": detail_url,
                    "temp_path": temp_path,
                }
            )
            print("CANDIDATE_VALID", json.dumps(downloaded[-1], ensure_ascii=False, default=str), flush=True)
        except Exception as exc:
            print("CANDIDATE_FAILED", report["info_code"], repr(exc), flush=True)

    if len(downloaded) < 3:
        raise RuntimeError(f"Only {len(downloaded)} qualifying public full reports were available")

    # Deep-report suitability first, then page depth, then recency/curation priority.
    downloaded.sort(
        key=lambda item: (
            int(item["pages"]),
            int(item["priority"]),
            item["publish_date"],
        ),
        reverse=True,
    )
    selected = downloaded[:3]

    records: list[dict[str, Any]] = []
    for rank, item in enumerate(selected, start=1):
        filename = (
            f"{rank:02d}_{item['publish_date'].replace('-', '')}_{item['institution']}_"
            f"{safe_name(item['title'])}.pdf"
        )
        destination = REPORT_DIR / filename
        shutil.copy2(item["temp_path"], destination)
        record = {
            "relative_path": destination.relative_to(ROOT).as_posix(),
            "filename": destination.name,
            "company": COMPANY,
            "stock_code": CODE,
            "publish_date": item["publish_date"],
            "institution": item["institution"],
            "analyst": item["analyst"],
            "title": item["title"],
            "report_type": item["type"],
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
        records.append(record)

    alternates = [
        {
            "publish_date": item["publish_date"],
            "institution": item["institution"],
            "title": item["title"],
            "pages": item["pages"],
            "info_code": item["info_code"],
            "detail_url": item["detail_url"],
        }
        for item in downloaded[3:]
    ]

    readme_lines = [
        f"{COMPANY}（{CODE}）券商深度报告精选包",
        "",
        f"资料整理日期：{AS_OF}",
        "",
        "筛选口径：",
        "1. 仅收录可公开取得的完整PDF，不使用网页摘要、预览页或受限附件冒充全文。",
        "2. 优先选择公司深度、首次覆盖或具有完整行业与公司分析框架的长篇报告。",
        "3. 在符合深度报告条件的候选中，综合实际页数、机构差异和报告日期选取3份。",
        "",
        "收录文件：",
    ]
    for record in records:
        readme_lines.append(
            f"- {record['publish_date']}｜{record['institution']}｜{record['title']}｜{record['pages']}页"
        )
    if alternates:
        readme_lines.extend(["", "已核验但未收录的备选报告："])
        for item in alternates:
            readme_lines.append(
                f"- {item['publish_date']}｜{item['institution']}｜{item['title']}｜{item['pages']}页"
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
        "selection_method": "公开完整PDF候选中按深度适配、实际页数、机构差异和日期精选3份",
        "documents": records,
        "validated_alternates_not_included": alternates,
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{r['sha256']}  {r['relative_path']}" for r in records) + "\n",
        encoding="utf-8",
    )

    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=f"{ROOT.name}/{path.relative_to(ROOT).as_posix()}")

    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")
        pdf_count = sum(name.lower().endswith(".pdf") for name in archive.namelist())
        if pdf_count != 3:
            raise RuntimeError(f"Expected 3 PDFs in ZIP, found {pdf_count}")

    print("FINAL_ZIP", ZIP_PATH.name, ZIP_PATH.stat().st_size, sha256_file(ZIP_PATH), flush=True)
    print("FINAL_RECORDS", json.dumps(records, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
