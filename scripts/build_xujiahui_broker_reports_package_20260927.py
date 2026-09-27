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

PACKAGE = "徐家汇_002561_券商研究报告精选_3份"
ROOT = Path(PACKAGE)
REPORTS_DIR = ROOT / "01_券商研究报告"
VERIFY_DIR = ROOT / "02_说明与校验"
WORK_DIR = Path("_xujiahui_broker_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (REPORTS_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

TARGETS: list[dict[str, Any]] = [
    {
        "date": "2015-08-20",
        "institution": "中泰证券",
        "authors": ["胡彦超"],
        "type": "公司深度研究",
        "title": "优质商圈+高盈利能力+高分红",
        "stock": "徐家汇（002561）",
        "url": "https://public.fxbaogao.com/report/2015/08/20/929115.pdf",
        "source_page": "发现报告公开PDF档案",
        "source_record_id": "929115",
        "destination": REPORTS_DIR / "2015-08-20_中泰证券_徐家汇深度研究_优质商圈高盈利能力高分红.pdf",
        "min_pages": 12,
        "expected_pages": 15,
        "identity_terms": ["徐家汇", "002561"],
        "title_terms": ["优质商圈", "高盈利能力", "高分红"],
        "institution_terms": ["中泰证券", "齐鲁证券"],
    },
    {
        "date": "2016-12-19",
        "institution": "民生证券",
        "authors": ["马科", "赵令伊", "李奇琦"],
        "type": "调研简报",
        "title": "主业经营稳健，持续深化全渠道布局",
        "stock": "徐家汇（002561）",
        "url": "https://public.fxbaogao.com/report/2016/12/19/89805.pdf",
        "source_page": "发现报告公开PDF档案",
        "source_record_id": "89805",
        "destination": REPORTS_DIR / "2016-12-19_民生证券_徐家汇调研简报_主业经营稳健持续深化全渠道布局.pdf",
        "min_pages": 4,
        "expected_pages": 4,
        "identity_terms": ["徐家汇", "002561"],
        "title_terms": ["主业经营稳健", "全渠道布局"],
        "institution_terms": ["民生证券"],
    },
    {
        "date": "2017-03-31",
        "institution": "民生证券",
        "authors": ["马科", "赵令伊", "李奇琦"],
        "type": "年度报告点评",
        "title": "经营稳健，加速推进全渠道融合",
        "stock": "徐家汇（002561）",
        "url": "https://pdf.dfcfw.com/pdf/H3_AP201704010460545465_1.pdf",
        "source_page": "东方财富研究报告公开PDF档案",
        "source_record_id": "AP201704010460545465",
        "destination": REPORTS_DIR / "2017-03-31_民生证券_徐家汇年报点评_经营稳健加速推进全渠道融合.pdf",
        "min_pages": 5,
        "expected_pages": 5,
        "identity_terms": ["徐家汇", "002561"],
        "title_terms": ["经营稳健", "全渠道融合"],
        "institution_terms": ["民生证券"],
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request_pdf(url: str, referer: str) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        headers = dict(BASE_HEADERS)
        headers["Referer"] = referer
        try:
            response = SESSION.get(url, headers=headers, timeout=(25, 360), stream=True, allow_redirects=True)
            print(
                "GET", url, "attempt", attempt, "status", response.status_code,
                "type", response.headers.get("content-type"),
                "length", response.headers.get("content-length"), "final", response.url,
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            time.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"failed to download {url}: {errors[-6:]}")


def download_pdf(target: dict[str, Any]) -> str:
    url = target["url"]
    referer = "https://www.fxbaogao.com/" if "fxbaogao.com" in url else "https://data.eastmoney.com/report/002561.html"
    response = request_pdf(url, referer)
    destination: Path = target["destination"]
    temp = destination.with_suffix(destination.suffix + ".part")
    temp.unlink(missing_ok=True)
    try:
        with temp.open("wb") as fh:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    fh.write(chunk)
        final_url = str(response.url)
    finally:
        response.close()
    head = temp.read_bytes()[:8]
    if temp.stat().st_size < 50_000 or not head.startswith(b"%PDF-"):
        raise RuntimeError(
            f"invalid PDF for {destination.name}: bytes={temp.stat().st_size}, head={head!r}"
        )
    temp.replace(destination)
    return final_url


def render_page(path: Path, page_number: int, suffix: str) -> None:
    prefix = RENDER_DIR / f"{path.stem}_{suffix}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
            "-r", "100", "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=240,
    )
    png = Path(str(prefix) + ".png")
    valid = (
        process.returncode == 0
        and png.exists()
        and png.stat().st_size > 1500
        and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(
            f"render validation failed for {path.name}, page {page_number}: {process.stderr[-1500:]}"
        )
    png.unlink()


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def validate_pdf(target: dict[str, Any]) -> dict[str, Any]:
    path: Path = target["destination"]
    check = subprocess.run(
        ["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=240
    )
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {check.stderr[-2500:]}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < target["min_pages"]:
        raise RuntimeError(f"unexpectedly short report {path.name}: {pages} pages")
    if target.get("expected_pages") and pages != target["expected_pages"]:
        raise RuntimeError(
            f"page count mismatch for {path.name}: expected {target['expected_pages']}, got {pages}"
        )

    render_page(path, 1, "first")
    render_page(path, pages, "last")

    sample_indices = list(range(min(6, pages)))
    if pages > 6:
        sample_indices.append(pages - 1)
    sample_text = "\n".join((reader.pages[index].extract_text() or "") for index in sample_indices)
    normalized = normalize(sample_text)

    identity_ok = any(normalize(term) in normalized for term in target["identity_terms"])
    title_hits = [term for term in target["title_terms"] if normalize(term) in normalized]
    institution_ok = any(normalize(term) in normalized for term in target["institution_terms"])
    if sample_text.strip():
        if not identity_ok:
            raise RuntimeError(f"issuer identity not found in sampled text: {path.name}")
        if not title_hits:
            raise RuntimeError(f"title terms not found in sampled text: {path.name}")
        if not institution_ok:
            raise RuntimeError(f"institution not found in sampled text: {path.name}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "render_verified_first_and_last_page": True,
        "sample_text_extractable": bool(sample_text.strip()),
        "issuer_identity_verified_when_text_extractable": identity_ok,
        "title_terms_found": title_hits,
        "institution_verified_when_text_extractable": institution_ok,
    }


records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()
for target in TARGETS:
    final_url = download_pdf(target)
    metadata = validate_pdf(target)
    if metadata["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate file detected: {target['destination'].name}")
    seen_hashes.add(metadata["sha256"])
    record = {
        "date": target["date"],
        "institution": target["institution"],
        "authors": target["authors"],
        "report_type": target["type"],
        "title": target["title"],
        "stock": target["stock"],
        "relative_path": str(target["destination"].relative_to(ROOT)),
        "source": target["source_page"],
        "source_record_id": target["source_record_id"],
        "source_url": final_url,
        **metadata,
    }
    records.append(record)
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

manifest = {
    "package_name": PACKAGE,
    "issuer": "上海徐家汇商城股份有限公司",
    "stock_code": "002561",
    "checked_as_of": "2026-09-27",
    "report_count": len(records),
    "selection_note": "收录1份公司深度研究、1份调研简报和1份年度报告点评；均为完整PDF而非网页摘要。",
    "records": records,
}
(ROOT / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as fh:
    writer = csv.writer(fh)
    writer.writerow([
        "日期", "机构", "类型", "标题", "作者", "文件", "页数", "字节数", "SHA-256", "来源网址"
    ])
    for record in records:
        writer.writerow([
            record["date"], record["institution"], record["report_type"], record["title"],
            "、".join(record["authors"]), record["relative_path"], record["pages"],
            record["bytes"], record["sha256"], record["source_url"],
        ])

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as fh:
    for record in records:
        fh.write(f"{record['sha256']}  {record['relative_path']}\n")

readme = """徐家汇（002561）券商研究报告精选

核对日期：2026年9月27日

收录报告：
1. 2015-08-20，中泰证券，公司深度研究，《优质商圈+高盈利能力+高分红》，15页；
2. 2016-12-19，民生证券，调研简报，《主业经营稳健，持续深化全渠道布局》，4页；
3. 2017-03-31，民生证券，年度报告点评，《经营稳健，加速推进全渠道融合》，5页。

口径说明：
- 第1份为正式公司深度研究；
- 第2份为调研简报；
- 第3份为年度报告点评；
- 三份均为券商出具的完整公司研究PDF，不包含仅有摘要的网页页面。

校验说明：
- 每份PDF均通过文件头、文件大小、qpdf结构检查；
- 使用PDF解析器核对页数，并在文本可提取时核对公司、标题关键词及券商名称；
- 每份PDF的第一页和最后一页均已实际渲染为PNG，确认文件可正常打开与显示；
- 已进行SHA-256去重和ZIP完整性检查。
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
    "FINAL_ZIP", zip_path, "bytes", zip_path.stat().st_size,
    "sha256", sha256(zip_path), flush=True,
)
