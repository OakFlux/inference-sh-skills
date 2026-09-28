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

COMPANY = "中新赛克"
CODE = "002912"
AS_OF = "2026-09-29"
ROOT = Path(f"{COMPANY}_{CODE}_券商深度报告")
VERIFY_DIR = Path("_verify_zhongxin_saike_broker")
ZIP_NAME = f"{COMPANY}_{CODE}_券商深度报告_3份_20260929.zip"
ROOT.mkdir(parents=True, exist_ok=True)
VERIFY_DIR.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://data.eastmoney.com/",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
)
REPORT_API = "https://reportapi.eastmoney.com/report/list"
PDF_TEMPLATE = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def request_with_retry(url: str, *, params: dict[str, Any] | None = None) -> requests.Response:
    last: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = SESSION.get(url, params=params, timeout=(20, 180), allow_redirects=True)
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
            response.raise_for_status()
            return response
        except Exception as exc:
            last = exc
            if attempt < 5:
                time.sleep(attempt * 2)
    raise RuntimeError(f"GET failed after retries: {url}: {last}")


def parse_json_or_jsonp(text: str) -> Any:
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)
    match = re.search(r"^[^(]+\((.*)\)\s*;?$", text, flags=re.S)
    if not match:
        raise RuntimeError(f"Unexpected Eastmoney payload prefix: {text[:120]!r}")
    return json.loads(match.group(1))


def list_reports() -> list[dict[str, Any]]:
    all_records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(1, 8):
        params = {
            "industryCode": "*",
            "pageSize": "100",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": "2017-01-01",
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
        response = request_with_retry(REPORT_API, params=params)
        payload = parse_json_or_jsonp(response.text)
        page_records: Any = []
        if isinstance(payload, dict):
            page_records = payload.get("data") or payload.get("Data") or payload.get("result") or []
            if isinstance(page_records, dict):
                page_records = page_records.get("data") or page_records.get("list") or []
        elif isinstance(payload, list):
            page_records = payload
        if not isinstance(page_records, list):
            raise RuntimeError(f"Unexpected report list shape: {type(page_records)}")
        print("REPORT_PAGE", page, len(page_records), flush=True)
        if not page_records:
            break
        for item in page_records:
            if not isinstance(item, dict):
                continue
            info_code = str(item.get("infoCode") or "")
            if info_code and info_code not in seen:
                seen.add(info_code)
                all_records.append(dict(item))
        if len(page_records) < 100:
            break
    print("REPORT_COUNT", len(all_records), flush=True)
    for item in all_records:
        print(
            "REPORT",
            str(item.get("publishDate") or "")[:10],
            item.get("orgSName"),
            item.get("attachPages"),
            item.get("infoCode"),
            item.get("title"),
            flush=True,
        )
    return all_records


def norm(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def title_score(title: str) -> int:
    t = norm(title)
    score = 0
    for token, points in (
        ("深度报告", 140),
        ("公司深度", 135),
        ("首次覆盖报告", 130),
        ("首次覆盖", 120),
        ("深度研究", 115),
        ("新股覆盖研究", 90),
        ("新股研究", 80),
        ("投资价值分析", 75),
    ):
        if token in t:
            score = max(score, points)
    return score


def report_score(item: dict[str, Any]) -> tuple[int, int, str]:
    title = str(item.get("title") or "")
    pages = int(item.get("attachPages") or 0)
    date = str(item.get("publishDate") or "")[:10]
    # Long-form depth is the primary criterion, then page count and recency.
    return title_score(title) + min(pages, 60) * 2, pages, date


def select_reports(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for item in records:
        pages = int(item.get("attachPages") or 0)
        title = str(item.get("title") or "")
        if pages >= 15 and title_score(title) > 0 and item.get("infoCode"):
            candidates.append(dict(item))

    if len(candidates) < 2:
        # Fallback to the longest company reports when titles do not explicitly say depth/coverage.
        candidates = [
            dict(item)
            for item in records
            if int(item.get("attachPages") or 0) >= 15 and item.get("infoCode")
        ]

    candidates.sort(key=report_score, reverse=True)
    selected: list[dict[str, Any]] = []
    institutions: set[str] = set()
    for item in candidates:
        institution = str(item.get("orgSName") or item.get("orgName") or "未知机构")
        if institution in institutions:
            continue
        selected.append(item)
        institutions.add(institution)
        if len(selected) == 3:
            break

    if len(selected) < 2:
        raise RuntimeError(f"Only {len(selected)} suitable long-form reports found")

    print("SELECTED_COUNT", len(selected), flush=True)
    for item in selected:
        print("SELECTED", json.dumps(item, ensure_ascii=False), flush=True)
    return selected


def safe_filename(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", "", value)
    return value[:175]


def download_pdf(record: dict[str, Any]) -> tuple[Path, str]:
    info_code = str(record["infoCode"])
    url = PDF_TEMPLATE.format(info_code=info_code)
    response = request_with_retry(url)
    data = response.content
    if not data.startswith(b"%PDF"):
        raise RuntimeError(f"Not a PDF for {info_code}: {data[:30]!r}")
    if len(data) < 200_000:
        raise RuntimeError(f"Suspiciously small report PDF: {info_code}, {len(data)} bytes")
    pubdate = str(record.get("publishDate") or "")[:10].replace("-", "")
    institution = safe_filename(str(record.get("orgSName") or record.get("orgName") or "未知机构"))
    title = safe_filename(str(record.get("title") or info_code))
    path = ROOT / f"{pubdate}_{institution}_{title}.pdf"
    path.write_bytes(data)
    return path, url


def validate_pdf(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 15:
        raise RuntimeError(f"Report is not long-form or is incomplete: {path.name}, {pages} pages")
    expected_pages = int(record.get("attachPages") or 0)
    if expected_pages and abs(pages - expected_pages) > 1:
        raise RuntimeError(f"Page mismatch for {path.name}: actual={pages}, API={expected_pages}")

    samples: list[str] = []
    for idx in sorted(set([0, 1, 2, max(0, pages // 2), pages - 1])):
        try:
            samples.append(reader.pages[idx].extract_text() or "")
        except Exception:
            pass
    sample_text = "\n".join(samples).lower()
    identity_terms = ("中新赛克", "002912", "sinovatio", "赛克")
    identity_ok = any(term.lower() in sample_text for term in identity_terms)
    if len(sample_text.strip()) > 300 and not identity_ok:
        raise RuntimeError(f"Company identity not found in {path.name}")

    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=180
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf validation failed for {path.name}: {qpdf.stderr}")

    for page_no, suffix in ((1, "first"), (pages, "last")):
        out_base = VERIFY_DIR / f"{path.stem}_{suffix}"
        result = subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-r",
                "72",
                "-f",
                str(page_no),
                "-l",
                str(page_no),
                "-singlefile",
                str(path),
                str(out_base),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        png = Path(str(out_base) + ".png")
        if result.returncode != 0 or not png.exists() or png.stat().st_size < 1000:
            raise RuntimeError(f"Render validation failed for {path.name} page {page_no}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "first_last_page_rendered": True,
        "identity_text_verified_when_extractable": bool(identity_ok or len(sample_text.strip()) <= 300),
    }


def main() -> None:
    records = list_reports()
    selected = select_reports(records)
    output_records: list[dict[str, Any]] = []

    for record in selected:
        path, pdf_url = download_pdf(record)
        validation = validate_pdf(path, record)
        output = {
            "filename": path.name,
            "title": str(record.get("title") or ""),
            "institution": str(record.get("orgSName") or record.get("orgName") or ""),
            "analysts": str(record.get("researcher") or ""),
            "publish_date": str(record.get("publishDate") or "")[:10],
            "rating": str(record.get("emRatingName") or record.get("sRatingName") or ""),
            "info_code": str(record.get("infoCode") or ""),
            "eastmoney_detail_url": f"https://data.eastmoney.com/report/info/{record.get('infoCode')}.html",
            "pdf_url": pdf_url,
            **validation,
        }
        output_records.append(output)
        print("PACKAGED", json.dumps(output, ensure_ascii=False), flush=True)

    if len(output_records) not in (2, 3):
        raise RuntimeError(f"Expected 2 or 3 reports, got {len(output_records)}")
    if len({r["sha256"] for r in output_records}) != len(output_records):
        raise RuntimeError("Duplicate PDF content detected")

    readme_lines = [
        f"{COMPANY}（{CODE}）券商深度报告文件包",
        "",
        f"整理日期：{AS_OF}",
        "",
        "筛选原则：优先收录公开可直接取得的完整公司深度、首次覆盖、深度研究或新股覆盖报告；排除短篇财报点评和零散预览页。",
        "",
        "文件清单：",
    ]
    for idx, item in enumerate(output_records, 1):
        readme_lines.extend(
            [
                f"{idx}. {item['institution']}｜{item['title']}",
                f"   日期：{item['publish_date']}；页数：{item['pages']}；评级：{item['rating'] or '未标注'}；分析师：{item['analysts'] or '未标注'}",
                f"   PDF来源：{item['pdf_url']}",
            ]
        )
    readme_lines.extend(
        [
            "",
            "来源：东方财富研报中心公开研报API及公开PDF端点。",
            "版权说明：报告版权归相应证券研究机构及作者所有，本文件包仅供个人研究使用，不构成投资建议。",
        ]
    )
    (ROOT / "00_文件清单与来源说明.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

    with (ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(output_records[0].keys()))
        writer.writeheader()
        writer.writerows(output_records)

    (ROOT / "manifest.json").write_text(
        json.dumps(
            {
                "company": COMPANY,
                "stock_code": CODE,
                "as_of": AS_OF,
                "source": "东方财富研报中心公开API与公开PDF端点",
                "reports": output_records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{r['sha256']}  {r['filename']}" for r in output_records) + "\n",
        encoding="utf-8",
    )

    zip_path = Path(ZIP_NAME)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=f"{ROOT.name}/{path.relative_to(ROOT).as_posix()}")

    with zipfile.ZipFile(zip_path, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC test failed at {bad}")
        pdf_count = sum(name.lower().endswith(".pdf") for name in zf.namelist())
        if pdf_count != len(output_records):
            raise RuntimeError(f"Unexpected PDF count in ZIP: {pdf_count}")

    print("FINAL_ZIP", zip_path.name, zip_path.stat().st_size, sha256_file(zip_path), flush=True)
    print("FINAL_RECORDS", json.dumps(output_records, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
