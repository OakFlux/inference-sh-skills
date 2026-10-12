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

COMPANY = "安恒信息"
CODE = "688023"
AS_OF = "2026-10-12"
ROOT = Path(f"{COMPANY}_{CODE}_券商深度报告")
REPORT_DIR = ROOT / "01_券商深度报告"
VERIFY_DIR = Path("_verify_anheng_broker_reports")
TEMP_DIR = Path("_anheng_broker_candidate_pdfs")
for directory in (REPORT_DIR, VERIFY_DIR, TEMP_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/155.0.0.0 Safari/537.36"
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
    for page in range(1, 8):
        params = {
            "industryCode": "*",
            "pageSize": "100",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": "2019-01-01",
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
                "publish_date": date_only(
                    row.get("publishDate") or row.get("publish_date")
                ),
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
                "rating": str(
                    row.get("emRatingName") or row.get("rating") or ""
                ).strip(),
                "attach_pages": as_int(
                    row.get("attachPages") or row.get("attach_pages")
                ),
                "attach_size": as_int(
                    row.get("attachSize") or row.get("attach_size")
                ),
            }
            reports.append(report)
            print("META", json.dumps(report, ensure_ascii=False), flush=True)
        if len(rows) < 100:
            break
        time.sleep(0.5)
    if not reports:
        raise RuntimeError("No report metadata returned")
    return reports


def report_score(report: dict[str, Any]) -> int:
    title = report["title"]
    pages = int(report.get("attach_pages") or 0)
    score = pages * 15

    if any(
        keyword in title
        for keyword in (
            "深度",
            "首次覆盖",
            "公司研究",
            "投资价值",
            "龙头",
            "领军",
            "先锋",
            "新星",
            "成长空间",
        )
    ):
        score += 400
    if pages >= 30:
        score += 350
    elif pages >= 20:
        score += 260
    elif pages >= 12:
        score += 120

    if any(
        keyword in title
        for keyword in (
            "季报",
            "年报点评",
            "中报点评",
            "业绩点评",
            "快报",
            "简评",
            "点评",
            "跟踪报告",
        )
    ):
        score -= 320

    year = as_int(report.get("publish_date", "")[:4])
    score += max(0, year - 2018) * 5
    return score


def safe_name(text: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]", "_", text)
    return re.sub(r"\s+", "", text)[:110].strip("._")


def download_pdf(report: dict[str, Any]) -> tuple[Path, str, str]:
    info_code = report["info_code"]
    detail_url = f"https://data.eastmoney.com/report/info/{info_code}.html"
    detail = get(detail_url)
    detail.raise_for_status()
    if COMPANY not in detail.text or CODE not in detail.text:
        raise RuntimeError(f"Detail identity failed: {info_code}")
    if report["institution"] and report["institution"] not in detail.text:
        raise RuntimeError(f"Institution identity failed: {info_code}")

    explicit_urls = re.findall(
        r"https?://[^\"']+\.pdf(?:\?[^\"']*)?",
        detail.text,
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
    raise RuntimeError(f"No public complete PDF: {info_code}")


def inspect_pdf(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 10:
        raise RuntimeError(f"Too short for deep research: {pages} pages")

    text_parts: list[str] = []
    for index in sorted(set([0, 1, min(2, pages - 1), pages - 1])):
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception:
            pass
    sample_text = "\n".join(text_parts)
    company_ok = COMPANY in sample_text or CODE in sample_text
    institution_ok = (
        not report["institution"] or report["institution"] in sample_text
    )
    if len(sample_text.strip()) > 300 and not company_ok:
        raise RuntimeError("Company text absent")
    if len(sample_text.strip()) > 300 and not institution_ok:
        raise RuntimeError("Institution text absent")

    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed: {qpdf.stderr}")

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
            raise RuntimeError(f"Page render failed: page {page_number}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "first_last_page_rendered": True,
        "company_text_verified_when_extractable": bool(
            company_ok or len(sample_text.strip()) <= 300
        ),
        "institution_text_verified_when_extractable": bool(
            institution_ok or len(sample_text.strip()) <= 300
        ),
    }


def select_reports(valid: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid.sort(
        key=lambda item: (
            report_score(item),
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
        if item["info_code"] not in {x["info_code"] for x in selected}:
            selected.append(item)

    if len(selected) < 2:
        raise RuntimeError(f"Only {len(selected)} qualifying reports")
    return selected


def main() -> None:
    reports = fetch_reports()
    ranked = sorted(reports, key=report_score, reverse=True)

    pool: list[dict[str, Any]] = []
    for report in ranked[:40]:
        if report["info_code"] not in {item["info_code"] for item in pool}:
            pool.append(report)

    valid: list[dict[str, Any]] = []
    for report in pool:
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

    chosen = select_reports(valid)
    records: list[dict[str, Any]] = []
    for rank, item in enumerate(chosen, start=1):
        filename = (
            f"{rank:02d}_{item['publish_date'].replace('-', '')}_"
            f"{item['institution']}_{safe_name(item['title'])}.pdf"
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

    lines = [
        f"{COMPANY}（{CODE}）券商深度报告精选包",
        "",
        f"资料整理日期：{AS_OF}",
        "",
        "筛选口径：仅收录公开可取得的完整PDF；优先选取首次覆盖、公司深度或分析框架完整且篇幅较长的报告。",
        "",
        "收录文件：",
    ]
    lines.extend(
        f"- {record['publish_date']}｜{record['institution']}｜"
        f"{record['title']}｜{record['pages']}页"
        for record in records
    )
    lines.extend(
        [
            "",
            "校验项目：PDF文件头、实际页数、公司及券商身份、qpdf结构、首末页渲染和ZIP CRC。",
            "报告版权归相应证券研究机构及作者所有，仅供个人研究参考，不构成投资建议。",
        ]
    )
    (ROOT / "00_文件清单与来源说明.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    with (ROOT / "文件清单.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        fields = [
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
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "company": COMPANY,
        "stock_code": CODE,
        "as_of": AS_OF,
        "selection_method": (
            "公开完整PDF中按深度适配、页数、机构差异和日期精选2至3份"
        ),
        "documents": records,
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(
            f"{record['sha256']}  {record['relative_path']}"
            for record in records
        )
        + "\n",
        encoding="utf-8",
    )

    count = len(records)
    zip_path = Path(f"{COMPANY}_{CODE}_券商深度报告_{count}份_20261012.zip")
    with zipfile.ZipFile(
        zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
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
        pdf_count = sum(
            name.lower().endswith(".pdf") for name in archive.namelist()
        )
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
