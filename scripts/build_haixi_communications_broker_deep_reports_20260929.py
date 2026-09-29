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

COMPANY = "海希通讯"
FULL_COMPANY = "上海海希工业通讯股份有限公司"
CURRENT_CODE = "920405"
FORMER_CODE = "831305"
AS_OF = "2026-09-29"
PACKAGE = f"{COMPANY}_{CURRENT_CODE}_券商深度报告_3份_20260929"
ROOT = Path(PACKAGE)
REPORT_DIR = ROOT / "01_券商深度报告"
VERIFY_DIR = Path("_verify_haixi_reports")
ZIP_PATH = Path(f"{PACKAGE}.zip")
REPORT_DIR.mkdir(parents=True, exist_ok=True)
VERIFY_DIR.mkdir(parents=True, exist_ok=True)

REPORTS = [
    {
        "info_code": "AP202601071816300192",
        "title": "工业无线遥控龙头，储能+固态构建增长新动能",
        "institution": "东吴证券",
        "analysts": "朱洁羽、余慧勇、易申申、武阿兰、陈哲晓",
        "publish_date": "2026-01-07",
        "rating": "增持",
        "expected_pages": 27,
        "pdf_url": "https://pdf.dfcfw.com/pdf/H3_AP202601071816300192_1.pdf",
        "detail_url": "https://data.eastmoney.com/report/info/AP202601071816300192.html",
        "selection_note": "最新公司深度报告，重点覆盖工业无线控制、储能和固态电池新业务。",
    },
    {
        "info_code": "AP202512181803099429",
        "title": "北交所首次覆盖报告：储能新引擎已成型，4GW+5GWh在建产能加速转型",
        "institution": "开源证券",
        "analysts": "诸海滨",
        "publish_date": "2025-12-18",
        "rating": "增持（首次）",
        "expected_pages": 31,
        "pdf_url": "https://pdf.dfcfw.com/pdf/H3_AP202512181803099429_1.pdf",
        "detail_url": "https://data.eastmoney.com/report/info/AP202512181803099429.html",
        "selection_note": "首次覆盖长篇报告，系统分析储能需求、扩产项目、盈利预测及风险。",
    },
    {
        "info_code": "AP202111261531266438",
        "title": "深耕无线遥控行业，差异化战略助力品牌发展",
        "institution": "华安证券",
        "analysts": "王莺",
        "publish_date": "2021-11-26",
        "rating": "未评级/公开元数据未列示",
        "expected_pages": 21,
        "pdf_url": "https://pdf.dfcfw.com/pdf/H3_AP202111261531266438_1.pdf",
        "detail_url": "https://data.eastmoney.com/report/info/AP202111261531266438.html",
        "selection_note": "上市初期公司研究，侧重工业无线遥控行业、双品牌战略及竞争格局。",
    },
]

session = requests.Session()
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://data.eastmoney.com/",
    }
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_filename(text: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]", "_", text)
    text = re.sub(r"\s+", "", text)
    return text.strip("._")


def request(url: str, *, accept: str = "*/*") -> requests.Response:
    last: Exception | None = None
    for attempt in range(1, 6):
        try:
            r = session.get(
                url,
                headers={"Accept": accept, "Referer": "https://data.eastmoney.com/"},
                timeout=(20, 180),
                allow_redirects=True,
            )
            print("HTTP", attempt, r.status_code, r.headers.get("content-type"), len(r.content), r.url, flush=True)
            if r.status_code in {429, 500, 502, 503, 504}:
                time.sleep(attempt * 2)
                continue
            r.raise_for_status()
            return r
        except Exception as exc:
            last = exc
            if attempt < 5:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Request failed: {url}: {last}")


def verify_detail_page(report: dict[str, Any]) -> None:
    r = request(report["detail_url"], accept="text/html,*/*")
    text = r.text
    required = [report["title"], report["institution"]]
    missing = [x for x in required if x not in text]
    if missing:
        raise RuntimeError(f"Detail page verification failed for {report['info_code']}: {missing}")
    if report["info_code"] not in text:
        raise RuntimeError(f"Info code missing from detail page for {report['info_code']}")


def download_pdf(report: dict[str, Any], destination: Path) -> None:
    r = request(report["pdf_url"], accept="application/pdf,application/octet-stream,*/*")
    content = r.content
    if not content.startswith(b"%PDF"):
        raise RuntimeError(f"Not a PDF for {report['info_code']}: {content[:32]!r}")
    if len(content) < 100_000:
        raise RuntimeError(f"PDF too small for {report['info_code']}: {len(content)}")
    destination.write_bytes(content)


def validate_pdf(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages != int(report["expected_pages"]):
        raise RuntimeError(f"Page count mismatch for {path.name}: {pages} != {report['expected_pages']}")

    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=180)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {qpdf.stderr[-2000:]}")

    sample_indices = sorted(set([0, 1, 2, max(0, pages - 1)]))
    sample = []
    for idx in sample_indices:
        try:
            sample.append(reader.pages[idx].extract_text() or "")
        except Exception:
            pass
    sample_text = "\n".join(sample)
    identity_terms = ("海希通讯", "920405", "831305", "上海海希")
    identity_ok = any(term in sample_text for term in identity_terms)
    if len(sample_text.strip()) > 300 and not identity_ok:
        raise RuntimeError(f"Company identity not found in extractable sample: {path.name}")

    for page_no, suffix in ((1, "first"), (pages, "last")):
        output_base = VERIFY_DIR / f"{path.stem}_{suffix}"
        run = subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-r",
                "90",
                "-f",
                str(page_no),
                "-l",
                str(page_no),
                "-singlefile",
                str(path),
                str(output_base),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        png = Path(str(output_base) + ".png")
        if run.returncode != 0 or not png.exists() or png.stat().st_size < 1000:
            raise RuntimeError(f"Render failed for {path.name} page {page_no}: {run.stderr[-1000:]}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "first_last_page_rendered": True,
        "identity_text_verified_when_extractable": bool(identity_ok or len(sample_text.strip()) <= 300),
    }


def main() -> None:
    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    for report in REPORTS:
        verify_detail_page(report)
        date_compact = report["publish_date"].replace("-", "")
        filename = f"{date_compact}_{report['institution']}_{safe_filename(report['title'])}.pdf"
        destination = REPORT_DIR / filename
        download_pdf(report, destination)
        validation = validate_pdf(destination, report)
        if validation["sha256"] in seen_hashes:
            raise RuntimeError(f"Duplicate PDF detected: {filename}")
        seen_hashes.add(validation["sha256"])
        record = {
            "filename": filename,
            "relative_path": destination.relative_to(ROOT).as_posix(),
            "company": COMPANY,
            "current_stock_code": CURRENT_CODE,
            "former_stock_code": FORMER_CODE,
            **report,
            **validation,
        }
        records.append(record)
        print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

    if len(records) != 3:
        raise RuntimeError(f"Expected 3 reports, got {len(records)}")

    readme_lines = [
        f"{FULL_COMPANY}（证券简称：{COMPANY}；现证券代码：{CURRENT_CODE}；历史证券代码：{FORMER_CODE}）券商深度报告包",
        "",
        f"资料整理日期：{AS_OF}",
        "",
        "收录范围：从公开可直接取得的公司级研究中，优先选取篇幅较长、来源可核验且研究角度互补的3份完整PDF原文。",
        "",
        "文件清单：",
    ]
    for idx, r in enumerate(records, 1):
        readme_lines.extend(
            [
                f"{idx}. {r['institution']}｜《{r['title']}》",
                f"   日期：{r['publish_date']}；页数：{r['pages']}；分析师：{r['analysts']}；评级：{r['rating']}。",
                f"   选取理由：{r['selection_note']}",
                f"   详情页：{r['detail_url']}",
                f"   PDF原文：{r['pdf_url']}",
            ]
        )
    readme_lines.extend(
        [
            "",
            "说明：",
            "1. 三份文件均从东方财富研报中心公开PDF端点取得，未绕过登录、会员或付费限制。",
            "2. 已排除13页的亿渡数据非券商研究，以及篇幅更短或重复度更高的材料。",
            "3. 报告版权归相应证券研究机构及作者所有，仅供个人研究参考，不构成投资建议。",
            "4. 已完成PDF文件头、实际页数、公司身份、qpdf结构及首末页渲染检查，并进行ZIP CRC测试。",
        ]
    )
    (ROOT / "00_文件清单与来源说明.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

    with (ROOT / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as f:
        fields = [
            "filename", "title", "institution", "analysts", "publish_date", "rating",
            "pages", "bytes", "sha256", "info_code", "detail_url", "pdf_url", "selection_note"
        ]
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "company": FULL_COMPANY,
        "short_name": COMPANY,
        "current_stock_code": CURRENT_CODE,
        "former_stock_code": FORMER_CODE,
        "as_of": AS_OF,
        "report_count": len(records),
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
            raise RuntimeError(f"ZIP CRC failed at {bad}")
        pdf_count = sum(name.lower().endswith(".pdf") for name in zf.namelist())
        if pdf_count != 3:
            raise RuntimeError(f"ZIP PDF count mismatch: {pdf_count}")

    print("FINAL_ZIP", ZIP_PATH.name, ZIP_PATH.stat().st_size, sha256_file(ZIP_PATH), flush=True)
    print("FINAL_RECORDS", json.dumps(records, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
