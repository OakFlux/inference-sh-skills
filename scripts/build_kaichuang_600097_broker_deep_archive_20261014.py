from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

COMPANY = "开创国际"
FULL_COMPANY = "上海开创国际海洋资源股份有限公司"
CODE = "600097"
AS_OF_DATE = "2026-10-14"
BJ = timezone(timedelta(hours=8))

WORK_ROOT = Path("_build_kaichuang_600097_broker")
PACKAGE_NAME = f"{COMPANY}_{CODE}_券商深度报告_3份"
PACKAGE_ROOT = WORK_ROOT / PACKAGE_NAME
PDF_DIR = PACKAGE_ROOT / "01_券商原始PDF"
VERIFY_DIR = WORK_ROOT / "_verify"
ZIP_PATH = Path(PACKAGE_NAME + ".zip")

REPORTS: list[dict[str, Any]] = [
    {
        "report_date": "2009-07-17",
        "source_publish_date": "2009-07-20",
        "broker": "招商证券",
        "broker_full": "招商证券股份有限公司",
        "analysts": "朱卫华",
        "title": "竹荚鱼保底，金枪鱼增色",
        "classification": "公司研究",
        "rating": "强烈推荐-A",
        "source_page": "https://www.p5w.net/stock/lzft/gsyj/200907/t2461725.htm",
        "pdf_url": "https://www.p5w.net/stock/lzft/gsyj/200907/P020090720552442284062.pdf",
    },
    {
        "report_date": "2009-08-13",
        "source_publish_date": "2009-08-13",
        "broker": "招商证券",
        "broker_full": "招商证券股份有限公司",
        "analysts": "朱卫华、黄珺、董广",
        "title": "中报业绩符合预期",
        "classification": "公司研究",
        "rating": "强烈推荐-A",
        "source_page": "https://www.p5w.net/stock/lzft/gsyj/200908/t2507867.htm",
        "pdf_url": "https://www.p5w.net/stock/lzft/gsyj/200908/P020090813524011724460.pdf",
    },
    {
        "report_date": "2009-07-08",
        "source_publish_date": "2009-07-08",
        "broker": "国联证券",
        "broker_full": "国联证券股份有限公司",
        "analysts": "谢刚",
        "title": "具备估值吸引力的远洋捕捞旗舰",
        "classification": "公司研究",
        "rating": "买入",
        "source_page": "https://www.p5w.net/stock/lzft/gsyj/200907/t2440284.htm",
        "pdf_url": "https://www.p5w.net/stock/lzft/gsyj/200907/P020090708511549482748.pdf",
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def log(*args: Any) -> None:
    print(*args, flush=True)


def safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", "", value)
    return value[:160]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_with_retry(
    session: requests.Session,
    url: str,
    *,
    referer: str | None = None,
    require_pdf: bool = False,
    timeout: int = 150,
) -> requests.Response:
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    if require_pdf:
        headers["Accept"] = "application/pdf,*/*;q=0.8"
    else:
        headers["Accept"] = "text/html,application/xhtml+xml,*/*;q=0.8"

    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            log("HTTP", attempt, response.status_code, response.headers.get("content-type"), len(response.content), response.url)
            response.raise_for_status()
            if require_pdf:
                if not response.content.startswith(b"%PDF-") or len(response.content) < 50_000:
                    raise RuntimeError(
                        f"Invalid PDF response: bytes={len(response.content)}, type={response.headers.get('content-type')}"
                    )
            return response
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(min(2**attempt, 12))
    raise RuntimeError(f"Failed to fetch {url}: {last_error!r}")


def verify_source_page(session: requests.Session, report: dict[str, Any]) -> dict[str, Any]:
    response = get_with_retry(session, report["source_page"])
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    page_text = re.sub(r"\s+", "", soup.get_text(" ", strip=True))

    attachment_urls: list[str] = []
    attachment_labels: list[str] = []
    for anchor in soup.find_all("a", href=True):
        full_url = urljoin(response.url, anchor["href"])
        if full_url.lower().split("?", 1)[0].endswith(".pdf"):
            attachment_urls.append(full_url)
            attachment_labels.append(" ".join(anchor.get_text(" ", strip=True).split()))

    exact_attachment_found = report["pdf_url"] in attachment_urls
    company_found = COMPANY in page_title or COMPANY in page_text or CODE in page_text
    broker_found = report["broker"] in page_text
    title_tokens = [token for token in re.split(r"[，：,:+（）()\s]+", report["title"]) if len(token) >= 4]
    title_found = any(token in page_title or token in page_text for token in title_tokens)

    if not exact_attachment_found:
        raise RuntimeError(
            f"Expected PDF attachment not found on source page {report['source_page']}; found={attachment_urls}"
        )
    if not company_found:
        raise RuntimeError(f"Company identity not found on source page {report['source_page']}")
    if not broker_found:
        raise RuntimeError(f"Broker identity not found on source page {report['source_page']}")
    if not title_found:
        raise RuntimeError(f"Report title not found on source page {report['source_page']}")

    return {
        "source_page_final_url": response.url,
        "source_page_title": page_title,
        "source_attachment_label": attachment_labels[attachment_urls.index(report["pdf_url"])],
        "source_attachment_verified": True,
        "source_company_verified": True,
        "source_broker_verified": True,
        "source_title_verified": True,
    }


def extract_text(path: Path, pages: int) -> str:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        return ""
    result = subprocess.run(
        [pdftotext, "-f", "1", "-l", str(min(12, pages)), "-layout", "-enc", "UTF-8", str(path), "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def render_selected_pages(path: Path, page_count: int) -> tuple[list[int], list[str]]:
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise RuntimeError("pdftoppm is unavailable")
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    selected = sorted(set([1, (page_count + 1) // 2, page_count]))
    rendered: list[str] = []
    for page_no in selected:
        prefix = VERIFY_DIR / f"{path.stem}_p{page_no}"
        process = subprocess.run(
            [
                pdftoppm,
                "-f", str(page_no),
                "-l", str(page_no),
                "-singlefile",
                "-png",
                "-r", "130",
                str(path),
                str(prefix),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            raise RuntimeError(f"PDF render failed for {path}, page {page_no}: {process.stderr[-1000:]}")
        image_path = prefix.with_suffix(".png")
        data = image_path.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 10_000:
            raise RuntimeError(f"Invalid rendered image: {image_path}")
        rendered.append(str(image_path))
    return selected, rendered


def validate_pdf(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    data = path.read_bytes()
    if not data.startswith(b"%PDF-"):
        raise RuntimeError(f"Not a PDF: {path}")

    reader = PdfReader(str(path), strict=False)
    page_count = len(reader.pages)
    if page_count < 3:
        raise RuntimeError(f"Unexpectedly short report: {path}, pages={page_count}")

    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, check=False)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path}: {(qpdf.stdout + qpdf.stderr)[-2000:]}")

    text = extract_text(path, page_count)
    compact = re.sub(r"\s+", "", text)
    identity_text_verified = any(token in compact for token in (COMPANY, FULL_COMPANY, CODE))
    broker_text_verified = report["broker"] in compact or report["broker_full"] in compact
    title_tokens = [token for token in re.split(r"[，：,:+（）()\s]+", report["title"]) if len(token) >= 4]
    title_text_verified = any(token in compact for token in title_tokens)

    rendered_pages, render_files = render_selected_pages(path, page_count)
    return {
        "pages": page_count,
        "bytes": len(data),
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "identity_text_verified": identity_text_verified,
        "broker_text_verified": broker_text_verified,
        "title_text_verified": title_text_verified,
        "text_characters_extracted": len(text),
        "rendered_pages": rendered_pages,
        "render_files": render_files,
    }


def write_metadata(records: list[dict[str, Any]]) -> None:
    lines = [
        f"{COMPANY}（{CODE}）券商深度研究资料包",
        "",
        f"检索与核验截止日期：{AS_OF_DATE}",
        "",
        "收录原则：",
        "1. 收录可公开直接取得的券商原始排版PDF，不使用网页摘要或人工重排文件替代原件。",
        "2. 优先选择覆盖公司业务、行业、盈利预测及估值的系统性公司研究。",
        "3. 三份报告均为2009年历史研究，仅用于理解公司上市初期的远洋捕捞业务与估值逻辑，不代表当前投资观点。",
        "4. 每份PDF均检查文件头、qpdf结构、实际页数，并渲染首页、中间页和末页。",
        "5. PDF与其公开来源页面的公司、券商、标题及附件链接均已交叉核验。",
        "6. 研报版权归原券商及相关权利人所有，仅供研究学习。",
        "",
        "文件清单：",
    ]
    for index, record in enumerate(records, 1):
        lines.extend(
            [
                f"{index}. {record['broker']}，{record['report_date']}",
                f"   标题：{record['title']}",
                f"   类型：{record['classification']}；评级：{record['rating']}",
                f"   分析师：{record['analysts']}",
                f"   页数：{record['pages']}；大小：{record['bytes']}字节",
                f"   文件：{record['relative_path']}",
                f"   来源页面：{record['source_page']}",
                f"   PDF来源：{record['pdf_url']}",
                f"   SHA-256：{record['sha256']}",
                "",
            ]
        )
    (PACKAGE_ROOT / "README.txt").write_text("\n".join(lines), encoding="utf-8")

    fields = [
        "report_date", "source_publish_date", "broker", "broker_full", "analysts",
        "title", "classification", "rating", "pages", "bytes", "sha256",
        "relative_path", "source_page", "pdf_url", "source_page_title",
        "source_attachment_label", "source_attachment_verified", "source_company_verified",
        "source_broker_verified", "source_title_verified", "identity_text_verified",
        "broker_text_verified", "title_text_verified", "text_characters_extracted",
        "qpdf_return_code"
    ]
    with (PACKAGE_ROOT / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "company": COMPANY,
        "full_company_name": FULL_COMPANY,
        "stock_code": CODE,
        "as_of_date": AS_OF_DATE,
        "generated_at": datetime.now(tz=BJ).isoformat(),
        "document_count": len(records),
        "records": records,
    }
    (PACKAGE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (PACKAGE_ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{record['sha256']}  {record['relative_path']}" for record in records) + "\n",
        encoding="utf-8",
    )


def build_zip() -> None:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(PACKAGE_ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(Path(PACKAGE_ROOT.name) / path.relative_to(PACKAGE_ROOT)))
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC validation failed at {bad}")
    log("FINAL_ZIP", ZIP_PATH.name, "bytes", ZIP_PATH.stat().st_size, "sha256", sha256_file(ZIP_PATH))


def main() -> None:
    if WORK_ROOT.exists():
        shutil.rmtree(WORK_ROOT)
    PACKAGE_ROOT.mkdir(parents=True)
    PDF_DIR.mkdir(parents=True)

    session = requests.Session()
    session.trust_env = False
    records: list[dict[str, Any]] = []

    for report in REPORTS:
        source_checks = verify_source_page(session, report)
        filename = f"{report['report_date'].replace('-', '')}_{report['broker']}_{safe_name(report['title'])}.pdf"
        path = PDF_DIR / filename
        response = get_with_retry(
            session,
            report["pdf_url"],
            referer=report["source_page"],
            require_pdf=True,
        )
        path.write_bytes(response.content)
        validation = validate_pdf(path, report)
        record = {
            **report,
            **source_checks,
            **validation,
            "download_final_url": response.url,
            "relative_path": str(path.relative_to(PACKAGE_ROOT)),
        }
        log("VALIDATED", json.dumps(record, ensure_ascii=False))
        records.append(record)
        time.sleep(0.5)

    if len(records) != 3:
        raise RuntimeError(f"Expected 3 reports, got {len(records)}")
    if len({record['sha256'] for record in records}) != 3:
        raise RuntimeError("Duplicate PDF detected")

    write_metadata(records)
    build_zip()


if __name__ == "__main__":
    main()
