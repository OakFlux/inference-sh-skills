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

COMPANY = "星德胜"
CODE = "603344"
AS_OF = "2026-10-12"
ROOT = Path(f"{COMPANY}_{CODE}_券商研究报告")
REPORT_DIR = ROOT / "01_券商研究报告"
VERIFY_DIR = Path("_verify_xingdesheng_broker_reports")
TEMP_DIR = Path("_xingdesheng_candidate_pdfs")
for directory in (REPORT_DIR, VERIFY_DIR, TEMP_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/155.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://data.eastmoney.com/",
    }
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    referer: str | None = None,
) -> requests.Response:
    headers = {"Referer": referer} if referer else None
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = SESSION.get(
                url,
                params=params,
                headers=headers,
                timeout=(20, 180),
                allow_redirects=True,
            )
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
    raise RuntimeError(f"GET failed: {url}: {last_error}")


def as_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except Exception:
        return 0


def date_only(value: Any) -> str:
    text = str(value or "")
    match = re.search(r"20\d{2}-\d{2}-\d{2}", text)
    return match.group(0) if match else text[:10]


def fetch_reports() -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(1, 6):
        params = {
            "industryCode": "*",
            "pageSize": "100",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": "2024-01-01",
            "endTime": AS_OF,
            "pageNo": str(page),
            "fields": "",
            "qType": "0",
            "orgCode": "",
            "code": CODE,
            "rcode": "",
            "p": str(page),
            "pageNum": str(page),
            "pageNumber": str(page),
        }
        response = get("https://reportapi.eastmoney.com/report/list", params=params)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") or payload.get("Data") or []
        print(
            "REPORT_PAGE",
            page,
            len(rows),
            payload.get("hits"),
            payload.get("TotalPage"),
            flush=True,
        )
        if not rows:
            break
        for row in rows:
            info_code = str(row.get("infoCode") or row.get("info_code") or "")
            if not info_code or info_code in seen:
                continue
            seen.add(info_code)
            report = {
                "info_code": info_code,
                "title": str(row.get("title") or "").strip(),
                "publish_date": date_only(row.get("publishDate") or row.get("publish_date")),
                "institution": str(
                    row.get("orgSName")
                    or row.get("orgName")
                    or row.get("org_name")
                    or ""
                ).strip(),
                "analyst": str(
                    row.get("researcher")
                    or row.get("researcherName")
                    or row.get("author")
                    or ""
                ).strip(),
                "rating": str(row.get("emRatingName") or row.get("rating") or "").strip(),
                "attach_pages": as_int(row.get("attachPages") or row.get("attach_pages")),
                "attach_size": as_int(row.get("attachSize") or row.get("attach_size")),
            }
            reports.append(report)
            print("META", json.dumps(report, ensure_ascii=False), flush=True)
        if len(rows) < 100:
            break
        time.sleep(0.5)
    if not reports:
        raise RuntimeError("No broker-report metadata returned for 603344")
    return reports


def score(report: dict[str, Any]) -> int:
    title = report["title"]
    pages = int(report.get("attach_pages") or 0)
    value = pages * 10
    if any(
        keyword in title
        for keyword in (
            "深度",
            "首次覆盖",
            "公司研究",
            "投资价值",
            "新股",
            "微特电机",
            "电机",
        )
    ):
        value += 450
    if pages >= 25:
        value += 300
    elif pages >= 15:
        value += 190
    elif pages >= 8:
        value += 80
    if any(
        keyword in title
        for keyword in (
            "季报",
            "年报点评",
            "中报点评",
            "业绩点评",
            "业绩预告",
            "快报",
            "简评",
        )
    ):
        value -= 220
    return value


def safe_name(text: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]", "_", text)
    text = re.sub(r"\s+", "", text)
    return text[:110].strip("._")


def download_pdf(report: dict[str, Any]) -> tuple[Path, str, str]:
    info_code = report["info_code"]
    detail_url = f"https://data.eastmoney.com/report/info/{info_code}.html"
    detail = get(detail_url)
    detail.raise_for_status()
    detail_text = detail.text
    if COMPANY not in detail_text and CODE not in detail_text:
        raise RuntimeError(f"Detail-page company identity failed: {info_code}")
    if report["institution"] and report["institution"] not in detail_text:
        raise RuntimeError(f"Detail-page institution identity failed: {info_code}")

    explicit_urls = re.findall(
        r"https?://[^\"']+\.pdf(?:\?[^\"']*)?",
        detail_text,
        flags=re.I,
    )
    generated_urls = [
        f"https://pdf.dfcfw.com/pdf/{prefix}_{info_code}{suffix}"
        for prefix in ("H3", "H1", "H2", "H4", "H5", "H0")
        for suffix in ("_1.pdf", "_2.pdf", "_0.pdf")
    ]
    urls: list[str] = []
    for url in explicit_urls + generated_urls:
        if url not in urls:
            urls.append(url)

    for url in urls:
        response = get(url, referer=detail_url)
        if (
            response.status_code == 200
            and response.content.startswith(b"%PDF")
            and len(response.content) > 100_000
        ):
            path = TEMP_DIR / f"{info_code}.pdf"
            path.write_bytes(response.content)
            return path, response.url, detail_url
    raise RuntimeError(f"No public complete PDF found: {info_code}")


def inspect_pdf(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 6:
        raise RuntimeError(f"Too short for company research: {pages} pages")

    text_parts: list[str] = []
    for index in sorted(set([0, 1, min(2, pages - 1), pages - 1])):
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception:
            pass
    sample = "\n".join(text_parts)
    company_ok = COMPANY in sample or CODE in sample
    institution_ok = not report["institution"] or report["institution"] in sample
    if len(sample.strip()) > 300 and not company_ok:
        raise RuntimeError(f"Company identity absent in PDF sample: {path.name}")
    if len(sample.strip()) > 300 and not institution_ok:
        raise RuntimeError(f"Institution identity absent in PDF sample: {path.name}")

    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {qpdf.stderr}")

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
        if (
            rendered.returncode != 0
            or not png_path.exists()
            or png_path.stat().st_size < 1_000
        ):
            raise RuntimeError(
                f"Page render failed for {path.name}, page {page_number}: {rendered.stderr}"
            )

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "first_last_page_rendered": True,
        "company_text_verified_when_extractable": bool(company_ok or len(sample.strip()) <= 300),
        "institution_text_verified_when_extractable": bool(
            institution_ok or len(sample.strip()) <= 300
        ),
    }


def choose(valid: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid.sort(
        key=lambda item: (
            score(item),
            int(item["pages"]),
            item["publish_date"],
        ),
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    institutions: set[str] = set()
    for item in valid:
        institution = item["institution"] or "未知机构"
        if institution in institutions:
            continue
        selected.append(item)
        institutions.add(institution)
        if len(selected) == 3:
            break
    for item in valid:
        if len(selected) == 3:
            break
        if item["info_code"] not in {chosen["info_code"] for chosen in selected}:
            selected.append(item)
    if not selected:
        raise RuntimeError("No qualifying public full reports were available")
    return selected


def main() -> None:
    reports = fetch_reports()
    ranked = sorted(reports, key=score, reverse=True)

    valid: list[dict[str, Any]] = []
    for report in ranked[:30]:
        try:
            path, pdf_url, detail_url = download_pdf(report)
            metadata = inspect_pdf(path, report)
            item = {
                **report,
                **metadata,
                "temp_path": path,
                "pdf_url": pdf_url,
                "detail_url": detail_url,
            }
            valid.append(item)
            print("VALID", json.dumps(item, ensure_ascii=False, default=str), flush=True)
        except Exception as exc:
            print("FAILED", report["info_code"], repr(exc), flush=True)
        if len(valid) >= 12:
            break

    selected = choose(valid)
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
                "rating": item["rating"],
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
        f"{COMPANY}（{CODE}）券商研究报告精选包",
        "",
        f"资料整理日期：{AS_OF}",
        "",
        "收录口径：仅使用可公开取得的完整PDF；优先选择首次覆盖、公司深度、投资价值分析或篇幅较长、框架较完整的公司研究。",
        "",
        "收录文件：",
    ]
    for record in records:
        readme_lines.append(
            f"- {record['publish_date']}｜{record['institution']}｜{record['title']}｜{record['pages']}页"
        )
    if len(records) < 2:
        readme_lines.extend(
            [
                "",
                "说明：公开渠道中仅发现上述1份可以完整下载并完成身份核验的公司研究PDF，未使用网页摘要或受限预览凑数。",
            ]
        )
    readme_lines.extend(
        [
            "",
            "校验项目：PDF文件头、实际页数、公司及券商身份文本（可提取时）、qpdf结构、首末页渲染和ZIP CRC。",
            "报告版权归相应证券研究机构及作者所有，仅供个人研究参考，不构成投资建议。",
        ]
    )
    (ROOT / "00_文件清单与来源说明.txt").write_text(
        "\n".join(readme_lines) + "\n",
        encoding="utf-8",
    )

    with (ROOT / "文件清单.csv").open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        fieldnames = [
            "relative_path",
            "publish_date",
            "institution",
            "analyst",
            "title",
            "rating",
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
        "selection_method": "公开完整PDF中按深度适配、页数、机构差异及日期精选最多3份",
        "documents": records,
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{record['sha256']}  {record['relative_path']}" for record in records)
        + "\n",
        encoding="utf-8",
    )

    count = len(records)
    zip_path = Path(f"{COMPANY}_{CODE}_券商研究报告_{count}份_20261012.zip")
    with zipfile.ZipFile(
        zip_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(
                    path,
                    arcname=f"{ROOT.name}/{path.relative_to(ROOT).as_posix()}",
                )
    with zipfile.ZipFile(zip_path, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failed at {bad}")
        pdf_count = sum(name.lower().endswith(".pdf") for name in archive.namelist())
        if pdf_count != count:
            raise RuntimeError(f"ZIP PDF count mismatch: {pdf_count} != {count}")

    print(
        "FINAL_ZIP",
        zip_path.name,
        zip_path.stat().st_size,
        sha256_file(zip_path),
        flush=True,
    )
    print("FINAL_RECORDS", json.dumps(records, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
