from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-10-04"
COMPANY = "天普股份"
FULL_COMPANY = "宁波市天普橡胶科技股份有限公司"
STOCK_CODE = "605255"
PACKAGE = "天普股份_605255_券商研究报告_3份"
ROOT = Path(PACKAGE)
REPORT_DIR = ROOT / "01_新股询价研究报告"
VERIFY_DIR = ROOT / "02_说明与校验"
WORK_DIR = Path("_tianpu_605255_broker_reports_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (REPORT_DIR, VERIFY_DIR, RENDER_DIR):
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
        "rptid": "650127406222",
        "filename": "20200807_国元证券_派克新材与天普股份新股网下询价策略.pdf",
        "candidates": [],
    },
    {
        "date": "2020-08-05",
        "broker": "华鑫证券",
        "broker_aliases": ["华鑫证券", "华鑫证券有限责任公司"],
        "authors": "严凯文",
        "title": "新股询价报告：天普股份",
        "report_type": "新股询价报告",
        "rptid": "649960495322",
        "filename": "20200805_华鑫证券_天普股份新股询价报告.pdf",
        "candidates": [
            "https://pdf.dfcfw.com/pdf/H3_AP202008051396530277_1.pdf",
        ],
    },
    {
        "date": "2020-08-05",
        "broker": "东莞证券",
        "broker_aliases": ["东莞证券", "东莞证券股份有限公司"],
        "authors": "魏红梅、雷国轩",
        "title": "新股网下申购询价建议报告：派克新材（605123）、天普股份（605255）",
        "report_type": "新股网下申购询价建议报告",
        "rptid": "649940413902",
        "filename": "20200805_东莞证券_派克新材与天普股份新股网下申购询价建议报告.pdf",
        "candidates": [],
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_response(url: str, referer: str | None = None, timeout: tuple[int, int] = (20, 300)) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        headers = dict(HEADERS)
        if referer:
            headers["Referer"] = referer
        try:
            response = SESSION.get(url, headers=headers, timeout=timeout, allow_redirects=True, stream=False)
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


def parse_redirect_candidates(base_url: str, text: str) -> list[str]:
    candidates: list[str] = []
    patterns = [
        r"(?:window\.)?location(?:\.href)?\s*=\s*['\"]([^'\"]+)['\"]",
        r"URL\s*=\s*([^'\"<>\s]+)",
        r"content\s*=\s*['\"][^'\"]*url=([^'\"]+)['\"]",
        r"href\s*=\s*['\"]([^'\"]+\.pdf(?:\?[^'\"]*)?)['\"]",
        r"https?://[^'\"<>\s]+\.pdf(?:\?[^'\"<>\s]*)?",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            value = match.group(1) if match.lastindex else match.group(0)
            value = html.unescape(value).strip()
            candidates.append(urljoin(base_url, value))
    return list(dict.fromkeys(candidates))


def save_pdf_from_url(url: str, destination: Path, referer: str) -> tuple[str, list[str]]:
    attempted: list[str] = []
    queue = [url]
    seen: set[str] = set()
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        attempted.append(current)
        try:
            response = get_response(current, referer=referer)
        except Exception as exc:  # noqa: BLE001
            print("CANDIDATE_FAILED", current, repr(exc), flush=True)
            continue
        content = response.content
        final_url = str(response.url)
        content_type = (response.headers.get("content-type") or "").lower()
        if content.startswith(b"%PDF-") and len(content) > 20_000:
            destination.write_bytes(content)
            return final_url, attempted
        if "html" in content_type or content[:100].lstrip().startswith((b"<", b"{")):
            try:
                text = response.text
            except Exception:
                text = content.decode("utf-8", errors="ignore")
            new_candidates = parse_redirect_candidates(final_url, text)
            print("PARSED_REDIRECTS", current, json.dumps(new_candidates, ensure_ascii=False), flush=True)
            queue.extend(new_candidates)
    raise RuntimeError(f"no PDF resolved; attempted={attempted}")


def download_report(report: dict[str, Any], destination: Path) -> tuple[str, list[str]]:
    rptid = report["rptid"]
    detail_url = f"https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/{rptid}/index.phtml"
    candidates = [
        f"https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/{rptid}/url",
        f"http://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/{rptid}/url",
        *report.get("candidates", []),
    ]
    errors: list[str] = []
    attempted_all: list[str] = []
    for candidate in candidates:
        try:
            final_url, attempted = save_pdf_from_url(candidate, destination, detail_url)
            attempted_all.extend(attempted)
            print("DOWNLOADED", report["broker"], destination, destination.stat().st_size, final_url, flush=True)
            return final_url, attempted_all
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{candidate}: {exc!r}")
            attempted_all.append(candidate)
            destination.unlink(missing_ok=True)
            print("DOWNLOAD_SOURCE_FAILED", report["broker"], candidate, repr(exc), flush=True)
    raise RuntimeError(f"all sources failed for {report['broker']}: {errors}")


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
        process.returncode == 0 and png.exists() and png.stat().st_size > 1000
        and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(
            f"render failed for {path.name} page {page_number}: "
            f"return={process.returncode}, stderr={process.stderr[-1200:]}"
        )
    png.unlink()


def validate_report(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=240)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-2000:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 2 or pages > 30:
        raise RuntimeError(f"unexpected page count for {path.name}: {pages}")
    render_page(path, 1, "first")
    if pages > 1:
        render_page(path, pages, "last")
    text_parts: list[str] = []
    for index in range(min(pages, 6)):
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_WARNING", path.name, index + 1, repr(exc), flush=True)
    text = "\n".join(text_parts)
    normalized = re.sub(r"\s+", "", text)
    company_ok = COMPANY in normalized or STOCK_CODE in normalized or FULL_COMPANY in normalized
    broker_ok = any(alias in normalized for alias in report["broker_aliases"])
    if text.strip() and not company_ok:
        raise RuntimeError(f"company identity not found in {path.name}")
    if text.strip() and not broker_ok:
        raise RuntimeError(f"broker identity not found in {path.name}")
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "company_verified_when_text_extractable": company_ok,
        "broker_verified_when_text_extractable": broker_ok,
        "sample_text_extractable": bool(text.strip()),
        "first_and_last_pages_rendered": True,
    }


records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()
for report in REPORTS:
    destination = REPORT_DIR / report["filename"]
    final_url, attempted = download_report(report, destination)
    validation = validate_report(destination, report)
    if validation["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate file detected: {destination.name}")
    seen_hashes.add(validation["sha256"])
    record = {
        "date": report["date"],
        "broker": report["broker"],
        "authors": report["authors"],
        "title": report["title"],
        "report_type": report["report_type"],
        "relative_path": str(destination.relative_to(ROOT)),
        "sina_detail_url": f"https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/{report['rptid']}/index.phtml",
        "download_url": final_url,
        "attempted_sources": attempted,
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
        "公开券商数据库仅检索到3份2020年上市前的新股询价/网下申购策略报告。"
        "未检索到20页以上的独立公司深度或首次覆盖报告，因此未将这些文件误标为长篇深度报告。"
    ),
    "records": records,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as handle:
    writer = csv.writer(handle)
    writer.writerow(["文件", "日期", "券商", "作者", "标题", "报告类型", "页数", "字节数", "SHA-256", "来源页面", "下载地址"])
    for record in records:
        writer.writerow([
            record["relative_path"], record["date"], record["broker"], record["authors"],
            record["title"], record["report_type"], record["pages"], record["bytes"],
            record["sha256"], record["sina_detail_url"], record["download_url"],
        ])

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as handle:
    for record in records:
        handle.write(f"{record['sha256']}  {record['relative_path']}\n")

readme_lines = [
    f"{COMPANY}（{STOCK_CODE}）券商研究报告资料包",
    "",
    f"核对日期：{CHECKED_AS_OF}",
    "收录数量：3份完整PDF",
    "",
    "重要说明：",
    "公开券商数据库仅检索到3份2020年上市前的新股询价或网下申购策略报告。",
    "这些报告属于券商公司研究，但篇幅较短，不是通常意义上20页以上的公司深度或首次覆盖报告。",
    "本资料包未使用公告、AI研报、网页行情分析或交易提示凑数。",
    "",
    "收录文件：",
]
for index, record in enumerate(records, start=1):
    readme_lines.append(
        f"{index}. {record['date']} | {record['broker']} | {record['title']} | {record['pages']}页"
    )
readme_lines.extend([
    "",
    "校验说明：",
    "- 每份PDF均通过文件头、qpdf结构和页数检查；",
    "- 核对天普股份/605255及券商署名；",
    "- 每份PDF首页和末页均已实际渲染验证；",
    "- 文件之间已进行SHA-256去重；",
    "- 详细来源、文件大小和校验值见文件清单.csv、SHA256SUMS.txt及manifest.json。",
])
(VERIFY_DIR / "README.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

zip_path = Path(PACKAGE + ".zip")
zip_path.unlink(missing_ok=True)
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, path.as_posix())

with zipfile.ZipFile(zip_path, "r") as archive:
    bad = archive.testzip()
    if bad:
        raise RuntimeError(f"ZIP integrity failure: {bad}")
    pdf_count = sum(1 for name in archive.namelist() if name.lower().endswith(".pdf"))
    if pdf_count != 3:
        raise RuntimeError(f"expected 3 PDFs, found {pdf_count}")

print(
    "FINAL_ZIP", zip_path, "bytes", zip_path.stat().st_size,
    "sha256", sha256(zip_path), flush=True,
)
print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
