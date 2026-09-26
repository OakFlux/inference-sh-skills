from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import time
import zipfile
from pathlib import Path

import requests
from pypdf import PdfReader

PACKAGE = "中国建材_03323_2020-2025年报_2026最新定期报告"
ROOT = Path(PACKAGE)
ANNUAL_DIR = ROOT / "01_年度报告"
LATEST_DIR = ROOT / "02_最新定期报告"
META_DIR = ROOT / "03_说明与校验"
WORK = Path("_cnbm_final_work")
RENDER_DIR = WORK / "renders"
for directory in (ANNUAL_DIR, LATEST_DIR, META_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_pdf(urls: list[str], destination: Path, min_bytes: int) -> str:
    errors: list[str] = []
    candidates: list[str] = []
    for url in urls:
        candidates.append(url)
        if "www1.hkexnews.hk" in url:
            candidates.append(url.replace("www1.hkexnews.hk", "www.hkexnews.hk"))
        elif "www.hkexnews.hk" in url:
            candidates.append(url.replace("www.hkexnews.hk", "www1.hkexnews.hk"))
    for url in dict.fromkeys(candidates):
        for attempt in range(1, 5):
            partial = destination.with_suffix(destination.suffix + ".part")
            partial.unlink(missing_ok=True)
            try:
                headers = dict(HEADERS)
                headers["Referer"] = "https://www1.hkexnews.hk/" if "hkexnews.hk" in url else "https://financialfilings.com/"
                response = SESSION.get(url, headers=headers, timeout=(20, 300), allow_redirects=True, stream=True)
                print("GET", url, "attempt", attempt, "status", response.status_code,
                      "type", response.headers.get("content-type"), "length", response.headers.get("content-length"),
                      "final", response.url, flush=True)
                response.raise_for_status()
                try:
                    with partial.open("wb") as output:
                        for chunk in response.iter_content(1024 * 1024):
                            if chunk:
                                output.write(chunk)
                    final_url = str(response.url)
                finally:
                    response.close()
                size = partial.stat().st_size
                head = partial.read_bytes()[:8]
                if size < min_bytes or not head.startswith(b"%PDF-"):
                    raise RuntimeError(f"not PDF or too small: bytes={size}, head={head!r}")
                partial.replace(destination)
                return final_url
            except Exception as exc:
                errors.append(f"{url} attempt {attempt}: {exc!r}")
                partial.unlink(missing_ok=True)
                time.sleep(min(attempt * 2, 8))
    raise RuntimeError(f"download failed for {destination.name}: {errors[-10:]}")


def validate_pdf(path: Path, min_pages: int) -> dict:
    if not path.exists() or path.stat().st_size < 10_000 or not path.read_bytes()[:8].startswith(b"%PDF-"):
        raise RuntimeError(f"invalid PDF file: {path}")
    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf validation failed for {path.name}: {qpdf.stderr[-2000:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"unexpected page count for {path.name}: {pages}")
    for page_no in sorted(set((1, pages))):
        prefix = RENDER_DIR / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{page_no}"
        result = subprocess.run(
            ["pdftoppm", "-f", str(page_no), "-l", str(page_no), "-r", "72", "-png", "-singlefile", str(path), str(prefix)],
            capture_output=True, text=True, timeout=240,
        )
        png = Path(str(prefix) + ".png")
        if result.returncode != 0 or not png.exists() or png.stat().st_size < 800 or not png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError(f"render check failed for {path.name}, page {page_no}: {result.stderr[-1200:]}")
        png.unlink()
    sample_text = ""
    try:
        indices = list(range(min(8, pages)))
        if pages > 8:
            indices.append(pages - 1)
        sample_text = "\n".join((reader.pages[index].extract_text() or "") for index in indices)
    except Exception as exc:
        print("TEXT_EXTRACTION_WARNING", path.name, repr(exc), flush=True)
    identity_ok = any(term.lower() in sample_text.lower() for term in (
        "China National Building Material", "CNBM", "03323", "中國建材", "中国建材"
    ))
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "first_and_last_page_rendered": True,
        "identity_text_verified_when_extractable": identity_ok,
    }


documents = [
    {
        "filename": "2020_中国建材_年度报告_英文版.pdf",
        "directory": ANNUAL_DIR,
        "type": "年度报告",
        "fiscal_year": 2020,
        "publication_date": "2021-04-08",
        "urls": ["https://www1.hkexnews.hk/listedco/listconews/sehk/2021/0408/2021040801378.pdf"],
        "source": "香港交易所披露易官方PDF",
        "min_bytes": 1_000_000,
        "min_pages": 50,
    },
    {
        "filename": "2021_中国建材_年度报告_英文版.pdf",
        "directory": ANNUAL_DIR,
        "type": "年度报告",
        "fiscal_year": 2021,
        "publication_date": "2022-04-13",
        "urls": ["https://www1.hkexnews.hk/listedco/listconews/sehk/2022/0413/2022041300586.pdf"],
        "source": "香港交易所披露易官方PDF",
        "min_bytes": 1_000_000,
        "min_pages": 50,
    },
    {
        "filename": "2022_中国建材_年度报告_英文版.pdf",
        "directory": ANNUAL_DIR,
        "type": "年度报告",
        "fiscal_year": 2022,
        "publication_date": "2023-04-04",
        "urls": ["https://www1.hkexnews.hk/listedco/listconews/sehk/2023/0404/2023040401493.pdf"],
        "source": "香港交易所披露易官方PDF",
        "min_bytes": 1_000_000,
        "min_pages": 50,
    },
    {
        "filename": "2023_中国建材_年度报告_英文版.pdf",
        "directory": ANNUAL_DIR,
        "type": "年度报告",
        "fiscal_year": 2023,
        "publication_date": "2024-03-28",
        "urls": ["https://www1.hkexnews.hk/listedco/listconews/sehk/2024/0328/2024032802318.pdf"],
        "source": "香港交易所披露易官方PDF",
        "min_bytes": 1_000_000,
        "min_pages": 50,
    },
    {
        "filename": "2024_中国建材_年度报告_英文版.pdf",
        "directory": ANNUAL_DIR,
        "type": "年度报告",
        "fiscal_year": 2024,
        "publication_date": "2025-03-27",
        "urls": ["https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0327/2025032702837.pdf"],
        "source": "香港交易所披露易官方PDF",
        "min_bytes": 1_000_000,
        "min_pages": 50,
    },
    {
        "filename": "2025_中国建材_年度报告_英文版.pdf",
        "directory": ANNUAL_DIR,
        "type": "年度报告",
        "fiscal_year": 2025,
        "publication_date": "2026-03-31",
        "urls": ["https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0331/2026033100719.pdf"],
        "source": "香港交易所披露易官方PDF",
        "min_bytes": 1_000_000,
        "min_pages": 50,
    },
    {
        "filename": "2026_中国建材_第一季度报告_英文版.pdf",
        "directory": LATEST_DIR,
        "type": "第一季度报告",
        "fiscal_year": 2026,
        "publication_date": "2026-04-29",
        "urls": ["https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0429/2026042905824.pdf"],
        "source": "香港交易所披露易官方PDF",
        "min_bytes": 80_000,
        "min_pages": 10,
    },
    {
        "filename": "2026_中国建材_中期报告_英文版_补充.pdf",
        "directory": LATEST_DIR,
        "type": "中期报告",
        "fiscal_year": 2026,
        "publication_date": "2026-08-27",
        "urls": [
            "https://cdn.financialreports.eu/financialreports/media/filings/50813/2026/RNS/50813_rns_2026-08-27_6205455f-f997-4154-8cbf-cc9cba3c3524.pdf"
        ],
        "source": "港交所披露原件的可核验镜像（FinancialFilings CDN）",
        "min_bytes": 500_000,
        "min_pages": 80,
    },
]

records: list[dict] = []
seen_hashes: set[str] = set()
for item in documents:
    destination = item["directory"] / item["filename"]
    final_url = download_pdf(item["urls"], destination, item["min_bytes"])
    validation = validate_pdf(destination, item["min_pages"])
    if validation["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate PDF detected: {item['filename']}")
    seen_hashes.add(validation["sha256"])
    record = {
        "relative_path": str(destination.relative_to(ROOT)),
        "filename": item["filename"],
        "document_type": item["type"],
        "fiscal_year": item["fiscal_year"],
        "publication_date": item["publication_date"],
        "language": "English",
        "source": item["source"],
        "source_url": final_url,
        **validation,
    }
    records.append(record)
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

manifest = {
    "package_name": PACKAGE,
    "issuer": "中国建材股份有限公司 / China National Building Material Company Limited",
    "stock_code": "03323.HK",
    "checked_as_of": "2026-09-26",
    "coverage": {
        "annual_reports": "2020-2025，共6份完整年度报告",
        "latest_quarterly_report": "2026年第一季度报告，2026-04-29披露",
        "supplemental_latest_periodic_report": "2026年中期报告，2026-08-27披露，因披露日期更晚一并收录",
    },
    "pdf_count": len(records),
    "records": records,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (ROOT / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as file:
    writer = csv.writer(file)
    writer.writerow(["相对路径", "文件类型", "会计年度", "披露日期", "语言", "页数", "字节数", "SHA-256", "来源", "来源网址"])
    for record in records:
        writer.writerow([
            record["relative_path"], record["document_type"], record["fiscal_year"], record["publication_date"],
            record["language"], record["pages"], record["bytes"], record["sha256"], record["source"], record["source_url"],
        ])

readme = f"""中国建材股份有限公司（03323.HK）定期报告文件包

核对日期：2026年9月26日

收录范围
- 2020—2025年度报告：6份，均为香港交易所披露易官方英文PDF原件。
- 2026年第一季度报告：截至核对日的最新正式季度报告，香港交易所披露易官方PDF原件。
- 2026年中期报告：披露时间晚于第一季度报告，作为最新阶段性财务信息补充收录；文件为港交所披露原件的可核验镜像。

质量检查
- PDF数量：{len(records)}。
- 每份PDF均完成文件头、页数和qpdf结构检查，并渲染首末页验证可读性。
- manifest.json和文件清单.csv记录每份文件的来源、页数、大小和SHA-256。
- ZIP完成后执行CRC完整性检查。
"""
(ROOT / "00_文件清单与范围说明.txt").write_text(readme, encoding="utf-8")

checksums = []
for path in sorted(ROOT.rglob("*")):
    if path.is_file() and path.name != "SHA256SUMS.txt":
        checksums.append(f"{sha256(path)}  {path.relative_to(ROOT)}")
(ROOT / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")

zip_path = Path(PACKAGE + ".zip")
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, arcname=str(Path(PACKAGE) / path.relative_to(ROOT)))
with zipfile.ZipFile(zip_path, "r") as archive:
    bad = archive.testzip()
    if bad:
        raise RuntimeError(f"ZIP CRC failure: {bad}")

print("FINAL_ZIP", zip_path, zip_path.stat().st_size, sha256(zip_path), flush=True)
print("PDF_COUNT", len(records), flush=True)
