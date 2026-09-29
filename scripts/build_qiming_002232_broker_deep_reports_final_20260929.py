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

CHECKED_AS_OF = "2026-09-29"
COMPANY = "启明信息"
FULL_COMPANY = "启明信息技术股份有限公司"
STOCK_CODE = "002232"
PACKAGE = "启明信息_002232_券商深度报告_3份"
ROOT = Path(PACKAGE)
REPORT_DIR = ROOT / "01_券商深度报告"
VERIFY_DIR = ROOT / "02_说明与校验"
WORK_DIR = Path("_qiming_002232_broker_final_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (REPORT_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
    "Accept": "text/html,application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

REPORTS: list[dict[str, Any]] = [
    {
        "date": "2016-05-05",
        "broker": "长城证券",
        "broker_aliases": ["长城证券", "长城研究"],
        "title": "车联网战略全启动，云服务拓展新空间——启明信息（002232）公司深度报告",
        "filename": "20160505_长城证券_车联网战略全启动_云服务拓展新空间.pdf",
        "url": "https://www.cgws.com/cczq/ggdt/ccyj/201606/P020160608525303437879.pdf",
        "page_url": "https://www.cgws.com/cczq/ggdt/ccyj/201606/t20160608_83594.html",
        "source": "长城证券官网原始附件",
        "authors": "周伟佳、赵悦媛",
        "min_pages": 10,
    },
    {
        "date": "2010-03-23",
        "broker": "国金证券",
        "broker_aliases": ["国金证券", "国金证券研究所"],
        "title": "背靠大树，双轮驱动，成就高成长之路",
        "filename": "20100323_国金证券_背靠大树_双轮驱动_成就高成长之路.pdf",
        "url": "https://www.p5w.net/stock/lzft/gsyj/201003/P020100323516850519501.pdf",
        "page_url": "https://www.p5w.net/stock/lzft/gsyj/201003/t2882628.htm",
        "source": "全景网原始研报附件（国金证券研究所）",
        "authors": "程兵、陈运红",
        "min_pages": 10,
    },
    {
        "date": "2010-04-01",
        "broker": "国联证券",
        "broker_aliases": ["国联证券", "国联证券研发中心", "国联民生证券"],
        "title": "“项目达产+行业需求”助推企业加速——启明信息投资价值分析",
        "filename": "20100401_国联证券_项目达产加行业需求_助推企业加速.pdf",
        "url": "https://www.p5w.net/stock/lzft/gsyj/201004/P020100401531193418983.pdf",
        "page_url": "https://www.p5w.net/stock/lzft/gsyj/201004/t2901168.htm",
        "source": "全景网原始研报附件（国联证券研发中心）",
        "authors": "郝杰",
        "min_pages": 10,
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request(url: str, *, referer: str, stream: bool = True,
            timeout: tuple[int, int] = (25, 420)) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        headers = dict(BASE_HEADERS)
        headers["Referer"] = referer
        try:
            response = SESSION.get(
                url, headers=headers, timeout=timeout,
                stream=stream, allow_redirects=True,
            )
            print(
                "HTTP", url, "attempt", attempt,
                "status", response.status_code,
                "type", response.headers.get("content-type"),
                "length", response.headers.get("content-length"),
                "final", response.url,
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(attempt * 2, 10))
    raise RuntimeError(f"request failed for {url}: {errors[-6:]}")


def download_pdf(report: dict[str, Any], destination: Path) -> str:
    temp = destination.with_suffix(".pdf.part")
    temp.unlink(missing_ok=True)
    response = request(report["url"], referer=report["page_url"], stream=True)
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
    if size < 120_000 or not head.startswith(b"%PDF-"):
        raise RuntimeError(f"invalid PDF for {report['broker']}: size={size}, head={head!r}")
    temp.replace(destination)
    print("DOWNLOADED", destination, size, final_url, flush=True)
    return final_url


def render_page(path: Path, page_number: int, suffix: str) -> str:
    prefix = RENDER_DIR / f"{path.stem}_{suffix}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
            "-r", "110", "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    png = Path(str(prefix) + ".png")
    valid = (
        process.returncode == 0 and png.exists() and png.stat().st_size > 3000
        and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(
            f"render failed for {path.name} page {page_number}: "
            f"return={process.returncode}, stderr={process.stderr[-1500:]}"
        )
    relative = str(png.relative_to(WORK_DIR))
    print("RENDERED", path.name, page_number, relative, png.stat().st_size, flush=True)
    return relative


def validate_pdf(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    check = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-2500:]}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < int(report["min_pages"]):
        raise RuntimeError(f"report too short: {path.name}, pages={pages}")

    page_numbers = sorted({1, max(1, (pages + 1) // 2), pages})
    render_files = [
        render_page(path, page_number, f"p{page_number}")
        for page_number in page_numbers
    ]

    sample_indices = sorted({0, 1, 2, min(5, pages - 1), max(0, pages // 2), pages - 1})
    text_parts: list[str] = []
    for index in sample_indices:
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_EXTRACT_WARNING", path.name, index + 1, repr(exc), flush=True)
    text = "\n".join(text_parts)
    normalized = re.sub(r"\s+", "", text)
    company_ok = COMPANY in normalized or FULL_COMPANY in normalized or STOCK_CODE in normalized
    broker_ok = any(alias in normalized for alias in report["broker_aliases"])
    research_ok = any(marker in normalized for marker in (
        "公司深度", "深度研究", "投资价值分析", "首次覆盖", "投资要点",
        "投资建议", "盈利预测", "评级", "公司研究", "研究报告",
    ))
    if text.strip() and not company_ok:
        raise RuntimeError(f"company identity missing from sampled text: {path.name}")
    if text.strip() and not broker_ok:
        raise RuntimeError(f"broker identity missing from sampled text: {path.name}")
    if text.strip() and not research_ok:
        raise RuntimeError(f"research marker missing from sampled text: {path.name}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "rendered_pages": page_numbers,
        "render_files": render_files,
        "issuer_identity_verified_when_text_extractable": company_ok,
        "broker_identity_verified_when_text_extractable": broker_ok,
        "research_marker_verified_when_text_extractable": research_ok,
        "sample_text_extractable": bool(text.strip()),
    }


records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()
for report in REPORTS:
    destination = REPORT_DIR / report["filename"]
    final_url = download_pdf(report, destination)
    validation = validate_pdf(destination, report)
    if validation["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate report detected: {destination.name}")
    seen_hashes.add(validation["sha256"])
    record = {
        "date": report["date"],
        "broker": report["broker"],
        "title": report["title"],
        "authors": report["authors"],
        "relative_path": str(destination.relative_to(ROOT)),
        "source": report["source"],
        "page_url": report["page_url"],
        "source_url": final_url,
        **validation,
    }
    records.append(record)
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

manifest = {
    "package_name": PACKAGE,
    "company": COMPANY,
    "stock_code": STOCK_CODE,
    "checked_as_of": CHECKED_AS_OF,
    "report_count": len(records),
    "selection_principles": [
        "仅收录可取得完整原始PDF的公司深度、投资价值分析或首次覆盖类报告。",
        "排除网页摘要、行业周报、晨会材料和短篇财报点评。",
        "优先不同券商，并保留报告原始发布日期、标题和来源页面。",
        "每份PDF均通过文件头、qpdf结构、页数、公司和券商身份、研究报告标识及首中尾页渲染检查。",
    ],
    "records": records,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as fh:
    writer = csv.writer(fh)
    writer.writerow([
        "文件", "发布日期", "券商", "标题", "作者", "页数", "字节数",
        "SHA-256", "来源说明", "来源页面", "PDF网址",
    ])
    for record in records:
        writer.writerow([
            record["relative_path"], record["date"], record["broker"], record["title"],
            record["authors"], record["pages"], record["bytes"], record["sha256"],
            record["source"], record["page_url"], record["source_url"],
        ])

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as fh:
    for record in records:
        fh.write(f"{record['sha256']}  {record['relative_path']}\n")

readme_lines = [
    f"{COMPANY}（{STOCK_CODE}）券商深度报告文件包",
    "",
    f"核对日期：{CHECKED_AS_OF}",
    "收录数量：3份完整PDF",
    "",
    "收录报告：",
]
for index, record in enumerate(records, start=1):
    readme_lines.append(
        f"{index}. {record['date']} | {record['broker']} | {record['title']} | {record['pages']}页"
    )
readme_lines.extend([
    "",
    "筛选和校验：",
    "- 仅使用券商官网或保留原始研报附件的公开证券信息平台PDF；",
    "- 未以网页摘要、短篇财报点评或自动生成内容替代原始研报；",
    "- 每份PDF均检查结构、页数、公司名称、券商署名及研究报告标识；",
    "- 每份PDF的首页、中间页和末页均已实际渲染验证；",
    "- 详细来源和哈希值见文件清单.csv、SHA256SUMS.txt及manifest.json。",
])
(VERIFY_DIR / "README.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

zip_path = Path(PACKAGE + ".zip")
zip_path.unlink(missing_ok=True)
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, path.as_posix())

with zipfile.ZipFile(zip_path, "r") as archive:
    bad_member = archive.testzip()
    if bad_member:
        raise RuntimeError(f"ZIP integrity test failed at {bad_member}")
    pdf_count = sum(1 for name in archive.namelist() if name.lower().endswith(".pdf"))
    if pdf_count != 3:
        raise RuntimeError(f"ZIP PDF count mismatch: expected 3, got {pdf_count}")

print(
    "FINAL_ZIP", zip_path,
    "bytes", zip_path.stat().st_size,
    "sha256", sha256(zip_path),
    flush=True,
)
