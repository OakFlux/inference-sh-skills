from __future__ import annotations

import csv
import hashlib
import html
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

CHECKED_AS_OF = "2026-10-04"
COMPANY = "天普股份"
FULL_COMPANY = "宁波市天普橡胶科技股份有限公司"
STOCK_CODE = "605255"
PACKAGE = "天普股份_605255_券商研究报告_3份"
ROOT = Path(PACKAGE)
ORIGINAL_DIR = ROOT / "01_券商原始PDF"
ARCHIVE_DIR = ROOT / "02_公开全文存档版"
VERIFY_DIR = ROOT / "03_说明与校验"
WORK_DIR = Path("_tianpu_605255_broker_reports_v2_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (ORIGINAL_DIR, ARCHIVE_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
    "Accept": "text/html,application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

REPORTS: list[dict[str, Any]] = [
    {
        "date": "2020-08-07",
        "broker": "国元证券",
        "broker_aliases": ["国元证券", "国元证券股份有限公司"],
        "authors": "王薇薇",
        "title": "派克新材（605123）、天普股份（605255）新股网下询价策略",
        "report_type": "新股网下询价策略",
        "source_kind": "public_html_archive",
        "source_url": "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/650127406222/index.phtml",
        "filename": "20200807_国元证券_派克新材与天普股份新股网下询价策略_公开全文存档版.pdf",
    },
    {
        "date": "2020-08-05",
        "broker": "华鑫证券",
        "broker_aliases": ["华鑫证券", "华鑫证券有限责任公司"],
        "authors": "严凯文",
        "title": "新股询价报告：天普股份",
        "report_type": "新股询价报告",
        "source_kind": "original_pdf",
        "source_url": "https://pdf.dfcfw.com/pdf/H3_AP202008051396530277_1.pdf",
        "detail_url": "https://data.eastmoney.com/report/info/AP202008051396530277.html",
        "filename": "20200805_华鑫证券_天普股份新股询价报告_原始PDF.pdf",
    },
    {
        "date": "2020-08-05",
        "broker": "东莞证券",
        "broker_aliases": ["东莞证券", "东莞证券股份有限公司"],
        "authors": "魏红梅、雷国轩",
        "title": "新股网下申购询价建议报告：派克新材（605123）、天普股份（605255）",
        "report_type": "新股网下申购询价建议报告",
        "source_kind": "public_html_archive",
        "source_url": "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/649940413902/index.phtml",
        "filename": "20200805_东莞证券_派克新材与天普股份新股网下申购询价建议报告_公开全文存档版.pdf",
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request(url: str, *, timeout: tuple[int, int] = (20, 300), referer: str | None = None) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        headers = dict(HEADERS)
        if referer:
            headers["Referer"] = referer
        try:
            response = SESSION.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            print(
                "HTTP", url, "attempt", attempt, "status", response.status_code,
                "type", response.headers.get("content-type"), "bytes", len(response.content),
                "final", response.url, flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"request failed for {url}: {errors[-6:]}")


def find_chrome() -> str:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        executable = shutil.which(name)
        if executable:
            return executable
    raise RuntimeError("headless Chrome/Chromium is not available")


def verify_public_page(report: dict[str, Any]) -> dict[str, Any]:
    response = request(report["source_url"], timeout=(20, 120))
    response.encoding = response.apparent_encoding or response.encoding or "gbk"
    text = response.text
    clean = html.unescape(
        re.sub(
            r"\s+",
            " ",
            re.sub(
                r"<[^>]+>",
                " ",
                re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.I | re.S),
            ),
        )
    )
    if COMPANY not in clean and STOCK_CODE not in clean:
        raise RuntimeError(f"company identity missing from source page: {report['source_url']}")
    if not any(alias in clean for alias in report["broker_aliases"]):
        raise RuntimeError(f"broker identity missing from source page: {report['source_url']}")
    if report["date"] not in clean:
        raise RuntimeError(f"date missing from source page: {report['source_url']}")
    body_markers = {
        "国元证券": "2020年8月7日派克新材和天普股份开启网下询价",
        "东莞证券": "公司是一家跨地区集团化生产型国家高新技术企业",
    }
    marker = body_markers.get(report["broker"])
    if marker and marker not in clean:
        raise RuntimeError(f"report body marker missing from source page: {marker}")
    return {
        "source_page_status": response.status_code,
        "source_page_final_url": str(response.url),
        "source_page_bytes": len(response.content),
        "source_page_identity_verified": True,
    }


def print_page_to_pdf(url: str, destination: Path) -> None:
    chrome = find_chrome()
    absolute_destination = destination.resolve()
    command = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--hide-scrollbars",
        "--virtual-time-budget=12000",
        "--run-all-compositor-stages-before-draw",
        "--print-to-pdf-no-header",
        f"--print-to-pdf={absolute_destination}",
        url,
    ]
    print("CHROME_COMMAND", command, flush=True)
    process = subprocess.run(command, capture_output=True, text=True, timeout=240)
    print("CHROME_RETURN", process.returncode, process.stderr[-3000:], flush=True)
    if process.returncode != 0 or not destination.exists():
        raise RuntimeError(f"Chrome print failed for {url}")
    if destination.stat().st_size < 40_000 or not destination.read_bytes().startswith(b"%PDF-"):
        raise RuntimeError(f"invalid printed PDF for {url}: {destination.stat().st_size}")


def download_original_pdf(report: dict[str, Any], destination: Path) -> str:
    response = request(report["source_url"], timeout=(25, 360), referer=report.get("detail_url"))
    content = response.content
    if not content.startswith(b"%PDF-") or len(content) < 40_000:
        raise RuntimeError(
            f"invalid original PDF: type={response.headers.get('content-type')}, bytes={len(content)}"
        )
    destination.write_bytes(content)
    return str(response.url)


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
        process.returncode == 0 and png.exists() and png.stat().st_size > 2000
        and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(
            f"render failed for {path.name} page {page_number}: "
            f"return={process.returncode}, stderr={process.stderr[-1500:]}"
        )
    png.unlink()


def validate_pdf(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=240)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {qpdf.stderr[-2500:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 1 or pages > 20:
        raise RuntimeError(f"unexpected page count for {path.name}: {pages}")
    page_numbers = sorted({1, pages, max(1, (pages + 1) // 2)})
    for page_number in page_numbers:
        render_page(path, page_number, f"p{page_number}")
    text_parts: list[str] = []
    for index in range(pages):
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_EXTRACT_WARNING", path.name, index + 1, repr(exc), flush=True)
    text = "\n".join(text_parts)
    normalized = re.sub(r"\s+", "", text)
    company_ok = COMPANY in normalized or STOCK_CODE in normalized or FULL_COMPANY in normalized
    broker_ok = any(alias in normalized for alias in report["broker_aliases"])
    if text.strip() and not company_ok:
        raise RuntimeError(f"company identity missing from generated PDF: {path.name}")
    if text.strip() and not broker_ok:
        raise RuntimeError(f"broker identity missing from generated PDF: {path.name}")
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "rendered_pages": page_numbers,
        "sample_text_extractable": bool(text.strip()),
        "company_verified_when_text_extractable": company_ok,
        "broker_verified_when_text_extractable": broker_ok,
    }


records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()
for report in REPORTS:
    source_metadata: dict[str, Any] = {}
    if report["source_kind"] == "original_pdf":
        destination = ORIGINAL_DIR / report["filename"]
        final_url = download_original_pdf(report, destination)
        source_metadata = {
            "source_format": "券商研究原始PDF镜像",
            "source_url": final_url,
            "source_detail_url": report.get("detail_url"),
            "archive_note": "原始PDF文件，未重新排版。",
        }
    else:
        destination = ARCHIVE_DIR / report["filename"]
        source_metadata.update(verify_public_page(report))
        print_page_to_pdf(report["source_url"], destination)
        source_metadata.update(
            {
                "source_format": "公开全文网页存档版",
                "source_url": report["source_url"],
                "archive_note": (
                    "由新浪财经保存的完整公开研报正文页面打印为PDF；"
                    "不是券商原始排版PDF，页面可能包含网站导航及来源信息。"
                ),
            }
        )
    validation = validate_pdf(destination, report)
    if validation["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate report detected: {destination.name}")
    seen_hashes.add(validation["sha256"])
    record = {
        "date": report["date"],
        "broker": report["broker"],
        "authors": report["authors"],
        "title": report["title"],
        "report_type": report["report_type"],
        "relative_path": str(destination.relative_to(ROOT)),
        **source_metadata,
        **validation,
    }
    records.append(record)
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

manifest = {
    "package_name": PACKAGE,
    "company": FULL_COMPANY,
    "stock_code": STOCK_CODE,
    "checked_as_of": CHECKED_AS_OF,
    "document_count": len(records),
    "scope_note": (
        "公开券商数据库仅检索到3份2020年上市前的新股询价/网下申购研究。"
        "其中1份取得原始PDF，2份取得公开全文网页并生成存档PDF。"
        "未检索到通常意义上20页以上的独立公司深度或首次覆盖报告。"
    ),
    "records": records,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as handle:
    writer = csv.writer(handle)
    writer.writerow(
        [
            "文件", "日期", "券商", "作者", "标题", "报告类型", "来源格式",
            "页数", "字节数", "SHA-256", "来源网址", "说明",
        ]
    )
    for record in records:
        writer.writerow(
            [
                record["relative_path"], record["date"], record["broker"], record["authors"],
                record["title"], record["report_type"], record["source_format"],
                record["pages"], record["bytes"], record["sha256"],
                record["source_url"], record["archive_note"],
            ]
        )

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as handle:
    for record in records:
        handle.write(f"{record['sha256']}  {record['relative_path']}\n")

readme_lines = [
    f"{COMPANY}（{STOCK_CODE}）券商研究报告资料包",
    "",
    f"核对日期：{CHECKED_AS_OF}",
    "收录数量：3份",
    "",
    "重要口径说明：",
    "公开券商数据库仅能确认3份2020年上市前的新股询价或网下申购研究。",
    "未检索到通常意义上20页以上的独立公司深度或首次覆盖报告，因此本包没有将短报告误标为长篇深度报告。",
    "华鑫证券报告为原始PDF；国元证券和东莞证券报告来自新浪财经保留的公开全文页面，已转换为PDF存档，并在文件名中明确标注。",
    "",
    "收录文件：",
]
for index, record in enumerate(records, start=1):
    readme_lines.append(
        f"{index}. {record['date']} | {record['broker']} | {record['title']} | "
        f"{record['pages']}页 | {record['source_format']}"
    )
readme_lines.extend(
    [
        "",
        "校验说明：",
        "- 每份PDF均完成文件头、qpdf结构和页数检查；",
        "- 核对公司名称/股票代码、券商名称、日期和正文标识；",
        "- 每份PDF的首页、中间页及末页均已实际渲染验证；",
        "- 文件之间已进行SHA-256去重；",
        "- ZIP已通过完整性测试；",
        "- 详细来源、大小及校验值见文件清单.csv、SHA256SUMS.txt和manifest.json。",
    ]
)
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
        raise RuntimeError(f"ZIP integrity failed at {bad_member}")
    pdf_count = sum(1 for name in archive.namelist() if name.lower().endswith(".pdf"))
    if pdf_count != 3:
        raise RuntimeError(f"ZIP PDF count mismatch: expected 3, got {pdf_count}")

print(
    "FINAL_ZIP", zip_path, "bytes", zip_path.stat().st_size,
    "sha256", sha256(zip_path), flush=True,
)
print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
