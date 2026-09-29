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
ISSUER = "深圳市长盈精密技术股份有限公司"
SHORT_NAME = "长盈精密"
STOCK_CODE = "300115"
PACKAGE = "长盈精密_300115_2020-2025年报及2026年最新季报"
ROOT = Path(PACKAGE)
ANNUAL_DIR = ROOT / "01_年度报告"
QUARTER_DIR = ROOT / "02_最新季报"
VERIFY_DIR = ROOT / "03_说明与校验"
WORK_DIR = Path("_changying_300115_v2_work")
RENDER_DIR = WORK_DIR / "renders"
ZIP_PATH = Path(PACKAGE + ".zip")

for directory in (ANNUAL_DIR, QUARTER_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

DOCUMENTS: list[dict[str, Any]] = [
    {
        "label": "2020年年度报告",
        "document_type": "年度报告",
        "fiscal_year": 2020,
        "published_date": "2021-04-28",
        "source_url": "https://static.cninfo.com.cn/finalpage/2021-04-28/1209829375.PDF",
        "path": ANNUAL_DIR / "2020_长盈精密_年度报告全文.pdf",
        "min_pages": 80,
        "min_bytes": 100_000,
    },
    {
        "label": "2021年年度报告",
        "document_type": "年度报告",
        "fiscal_year": 2021,
        "published_date": "2022-04-27",
        "source_url": "https://static.cninfo.com.cn/finalpage/2022-04-27/1213139649.PDF",
        "path": ANNUAL_DIR / "2021_长盈精密_年度报告全文.pdf",
        "min_pages": 80,
        "min_bytes": 100_000,
    },
    {
        "label": "2022年年度报告（更新后）",
        "document_type": "年度报告",
        "fiscal_year": 2022,
        "published_date": "2023-06-09",
        "source_url": "https://static.cninfo.com.cn/finalpage/2023-06-09/1217028221.PDF",
        "path": ANNUAL_DIR / "2022_长盈精密_年度报告全文_更新后.pdf",
        "min_pages": 80,
        "min_bytes": 100_000,
    },
    {
        "label": "2023年年度报告",
        "document_type": "年度报告",
        "fiscal_year": 2023,
        "published_date": "2024-03-19",
        "source_url": "https://static.cninfo.com.cn/finalpage/2024-03-19/1219329637.PDF",
        "path": ANNUAL_DIR / "2023_长盈精密_年度报告全文.pdf",
        "min_pages": 80,
        "min_bytes": 100_000,
    },
    {
        "label": "2024年年度报告",
        "document_type": "年度报告",
        "fiscal_year": 2024,
        "published_date": "2025-04-18",
        "source_url": "https://static.cninfo.com.cn/finalpage/2025-04-18/1223124284.PDF",
        "path": ANNUAL_DIR / "2024_长盈精密_年度报告全文.pdf",
        "min_pages": 80,
        "min_bytes": 100_000,
    },
    {
        "label": "2025年年度报告",
        "document_type": "年度报告",
        "fiscal_year": 2025,
        "published_date": "2026-04-18",
        "source_url": "https://static.cninfo.com.cn/finalpage/2026-04-18/1225120097.PDF",
        "path": ANNUAL_DIR / "2025_长盈精密_年度报告全文.pdf",
        "min_pages": 80,
        "min_bytes": 100_000,
    },
    {
        "label": "2026年第一季度报告",
        "document_type": "季度报告",
        "fiscal_year": 2026,
        "published_date": "2026-04-23",
        "source_url": "https://static.cninfo.com.cn/finalpage/2026-04-23/1225144413.PDF",
        "path": QUARTER_DIR / "2026_Q1_长盈精密_第一季度报告.pdf",
        "min_pages": 5,
        "min_bytes": 10_000,
    },
]

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/pdf,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.cninfo.com.cn/",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_pdf(url: str, destination: Path, min_bytes: int) -> str:
    errors: list[str] = []
    for attempt in range(1, 7):
        temp = destination.with_suffix(destination.suffix + ".part")
        temp.unlink(missing_ok=True)
        response = None
        try:
            response = SESSION.get(
                url,
                headers=HEADERS,
                stream=True,
                timeout=(25, 600),
                allow_redirects=True,
            )
            print(
                "HTTP", url, "attempt", attempt, "status", response.status_code,
                "type", response.headers.get("content-type"),
                "length", response.headers.get("content-length"),
                "final", response.url,
                flush=True,
            )
            response.raise_for_status()
            with temp.open("wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        handle.write(chunk)
            size = temp.stat().st_size
            head = temp.read_bytes()[:8]
            if size < min_bytes or not head.startswith(b"%PDF-"):
                raise RuntimeError(f"invalid PDF: bytes={size}, head={head!r}")
            final_url = str(response.url)
            temp.replace(destination)
            print("DOWNLOADED", destination, destination.stat().st_size, flush=True)
            return final_url
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            print("DOWNLOAD_RETRY", destination.name, errors[-1], flush=True)
            time.sleep(min(2 * attempt, 12))
        finally:
            if response is not None:
                response.close()
    raise RuntimeError(f"download failed for {destination.name}: {errors}")


def render_page(path: Path, page_number: int, tag: str) -> None:
    prefix = RENDER_DIR / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{tag}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
            "-r", "84", "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    image = Path(str(prefix) + ".png")
    valid = (
        process.returncode == 0
        and image.exists()
        and image.stat().st_size > 1000
        and image.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(
            f"render validation failed for {path.name}, page {page_number}: "
            f"{process.stderr[-1500:]}"
        )
    image.unlink()


def validate_pdf(path: Path, fiscal_year: int, document_type: str, min_pages: int) -> dict[str, Any]:
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
    if pages < min_pages:
        raise RuntimeError(f"unexpectedly short PDF {path.name}: {pages} pages")

    render_page(path, 1, "first")
    if pages > 1:
        render_page(path, pages, "last")

    indices = list(range(min(12, pages)))
    if pages > 12:
        indices.append(pages - 1)
    sample = "\n".join((reader.pages[index].extract_text() or "") for index in indices)
    normalized = re.sub(r"\s+", "", sample)
    identity_ok = SHORT_NAME in normalized or ISSUER in normalized
    if sample.strip() and not identity_ok:
        raise RuntimeError(f"issuer identity not found in sampled text for {path.name}")
    if sample.strip() and str(fiscal_year) not in normalized:
        raise RuntimeError(f"fiscal year {fiscal_year} not found in sampled text for {path.name}")

    first_text = "\n".join((reader.pages[index].extract_text() or "") for index in range(min(8, pages)))
    first_normalized = re.sub(r"\s+", "", first_text)
    if document_type == "年度报告":
        if "年度报告摘要" in first_normalized:
            raise RuntimeError(f"annual report summary detected: {path.name}")
        if first_text.strip() and "年度报告" not in first_normalized:
            raise RuntimeError(f"annual-report title not found: {path.name}")
    elif document_type == "季度报告":
        if first_text.strip() and not re.search(r"(?:一|第一|三|第三)季度报告", first_normalized):
            raise RuntimeError(f"quarterly-report title not found: {path.name}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "render_verified_first_and_last_page": True,
        "issuer_identity_verified_when_text_extractable": identity_ok,
        "sample_text_extractable": bool(sample.strip()),
    }


records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()
for document in DOCUMENTS:
    destination: Path = document["path"]
    final_url = download_pdf(document["source_url"], destination, document["min_bytes"])
    metadata = validate_pdf(
        destination,
        document["fiscal_year"],
        document["document_type"],
        document["min_pages"],
    )
    if metadata["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate document detected: {destination.name}")
    seen_hashes.add(metadata["sha256"])
    records.append({
        "label": document["label"],
        "document_type": document["document_type"],
        "fiscal_year": document["fiscal_year"],
        "relative_path": str(destination.relative_to(ROOT)),
        "published_date": document["published_date"],
        "source": "巨潮资讯网（官方信息披露平台）",
        "source_url": final_url,
        **metadata,
    })

manifest = {
    "issuer": ISSUER,
    "short_name": SHORT_NAME,
    "stock_code": STOCK_CODE,
    "checked_as_of": CHECKED_AS_OF,
    "document_count": len(records),
    "documents": records,
}
(VERIFY_DIR / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

fieldnames = [
    "label", "document_type", "fiscal_year", "relative_path", "published_date",
    "source", "source_url", "pages", "bytes", "sha256", "qpdf_return_code",
    "render_verified_first_and_last_page",
    "issuer_identity_verified_when_text_extractable", "sample_text_extractable",
]
with (VERIFY_DIR / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(records)

(VERIFY_DIR / "SHA256SUMS.txt").write_text(
    "\n".join(f"{row['sha256']}  {row['relative_path']}" for row in records) + "\n",
    encoding="utf-8",
)

readme = [
    f"{ISSUER}（{STOCK_CODE}）定期报告压缩包",
    "",
    f"核对日期：{CHECKED_AS_OF}",
    "来源：巨潮资讯网（上市公司官方信息披露平台）",
    "",
    "包含文件：",
    "- 2020—2025年度报告全文，共6份；",
    "- 截至核对日最新季度报告：2026年第一季度报告，共1份。",
    "",
    "说明：2022年度报告采用巨潮资讯网披露的更新后版本。",
    "所有PDF已完成文件头、文件大小、页数、qpdf结构检查，以及首尾页渲染验证。",
    "详细来源链接、页数、文件大小和SHA-256见manifest.csv、manifest.json及SHA256SUMS.txt。",
    "",
    "文件清单：",
]
for row in records:
    readme.append(
        f"- {row['label']}｜{row['relative_path']}｜{row['pages']}页｜披露日{row['published_date']}"
    )
(VERIFY_DIR / "README.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")

ZIP_PATH.unlink(missing_ok=True)
with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, arcname=str(path))

if not ZIP_PATH.exists() or ZIP_PATH.stat().st_size < 500_000:
    raise RuntimeError(f"ZIP creation failed or unexpectedly small: {ZIP_PATH}")
with zipfile.ZipFile(ZIP_PATH, "r") as archive:
    bad_member = archive.testzip()
    if bad_member:
        raise RuntimeError(f"ZIP integrity failure at {bad_member}")

print("FINAL_ZIP", ZIP_PATH, ZIP_PATH.stat().st_size, flush=True)
print("DOCUMENT_COUNT", len(records), flush=True)
