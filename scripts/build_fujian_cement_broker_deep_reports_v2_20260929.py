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

COMPANY = "福建水泥"
CODE = "600802"
AS_OF = "2026-09-29"
ROOT = Path(f"{COMPANY}_{CODE}_券商深度报告_2份")
VERIFY_DIR = Path("_verify_fujian_cement_broker_v2")
ZIP_NAME = f"{COMPANY}_{CODE}_券商深度报告_2份_20260929.zip"
ROOT.mkdir(parents=True, exist_ok=True)
VERIFY_DIR.mkdir(parents=True, exist_ok=True)

REPORTS = [
    {
        "info_code": "AP201206050005274029",
        "publish_date": "2012-06-05",
        "institution": "宏源证券",
        "analysts": "邓海清、沈荣、黄立军",
        "title": "区域整合的领头羊，海峡经济区奠定未来需求",
        "expected_pages": 28,
        "rating": "未在文件清单中强行推断",
    },
    {
        "info_code": "AP201407180006381375",
        "publish_date": "2014-07-18",
        "institution": "宏源证券",
        "analysts": "顾益辉、王钦",
        "title": "畅享海西建设，整合促盈利回升",
        "expected_pages": 13,
        "rating": "增持",
    },
]

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        "Referer": "https://data.eastmoney.com/",
        "Accept": "application/pdf,text/html,*/*",
    }
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_filename(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", "", value)
    return value[:180]


def get_with_retry(url: str) -> requests.Response:
    last: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = SESSION.get(url, timeout=(20, 180), allow_redirects=True)
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


def download_and_validate(report: dict[str, Any]) -> dict[str, Any]:
    code = report["info_code"]
    detail_url = f"https://data.eastmoney.com/report/info/{code}.html"
    pdf_url = f"https://pdf.dfcfw.com/pdf/H3_{code}_1.pdf"

    detail = get_with_retry(detail_url)
    detail_text = detail.text
    if report["title"] not in detail_text:
        raise RuntimeError(f"Detail page title mismatch for {code}")
    if report["institution"] not in detail_text:
        raise RuntimeError(f"Detail page institution mismatch for {code}")
    for analyst in report["analysts"].split("、"):
        if analyst and analyst not in detail_text:
            raise RuntimeError(f"Detail page analyst mismatch for {code}: {analyst}")

    response = get_with_retry(pdf_url)
    data = response.content
    if not data.startswith(b"%PDF") or len(data) < 200_000:
        raise RuntimeError(f"Invalid PDF payload for {code}: {len(data)} bytes")

    filename = (
        f"{report['publish_date'].replace('-', '')}_{safe_filename(report['institution'])}_"
        f"{safe_filename(report['title'])}.pdf"
    )
    path = ROOT / filename
    path.write_bytes(data)

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages != int(report["expected_pages"]):
        raise RuntimeError(
            f"Page count mismatch for {code}: actual={pages}, expected={report['expected_pages']}"
        )

    sample_text_parts: list[str] = []
    for idx in sorted(set([0, 1, 2, pages // 2, pages - 1])):
        try:
            sample_text_parts.append(reader.pages[idx].extract_text() or "")
        except Exception:
            pass
    sample_text = "\n".join(sample_text_parts).lower()
    identity_ok = any(term in sample_text for term in ("福建水泥", "600802", "fujian cement"))
    if len(sample_text.strip()) > 300 and not identity_ok:
        raise RuntimeError(f"Company identity not found in extractable text: {filename}")

    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=180
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf validation failed for {filename}: {qpdf.stderr}")

    for page_no, suffix in ((1, "first"), (pages, "last")):
        base = VERIFY_DIR / f"{path.stem}_{suffix}"
        rendered = subprocess.run(
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
                str(base),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        png = Path(str(base) + ".png")
        if rendered.returncode != 0 or not png.exists() or png.stat().st_size < 1000:
            raise RuntimeError(f"Render check failed for {filename}, page {page_no}")

    return {
        "filename": filename,
        "title": report["title"],
        "institution": report["institution"],
        "analysts": report["analysts"],
        "publish_date": report["publish_date"],
        "rating": report["rating"],
        "info_code": code,
        "detail_url": detail_url,
        "pdf_url": pdf_url,
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "first_last_page_rendered": True,
        "identity_text_verified_when_extractable": bool(identity_ok or len(sample_text.strip()) <= 300),
    }


def main() -> None:
    records = [download_and_validate(report) for report in REPORTS]
    if len(records) != 2 or len({r["sha256"] for r in records}) != 2:
        raise RuntimeError("Report count or duplicate-content validation failed")

    readme_lines = [
        f"{COMPANY}（{CODE}）券商深度报告文件包",
        "",
        f"整理日期：{AS_OF}",
        "",
        "收录口径：从东方财富个股日历及研报详情页回溯历史公司研究，选择公开可完整下载且达到10页以上的长篇报告。",
        "检索结果：公开档案中达到该标准的文件为2份；其他可核验历史材料大多只有2—7页，未混入本包凑数。",
        "",
        "文件清单：",
    ]
    for i, r in enumerate(records, 1):
        readme_lines.extend(
            [
                f"{i}. {r['institution']}｜《{r['title']}》",
                f"   日期：{r['publish_date']}；分析师：{r['analysts']}；页数：{r['pages']}；评级：{r['rating']}",
                f"   研报详情：{r['detail_url']}",
                f"   PDF原文：{r['pdf_url']}",
            ]
        )
    readme_lines.extend(
        [
            "",
            "校验：PDF文件头、实际页数、公司身份、qpdf结构、首末页渲染、文件哈希及ZIP CRC。",
            "版权与使用说明：报告版权归相应证券研究机构及作者所有，仅作个人研究和资料整理使用，不构成投资建议。",
        ]
    )
    (ROOT / "00_文件清单与来源说明.txt").write_text(
        "\n".join(readme_lines) + "\n", encoding="utf-8"
    )

    with (ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)

    (ROOT / "manifest.json").write_text(
        json.dumps(
            {
                "company": COMPANY,
                "stock_code": CODE,
                "as_of": AS_OF,
                "report_count": len(records),
                "source": "东方财富个股日历、研报详情页及公开PDF端点",
                "reports": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{r['sha256']}  {r['filename']}" for r in records) + "\n",
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
        if pdf_count != 2:
            raise RuntimeError(f"Unexpected PDF count in ZIP: {pdf_count}")

    print("FINAL_ZIP", zip_path.name, zip_path.stat().st_size, sha256_file(zip_path), flush=True)
    print("FINAL_RECORDS", json.dumps(records, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
