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

COMPANY = "中孚信息"
CODE = "300659"
AS_OF = "2026-10-04"
ROOT = Path(f"{COMPANY}_{CODE}_券商研究报告_2份_20261004")
REPORT_DIR = ROOT / "01_券商研究报告"
VERIFY_DIR = Path("_verify_zhongfu_reports")
ZIP_PATH = Path(f"{COMPANY}_{CODE}_券商研究报告_2份_20261004.zip")

REPORTS = [
    {
        "publish_date": "2021-09-14",
        "institution": "开源证券",
        "analysts": "陈宝健、刘逍遥",
        "rating": "买入（首次）",
        "title": "公司首次覆盖报告：从“保密安全”走向“数字安全”，长期成长路径逐渐清晰",
        "info_code": "AP202109141516192301",
        "detail_url": "https://data.eastmoney.com/report/info/AP202109141516192301.html",
        "pdf_url": "https://pdf.dfcfw.com/pdf/H3_AP202109141516192301_1.pdf",
        "expected_pages": 16,
        "filename": "20210914_开源证券_公司首次覆盖报告_从保密安全走向数字安全.pdf",
        "selection_note": "正式首次覆盖报告，系统梳理保密安全、数字安全、行业政策、成长逻辑及风险。",
    },
    {
        "publish_date": "2022-04-08",
        "institution": "西南证券",
        "analysts": "王湘杰",
        "rating": "增持",
        "title": "营收持续高增长，政策推动行业高景气",
        "info_code": "AP202204081557973891",
        "detail_url": "https://data.eastmoney.com/report/info/AP202204081557973891.html",
        "pdf_url": "https://pdf.dfcfw.com/pdf/H3_AP202204081557973891_1.pdf",
        "expected_pages": 9,
        "filename": "20220408_西南证券_营收持续高增长_政策推动行业高景气.pdf",
        "selection_note": "完整公司研究报告，覆盖业绩、信创与保密政策驱动、盈利预测及估值。",
    },
]

REPORT_DIR.mkdir(parents=True, exist_ok=True)
VERIFY_DIR.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://data.eastmoney.com/",
    }
)


def request_with_retry(url: str, **kwargs: Any) -> requests.Response:
    last: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = session.get(url, timeout=(20, 180), allow_redirects=True, **kwargs)
            print("HTTP", attempt, response.status_code, response.headers.get("content-type"), len(response.content), response.url, flush=True)
            if response.status_code in {429, 500, 502, 503, 504}:
                time.sleep(attempt * 2)
                continue
            response.raise_for_status()
            return response
        except Exception as exc:
            last = exc
            if attempt < 5:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Request failed: {url}: {last}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_sample_text(reader: PdfReader) -> str:
    indices = sorted(set([0, 1, 2, max(0, len(reader.pages) - 1)]))
    parts: list[str] = []
    for idx in indices:
        try:
            parts.append(reader.pages[idx].extract_text() or "")
        except Exception:
            pass
    return "\n".join(parts)


def validate_pdf(path: Path, expected_pages: int) -> dict[str, Any]:
    if not path.read_bytes()[:5] == b"%PDF-":
        raise RuntimeError(f"Invalid PDF header: {path.name}")
    if path.stat().st_size < 100_000:
        raise RuntimeError(f"Suspiciously small PDF: {path.name}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages != expected_pages:
        raise RuntimeError(f"Page-count mismatch for {path.name}: {pages} != {expected_pages}")

    text = extract_sample_text(reader)
    normalized = re.sub(r"\s+", "", text).lower()
    identity_ok = any(term.lower() in normalized for term in ("中孚信息", "300659", "zhongfu"))
    if len(normalized) > 200 and not identity_ok:
        raise RuntimeError(f"Company identity not found in extractable sample: {path.name}")

    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=120)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {qpdf.stdout}\n{qpdf.stderr}")

    for label, page_no in (("first", 1), ("last", pages)):
        outbase = VERIFY_DIR / f"{path.stem}_{label}"
        render = subprocess.run(
            [
                "pdftoppm", "-png", "-r", "72", "-f", str(page_no), "-l", str(page_no),
                "-singlefile", str(path), str(outbase),
            ],
            capture_output=True, text=True, timeout=180,
        )
        png = Path(str(outbase) + ".png")
        if render.returncode != 0 or not png.exists() or png.stat().st_size < 1_000:
            raise RuntimeError(f"Render validation failed for {path.name} page {page_no}: {render.stderr}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "first_last_page_rendered": True,
        "identity_text_verified_when_extractable": bool(identity_ok or len(normalized) <= 200),
    }


def main() -> None:
    records: list[dict[str, Any]] = []
    for report in REPORTS:
        # Confirm the public landing page remains accessible and contains the report id/title.
        detail = request_with_retry(report["detail_url"])
        detail_text = detail.text
        if report["info_code"] not in detail.url and report["title"].split("：")[-1][:8] not in detail_text:
            raise RuntimeError(f"Unable to verify report landing page: {report['title']}")

        pdf = request_with_retry(report["pdf_url"], headers={"Accept": "application/pdf,*/*"})
        path = REPORT_DIR / report["filename"]
        path.write_bytes(pdf.content)
        validation = validate_pdf(path, int(report["expected_pages"]))
        record = {
            "relative_path": path.relative_to(ROOT).as_posix(),
            "filename": path.name,
            "company": COMPANY,
            "stock_code": CODE,
            **report,
            **validation,
            "source": "东方财富研报中心公开PDF端点",
        }
        records.append(record)
        print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

    readme = f"""中孚信息股份有限公司（证券简称：中孚信息；证券代码：{CODE}）券商研究报告包

资料整理日期：{AS_OF}

收录原则：
1. 仅收录公开可直接下载、来源可核验的完整PDF。
2. 优先保留首次覆盖或篇幅相对完整的公司研究；未使用3—5页的季度点评凑数。
3. 本包最终收录2份，符合用户要求的2—3份范围。

收录文件：
- 开源证券，2021-09-14，16页：《公司首次覆盖报告：从“保密安全”走向“数字安全”，长期成长路径逐渐清晰》。
- 西南证券，2022-04-08，9页：《营收持续高增长，政策推动行业高景气》。

来源：东方财富研报中心公开详情页及其公开PDF端点。
校验：PDF文件头、实际页数、公司身份文本（可提取时）、qpdf结构、首页与末页渲染、SHA-256及ZIP CRC。

报告版权归相应证券研究机构及作者所有，仅供个人研究参考，不构成投资建议。
"""
    (ROOT / "00_文件清单与来源说明.txt").write_text(readme, encoding="utf-8")

    with (ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = [
            "relative_path", "institution", "publish_date", "title", "analysts", "rating",
            "pages", "bytes", "sha256", "detail_url", "pdf_url", "info_code", "selection_note",
        ]
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "company": COMPANY,
        "stock_code": CODE,
        "as_of": AS_OF,
        "scope": "公开可直接下载的完整券商公司研究报告2份",
        "documents": records,
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{r['sha256']}  {r['relative_path']}" for r in records) + "\n",
        encoding="utf-8",
    )

    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=f"{ROOT.name}/{path.relative_to(ROOT).as_posix()}")

    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")
        pdf_count = sum(name.lower().endswith(".pdf") for name in zf.namelist())
        if pdf_count != 2:
            raise RuntimeError(f"Unexpected PDF count in ZIP: {pdf_count}")

    print("FINAL_ZIP", ZIP_PATH.name, ZIP_PATH.stat().st_size, sha256_file(ZIP_PATH), flush=True)
    print("FINAL_RECORDS", json.dumps(records, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
