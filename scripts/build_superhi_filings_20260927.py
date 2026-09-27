from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

PACKAGE = "特海国际_09658_HDL_2022-2025全部年报_上市及招股文件_2026最新定期报告"
root = Path(PACKAGE)
annual_dir = root / "01_年度报告"
offering_dir = root / "02_上市及招股文件"
latest_dir = root / "03_最新定期报告"
notes_dir = root / "04_说明与校验"
render_dir = Path("_superhi_v3_renders")
for directory in (annual_dir, offering_dir, latest_dir, notes_dir, render_dir):
    directory.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.trust_env = False
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
    }
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_response(
    url: str,
    *,
    referer: str | None = None,
    stream: bool = False,
    timeout: tuple[int, int] = (12, 120),
) -> requests.Response:
    headers = {"Referer": referer} if referer else {}
    errors: list[str] = []
    variants = [url]
    if "www1.hkexnews.hk" in url:
        variants.append(url.replace("www1.hkexnews.hk", "www.hkexnews.hk"))
    for variant in dict.fromkeys(variants):
        for attempt in range(1, 4):
            try:
                response = session.get(
                    variant,
                    headers=headers,
                    timeout=timeout,
                    allow_redirects=True,
                    stream=stream,
                )
                print(
                    "GET",
                    attempt,
                    response.status_code,
                    response.headers.get("content-type"),
                    response.headers.get("content-length"),
                    response.url,
                    flush=True,
                )
                response.raise_for_status()
                return response
            except Exception as exc:
                errors.append(repr(exc))
                time.sleep(attempt)
    raise RuntimeError(f"GET failed for {url}: {errors[-6:]}")


def download_pdf(
    url: str,
    destination: Path,
    *,
    referer: str | None = None,
    min_bytes: int = 30_000,
) -> str:
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    response = get_response(
        url,
        referer=referer,
        stream=True,
        timeout=(15, 300),
    )
    try:
        with temporary.open("wb") as file:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    file.write(chunk)
        final_url = str(response.url)
    finally:
        response.close()
    header = temporary.read_bytes()[:8]
    if temporary.stat().st_size < min_bytes or not header.startswith(b"%PDF-"):
        raise RuntimeError(
            f"Invalid PDF download {destination.name}: "
            f"size={temporary.stat().st_size}, header={header!r}, url={final_url}"
        )
    temporary.replace(destination)
    return final_url


def hkex_links(start_date: str, end_date: str) -> list[dict]:
    search_url = (
        "https://www1.hkexnews.hk/search/titlesearch.xhtml"
        f"?category=0&lang=EN&market=SEHK&stockId=1000179492"
        f"&from={start_date}&to={end_date}"
    )
    response = get_response(
        search_url,
        referer="https://www1.hkexnews.hk/",
        timeout=(10, 60),
    )
    try:
        content = response.content
        final_url = str(response.url)
    finally:
        response.close()
    soup = BeautifulSoup(content, "html.parser")
    links: list[dict] = []
    for anchor in soup.find_all("a", href=True):
        text = " ".join(anchor.get_text(" ", strip=True).split())
        href = urljoin(final_url, anchor["href"])
        if "listconews" in href and (
            ".pdf" in href.lower() or ".htm" in href.lower()
        ):
            links.append({"text": text, "href": href, "page": final_url})
    print("HKEX_ROWS", start_date, end_date, len(links), flush=True)
    for row in links:
        print("HKEX_LINK", json.dumps(row, ensure_ascii=False), flush=True)
    return links


def choose_hkex_link(
    links: list[dict],
    required_terms: tuple[str, ...],
    excluded_terms: tuple[str, ...] = (),
) -> dict:
    matches: list[dict] = []
    for row in links:
        text = row["text"].lower()
        if all(term.lower() in text for term in required_terms) and not any(
            term.lower() in text for term in excluded_terms
        ):
            matches.append(row)
    matches.sort(
        key=lambda row: (row["href"].lower().endswith(".pdf"), len(row["text"])),
        reverse=True,
    )
    if not matches:
        raise RuntimeError(
            f"No HKEX match for required={required_terms}, excluded={excluded_terms}"
        )
    return matches[0]


def pdf_link_from_ir_filing(filing_url: str) -> tuple[str, str]:
    response = get_response(filing_url, timeout=(10, 60))
    try:
        content = response.content
        final_url = str(response.url)
    finally:
        response.close()
    soup = BeautifulSoup(content, "html.parser")
    candidates: list[tuple[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        text = " ".join(anchor.get_text(" ", strip=True).split())
        href = urljoin(final_url, anchor["href"])
        if "pdf" in text.lower() or href.lower().endswith(".pdf"):
            candidates.append((text, href))
    for text, href in candidates:
        if "download pdf" in text.lower() or re.search(
            r"\d{10}-\d{2}-\d{6}\.pdf$", href, re.I
        ):
            print("IR_PDF", text, href, flush=True)
            return href, final_url
    if candidates:
        print("IR_PDF_FALLBACK", candidates[0], flush=True)
        return candidates[0][1], final_url
    raise RuntimeError(f"No PDF link found on {filing_url}")


def validate_pdf(
    path: Path,
    min_pages: int = 1,
    identity_terms: tuple[str, ...] = ("super hi", "特海"),
) -> dict:
    data = path.read_bytes()
    if len(data) < 10_000 or not data.startswith(b"%PDF-"):
        raise RuntimeError(f"Invalid PDF: {path}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"Too few pages: {path.name}: {pages}")
    check = subprocess.run(
        ["qpdf", "--check", str(path)], capture_output=True, text=True
    )
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed: {path.name}: {check.stderr[-1200:]}")
    for page_number in sorted({1, pages}):
        prefix = render_dir / (
            f"{hashlib.sha1(str(path).encode()).hexdigest()}_{page_number}"
        )
        render = subprocess.run(
            [
                "pdftoppm",
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-r",
                "72",
                "-png",
                "-singlefile",
                str(path),
                str(prefix),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        image = Path(str(prefix) + ".png")
        if (
            render.returncode != 0
            or not image.exists()
            or image.stat().st_size < 1_000
        ):
            raise RuntimeError(
                f"Render failed: {path.name} page {page_number}: "
                f"{render.stderr[-1000:]}"
            )
    sample_text = ""
    indexes = list(range(min(5, pages)))
    if pages > 5:
        indexes.append(pages - 1)
    for index in indexes:
        try:
            sample_text += "\n" + (reader.pages[index].extract_text() or "")
        except Exception:
            pass
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "first_last_page_rendered": True,
        "identity_text_verified_when_extractable": any(
            term.lower() in sample_text.lower() for term in identity_terms
        ),
    }


records: list[dict] = []
seen_hashes: set[str] = set()


def register(
    path: Path,
    *,
    title: str,
    document_type: str,
    publication_date: str,
    source: str,
    source_url: str,
    notes: str = "",
    min_pages: int = 1,
    identity_terms: tuple[str, ...] = ("super hi", "特海"),
) -> None:
    metadata = validate_pdf(path, min_pages, identity_terms)
    if metadata["sha256"] in seen_hashes:
        raise RuntimeError(f"Duplicate PDF: {path.name}")
    seen_hashes.add(metadata["sha256"])
    record = {
        "relative_path": str(path.relative_to(root)),
        "filename": path.name,
        "title": title,
        "document_type": document_type,
        "publication_date": publication_date,
        "source": source,
        "source_url": source_url,
        "notes": notes,
        **metadata,
    }
    records.append(record)
    print("REGISTERED", json.dumps(record, ensure_ascii=False), flush=True)


# 2022 annual report from HKEX.
rows = hkex_links("20230320", "20230415")
selected = choose_hkex_link(rows, ("2022", "annual report"))
path = annual_dir / "2022_特海国际_年度报告_港交所官方.pdf"
final_url = download_pdf(
    selected["href"], path, referer=selected["page"], min_bytes=500_000
)
register(
    path,
    title="特海国际2022年度报告",
    document_type="年度报告",
    publication_date="2023-03-30",
    source="香港交易所披露易",
    source_url=final_url,
    min_pages=150,
)

# 2023-2025 annual reports from official IR direct files.
direct_annual_reports = [
    (
        2023,
        "2024-04-25",
        "https://ir.superhiinternational.com/static-files/b8f31775-61bb-4eca-afce-7615cdff1d5e",
    ),
    (
        2024,
        "2025-04-24",
        "https://ir.superhiinternational.com/system/files-encrypted/nasdaq_kms/assets/2025/04/25/4-08-20/2024%20Annual%20Report.pdf",
    ),
    (
        2025,
        "2026-04-13",
        "https://ir.superhiinternational.com/static-files/6bc00940-9e5c-4e91-a460-608a4124d124",
    ),
]
for year, publication_date, url in direct_annual_reports:
    path = annual_dir / f"{year}_特海国际_年度报告_官方双语版.pdf"
    final_url = download_pdf(
        url,
        path,
        referer="https://ir.superhiinternational.com/financial-information/annual-reports",
        min_bytes=500_000,
    )
    register(
        path,
        title=f"特海国际{year}年度报告",
        document_type="年度报告",
        publication_date=publication_date,
        source="特海国际投资者关系网站",
        source_url=final_url,
        min_pages=150,
    )

# 2022 Hong Kong listing document by way of introduction.
rows = hkex_links("20221215", "20221231")
selected = choose_hkex_link(
    rows, ("listing document",), ("display document",)
)
path = offering_dir / "2022_特海国际_香港联交所以介绍方式上市文件.pdf"
final_url = download_pdf(
    selected["href"], path, referer=selected["page"], min_bytes=500_000
)
register(
    path,
    title="特海国际香港联交所以介绍方式上市文件",
    document_type="香港上市文件（介绍方式）",
    publication_date="2022-12-19",
    source="香港交易所披露易",
    source_url=final_url,
    notes="香港上市采用介绍方式，不涉及公开发售。",
    min_pages=200,
    identity_terms=("super hi", "listing document", "特海"),
)

# 2024 U.S. ADS final prospectus.
filing_page = (
    "https://ir.superhiinternational.com/sec-filings/sec-filing/"
    "424b4/0001104659-24-062760"
)
pdf_url, filing_referer = pdf_link_from_ir_filing(filing_page)
path = offering_dir / "2024_特海国际_美国ADS首次公开发行最终招股说明书_Form424B4.pdf"
final_url = download_pdf(
    pdf_url, path, referer=filing_referer, min_bytes=500_000
)
register(
    path,
    title="特海国际美国ADS首次公开发行最终招股说明书（Form 424B4）",
    document_type="美国IPO最终招股说明书",
    publication_date="2024-05-17",
    source="特海国际投资者关系网站/美国SEC申报",
    source_url=final_url,
    notes="NASDAQ代码HDL。",
    min_pages=150,
    identity_terms=("super hi", "prospectus", "american depositary"),
)

# 2026 formal interim report.
rows = hkex_links("20260915", "20260925")
selected = choose_hkex_link(rows, ("2026", "interim report"))
path = latest_dir / "2026_特海国际_中期报告_截至2026年6月30日止六个月.pdf"
final_url = download_pdf(
    selected["href"], path, referer=selected["page"], min_bytes=100_000
)
register(
    path,
    title="特海国际2026年中期报告",
    document_type="中期报告",
    publication_date="2026-09-22",
    source="香港交易所披露易",
    source_url=final_url,
    min_pages=50,
)

# Latest quarterly results, Q2 2026.
rows = hkex_links("20260820", "20260830")
selected = choose_hkex_link(
    rows, ("second quarter", "2026", "unaudited financial results")
)
path = latest_dir / "2026_Q2_特海国际_第二季度未经审核财务业绩.pdf"
final_url = download_pdf(
    selected["href"], path, referer=selected["page"], min_bytes=50_000
)
register(
    path,
    title="特海国际2026年第二季度未经审核财务业绩",
    document_type="最新季度业绩",
    publication_date="2026-08-26",
    source="香港交易所披露易",
    source_url=final_url,
    min_pages=5,
    identity_terms=("super hi", "second quarter", "2026"),
)

annual_years = sorted(
    int(record["title"].split("特海国际")[1][:4])
    for record in records
    if record["document_type"] == "年度报告"
)
if annual_years != [2022, 2023, 2024, 2025]:
    raise RuntimeError(f"Incomplete annual-report coverage: {annual_years}")
required_types = {
    "香港上市文件（介绍方式）",
    "美国IPO最终招股说明书",
    "中期报告",
    "最新季度业绩",
}
existing_types = {record["document_type"] for record in records}
if not required_types.issubset(existing_types):
    raise RuntimeError(f"Missing required types: {required_types - existing_types}")

manifest = {
    "issuer": "SUPER HI INTERNATIONAL HOLDING LTD. / 特海国际控股有限公司",
    "hk_ticker": "09658",
    "nasdaq_ticker": "HDL",
    "checked_as_of": "2026-09-27",
    "record_count": len(records),
    "records": records,
}
(root / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)

with (root / "文件清单.csv").open(
    "w", newline="", encoding="utf-8-sig"
) as file:
    writer = csv.writer(file)
    writer.writerow(
        [
            "相对路径",
            "文件类型",
            "发布日期",
            "页数",
            "字节数",
            "SHA-256",
            "来源",
            "来源网址",
            "备注",
        ]
    )
    for record in records:
        writer.writerow(
            [
                record["relative_path"],
                record["document_type"],
                record["publication_date"],
                record["pages"],
                record["bytes"],
                record["sha256"],
                record["source"],
                record["source_url"],
                record["notes"],
            ]
        )

readme = """特海国际控股有限公司（09658.HK / NASDAQ: HDL）官方披露文件包
核对日期：2026年9月27日

收录：
1. 2022—2025年度报告，共4份。
2. 2022年香港联交所以介绍方式上市文件。香港上市不涉及公开发售，因此文件名称为“上市文件”。
3. 2024年美国ADS首次公开发行最终招股说明书（Form 424B4）。
4. 最新正式阶段性报告：2026年中期报告。
5. 最新季度业绩：2026年第二季度未经审核财务业绩。

每份PDF均完成文件头、实际页数、qpdf结构和首末页渲染检查。来源、页数、大小及SHA-256见manifest.json和文件清单.csv。
"""
(root / "00_文件清单与范围说明.txt").write_text(readme, encoding="utf-8")

checksums: list[str] = []
for file in sorted(root.rglob("*")):
    if file.is_file() and file.name != "SHA256SUMS.txt":
        checksums.append(f"{sha256(file)}  {file.relative_to(root)}")
(root / "SHA256SUMS.txt").write_text(
    "\n".join(checksums) + "\n", encoding="utf-8"
)

zip_path = Path(PACKAGE + ".zip")
with zipfile.ZipFile(
    zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True
) as archive:
    for file in sorted(root.rglob("*")):
        if file.is_file():
            archive.write(
                file,
                arcname=str(Path(PACKAGE) / file.relative_to(root)),
            )
with zipfile.ZipFile(zip_path, "r") as archive:
    bad_file = archive.testzip()
    if bad_file:
        raise RuntimeError(f"ZIP CRC failure: {bad_file}")

print("FINAL_ZIP", zip_path, zip_path.stat().st_size, sha256(zip_path), flush=True)
print("RECORDS", json.dumps(records, ensure_ascii=False), flush=True)
