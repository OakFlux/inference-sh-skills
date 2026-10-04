from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests
from pypdf import PdfReader

PACKAGE_NAME = "小熊电器_002959_2020-2025年报及2026最新定期报告"
ROOT = Path(PACKAGE_NAME)
ANNUAL_DIR = ROOT / "01_年度报告"
QUARTER_DIR = ROOT / "02_最新季报"
SUPPLEMENT_DIR = ROOT / "03_补充定期报告"
NOTES_DIR = ROOT / "04_说明"
WORK_DIR = Path("_xiaoxiong_002959_work")
RENDER_DIR = WORK_DIR / "renders"
FINAL_ZIP = Path(PACKAGE_NAME + ".zip")

for directory in (ANNUAL_DIR, QUARTER_DIR, SUPPLEMENT_DIR, NOTES_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.cninfo.com.cn/",
}
SESSION = requests.Session()
SESSION.trust_env = False

DOCUMENTS = [
    {
        "period": "2020",
        "document_type": "年度报告",
        "publication_date": "2021-04-29",
        "title": "小熊电器股份有限公司2020年年度报告",
        "url": "https://static.cninfo.com.cn/finalpage/2021-04-29/1209847840.PDF",
        "folder": ANNUAL_DIR,
        "filename": "2020_小熊电器_年度报告.pdf",
    },
    {
        "period": "2021",
        "document_type": "年度报告",
        "publication_date": "2022-04-09",
        "title": "小熊电器股份有限公司2021年年度报告",
        "url": "https://static.cninfo.com.cn/finalpage/2022-04-09/1212857533.PDF",
        "folder": ANNUAL_DIR,
        "filename": "2021_小熊电器_年度报告.pdf",
    },
    {
        "period": "2022",
        "document_type": "年度报告",
        "publication_date": "2023-04-07",
        "title": "小熊电器股份有限公司2022年年度报告",
        "url": "https://static.cninfo.com.cn/finalpage/2023-04-07/1216346105.PDF",
        "folder": ANNUAL_DIR,
        "filename": "2022_小熊电器_年度报告.pdf",
    },
    {
        "period": "2023",
        "document_type": "年度报告",
        "publication_date": "2024-04-09",
        "title": "小熊电器股份有限公司2023年年度报告",
        "url": "https://static.cninfo.com.cn/finalpage/2024-04-09/1219538007.PDF",
        "folder": ANNUAL_DIR,
        "filename": "2023_小熊电器_年度报告.pdf",
    },
    {
        "period": "2024",
        "document_type": "年度报告",
        "publication_date": "2025-04-09",
        "title": "小熊电器股份有限公司2024年年度报告",
        "url": "https://static.cninfo.com.cn/finalpage/2025-04-09/1223032188.PDF",
        "folder": ANNUAL_DIR,
        "filename": "2024_小熊电器_年度报告.pdf",
    },
    {
        "period": "2025",
        "document_type": "年度报告",
        "publication_date": "2026-04-09",
        "title": "小熊电器股份有限公司2025年年度报告",
        "url": "https://static.cninfo.com.cn/finalpage/2026-04-09/1225085711.PDF",
        "folder": ANNUAL_DIR,
        "filename": "2025_小熊电器_年度报告.pdf",
    },
    {
        "period": "2026Q1",
        "document_type": "第一季度报告",
        "publication_date": "2026-04-30",
        "title": "小熊电器股份有限公司2026年一季度报告",
        "url": "https://static.cninfo.com.cn/finalpage/2026-04-30/1225259657.PDF",
        "folder": QUARTER_DIR,
        "filename": "2026Q1_小熊电器_第一季度报告.pdf",
    },
    {
        "period": "2026H1",
        "document_type": "半年度报告（补充）",
        "publication_date": "2026-08-14",
        "title": "小熊电器股份有限公司2026年半年度报告",
        "url": "https://static.cninfo.com.cn/finalpage/2026-08-14/1225471529.PDF",
        "folder": SUPPLEMENT_DIR,
        "filename": "2026H1_小熊电器_半年度报告.pdf",
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_pdf(url: str, destination: Path) -> str:
    errors: list[str] = []
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    for attempt in range(1, 7):
        try:
            response = SESSION.get(
                url,
                headers=HEADERS,
                timeout=(25, 300),
                allow_redirects=True,
                stream=True,
            )
            print(
                "DOWNLOAD",
                destination.name,
                "attempt",
                attempt,
                "status",
                response.status_code,
                "type",
                response.headers.get("content-type"),
                "length",
                response.headers.get("content-length"),
                "final",
                response.url,
                flush=True,
            )
            response.raise_for_status()
            with temporary.open("wb") as output:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        output.write(chunk)
            final_url = str(response.url)
            response.close()
            size = temporary.stat().st_size
            header = temporary.read_bytes()[:8]
            if size < 20_000 or not header.startswith(b"%PDF-"):
                raise RuntimeError(f"invalid PDF bytes: size={size}, header={header!r}")
            temporary.replace(destination)
            return final_url
        except Exception as exc:
            errors.append(f"attempt {attempt}: {exc!r}")
            temporary.unlink(missing_ok=True)
            time.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"failed to download {destination.name}: {errors[-6:]}")


def page_count(path: Path) -> int:
    return len(PdfReader(str(path), strict=False).pages)


def extract_identity_text(path: Path, pages: int) -> tuple[str, bool]:
    text_path = WORK_DIR / (path.stem + "_identity.txt")
    text_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "pdftotext",
        "-f",
        "1",
        "-l",
        str(min(15, pages)),
        "-enc",
        "UTF-8",
        str(path),
        str(text_path),
    ]
    run = subprocess.run(command, capture_output=True, text=True, timeout=240)
    if run.returncode != 0 or not text_path.exists():
        return run.stderr[-1000:], False
    text = text_path.read_text(encoding="utf-8", errors="replace")
    compact = "".join(text.split())
    identity_ok = ("小熊电器" in compact) or ("002959" in compact)
    return text[:2000], identity_ok


def render_check(path: Path, pages: int) -> list[int]:
    selected = [1]
    if pages > 1:
        selected.append(pages)
    for page in selected:
        prefix = RENDER_DIR / f"{hashlib.sha1(str(path).encode('utf-8')).hexdigest()}_{page}"
        command = [
            "pdftoppm",
            "-f",
            str(page),
            "-l",
            str(page),
            "-r",
            "96",
            "-png",
            "-singlefile",
            str(path),
            str(prefix),
        ]
        run = subprocess.run(command, capture_output=True, text=True, timeout=240)
        png = Path(str(prefix) + ".png")
        if (
            run.returncode != 0
            or not png.exists()
            or png.stat().st_size < 1000
            or not png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        ):
            raise RuntimeError(f"render failed for {path.name} page {page}: {run.stderr[-1200:]}")
        png.unlink()
    return selected


def validate_pdf(path: Path) -> dict:
    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=240)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf validation failed for {path.name}: {qpdf.stderr[-1500:]}")
    pages = page_count(path)
    if pages < 1:
        raise RuntimeError(f"zero-page PDF: {path.name}")
    _, identity_ok = extract_identity_text(path, pages)
    rendered_pages = render_check(path, pages)
    if not identity_ok:
        print("IDENTITY_TEXT_WARNING", path.name, "text extraction did not expose company name or code", flush=True)
    return {
        "bytes": path.stat().st_size,
        "pages": pages,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "identity_text_verified_when_extractable": identity_ok,
        "rendered_pages": rendered_pages,
    }


def write_metadata(records: list[dict]) -> None:
    readme = f"""# 小熊电器（002959）定期报告资料包

生成日期：2026-10-04

## 文件范围

- 2020—2025年度报告：6份。
- 截至2026-10-04可取得的最新季度报告：2026年一季度报告，1份。
- 补充收录更新的定期报告：2026年半年度报告，1份。半年度报告不属于季度报告，单独存放。

## 来源与校验

全部报告均从巨潮资讯网官方静态披露文件下载，未以摘要替代完整报告。每份PDF均执行文件头、页数、qpdf结构检查，以及首页和末页渲染检查。`manifest.json`记录披露日期、官方来源、页数、字节数和SHA-256；`SHA256SUMS.txt`可用于完整性复核。

截至2026-10-04，2026年第三季度报告尚未披露，因此本包所称“最新季报”为2026年一季度报告。
"""
    (NOTES_DIR / "README.md").write_text(readme, encoding="utf-8")
    manifest = {
        "package_name": PACKAGE_NAME,
        "company": "小熊电器股份有限公司",
        "stock_code": "002959",
        "checked_as_of": "2026-10-04",
        "document_count": len(records),
        "annual_report_count": sum(r["document_type"] == "年度报告" for r in records),
        "latest_quarterly_report": "2026年一季度报告",
        "supplementary_periodic_report": "2026年半年度报告",
        "source": "巨潮资讯网官方披露",
        "validation": [
            "PDF文件头与最低文件大小",
            "qpdf结构检查",
            "pypdf页数读取",
            "首页与末页渲染检查",
            "可提取文本中的公司名称或股票代码检查",
            "SHA-256完整性记录",
        ],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "records": records,
    }
    (NOTES_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    checksum_lines = [f"{record['sha256']}  {record['relative_path']}" for record in records]
    (NOTES_DIR / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")


def build_zip() -> None:
    FINAL_ZIP.unlink(missing_ok=True)
    with zipfile.ZipFile(FINAL_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(path))
    with zipfile.ZipFile(FINAL_ZIP, "r") as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP CRC check failed at {bad}")
        names = archive.namelist()
        pdf_count = sum(name.lower().endswith(".pdf") for name in names)
        if pdf_count != 8:
            raise RuntimeError(f"unexpected PDF count in ZIP: {pdf_count}")
        if len(names) != 11:
            raise RuntimeError(f"unexpected total file count in ZIP: {len(names)}")
    print(
        "FINAL_ZIP",
        FINAL_ZIP.name,
        FINAL_ZIP.stat().st_size,
        sha256(FINAL_ZIP),
        flush=True,
    )


def main() -> None:
    records: list[dict] = []
    seen_hashes: set[str] = set()
    for document in DOCUMENTS:
        destination = document["folder"] / document["filename"]
        final_url = download_pdf(document["url"], destination)
        validation = validate_pdf(destination)
        if validation["sha256"] in seen_hashes:
            raise RuntimeError(f"duplicate PDF detected: {destination.name}")
        seen_hashes.add(validation["sha256"])
        record = {
            "period": document["period"],
            "document_type": document["document_type"],
            "title": document["title"],
            "publication_date": document["publication_date"],
            "source": "巨潮资讯网",
            "source_url": document["url"],
            "download_final_url": final_url,
            "relative_path": str(destination.relative_to(ROOT)),
            **validation,
        }
        records.append(record)
        print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)
    write_metadata(records)
    build_zip()
    print(
        json.dumps(
            {
                "package_name": PACKAGE_NAME,
                "annual_reports": 6,
                "latest_quarterly_report": "2026年一季度报告",
                "supplementary_report": "2026年半年度报告",
                "pdf_count": 8,
                "zip_bytes": FINAL_ZIP.stat().st_size,
                "zip_sha256": sha256(FINAL_ZIP),
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(WORK_DIR, ignore_errors=True)
