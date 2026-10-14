from __future__ import annotations

import csv
import hashlib
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

CHECKED_AS_OF = "2026-10-14"
COMPANY = "厦门松霖科技股份有限公司"
SHORT = "松霖科技"
CODE = "603992"
PACKAGE = "松霖科技_603992_券商研究报告_3份"
ROOT = Path(PACKAGE)
REPORT_DIR = ROOT / "01_券商研究报告"
VERIFY_DIR = ROOT / "02_说明与校验"
RENDER_DIR = Path("_solex_official_broker_renders")
for directory in (REPORT_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

# All PDFs below are linked from the company's official investor-relations research page.
CANDIDATES: list[dict[str, Any]] = [
    {
        "date": "2025-11-09",
        "broker": "国投证券",
        "title": "卡位机器人高增赛道，有望率先落地养老领域",
        "url": "https://img.solex-group.com/file/86/3e/42/5b2e031db18ebe6c54bf47ab57.pdf",
        "filename": "2025-11-09_国投证券_卡位机器人高增赛道_有望率先落地养老领域.pdf",
        "priority": 1,
    },
    {
        "date": "2025-07-22",
        "broker": "方正证券",
        "title": "创新驱动多品类协同发展，积极拓展机器人产业布局",
        "url": "https://img.solex-group.com/file/d2/8f/0b/6ee55dade1509b35688da54ddc.pdf",
        "filename": "2025-07-22_方正证券_首次覆盖_创新驱动多品类协同发展_积极拓展机器人产业布局.pdf",
        "priority": 2,
    },
    {
        "date": "2025-06-11",
        "broker": "财通证券",
        "title": "IDM技术固本，智能机器人谱新篇",
        "url": "https://img.solex-group.com/file/6a/4b/c3/c074d83950824439c8d307a758.pdf",
        "filename": "2025-06-11_财通证券_IDM技术固本_智能机器人谱新篇.pdf",
        "priority": 3,
    },
    # Fallbacks retained in case a primary source is temporarily unavailable.
    {
        "date": "2025-08-22",
        "broker": "东北证券",
        "title": "主业预计下半年恢复，养老机器人前景可期",
        "url": "https://img.solex-group.com/file/7f/45/81/a7b2f8eaa7937b4bb985e411c1.pdf",
        "filename": "2025-08-22_东北证券_主业预计下半年恢复_养老机器人前景可期.pdf",
        "priority": 4,
    },
    {
        "date": "2025-09-30",
        "broker": "东方财富证券",
        "title": "智能厨卫+大健康领先厂商，布局机器人整机",
        "url": "https://img.solex-group.com/file/ef/df/7a/54e0f9c931220feff2e6d61c16.pdf",
        "filename": "2025-09-30_东方财富证券_智能厨卫+大健康领先厂商_布局机器人整机.pdf",
        "priority": 5,
    },
]

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/155 Safari/537.36",
    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.5",
    "Referer": "https://www.solex.cn/research.html",
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def compact(text: str) -> str:
    return re.sub(r"[\s，,。：:；;（）()·•—\-_/]+", "", text or "").lower()


def download(candidate: dict[str, Any], destination: Path) -> str:
    errors: list[str] = []
    for attempt in range(1, 6):
        temp = destination.with_suffix(".pdf.part")
        temp.unlink(missing_ok=True)
        try:
            with SESSION.get(candidate["url"], headers=HEADERS, stream=True, timeout=(25, 360), allow_redirects=True) as response:
                print("GET", candidate["broker"], attempt, response.status_code, response.headers.get("content-type"), response.url, flush=True)
                response.raise_for_status()
                with temp.open("wb") as handle:
                    for block in response.iter_content(1024 * 1024):
                        if block:
                            handle.write(block)
                resolved = str(response.url)
            size = temp.stat().st_size
            head = temp.read_bytes()[:1024]
            if size < 50_000 or b"%PDF-" not in head:
                raise RuntimeError(f"invalid PDF payload: size={size}, head={head[:32]!r}")
            temp.replace(destination)
            return resolved
        except Exception as exc:  # noqa: BLE001
            temp.unlink(missing_ok=True)
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(3 * attempt, 12))
    raise RuntimeError("download failed: " + " | ".join(errors))


def sample_text(reader: PdfReader) -> str:
    count = len(reader.pages)
    indices = sorted({0, min(1, count - 1), count // 2, count - 1})
    pieces: list[str] = []
    for index in indices:
        try:
            pieces.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_WARNING", index + 1, repr(exc), flush=True)
    return compact("\n".join(pieces))


def render_page(pdf_path: Path, page: int) -> Path:
    stem = RENDER_DIR / f"{pdf_path.stem}_p{page}"
    proc = subprocess.run(
        ["pdftoppm", "-f", str(page), "-l", str(page), "-r", "130", "-png", "-singlefile", str(pdf_path), str(stem)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    png = Path(str(stem) + ".png")
    if proc.returncode != 0 or not png.exists() or png.stat().st_size < 3000:
        raise RuntimeError(f"render failed for {pdf_path.name} page {page}: {proc.stderr[-1200:]}")
    return png


def validate(candidate: dict[str, Any], path: Path) -> dict[str, Any]:
    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed: {qpdf.stderr[-1600:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 3:
        raise RuntimeError(f"too few pages: {pages}")
    text = sample_text(reader)
    if text and not any(marker in text for marker in (compact(SHORT), compact(CODE), compact(candidate["title"][:10]))):
        raise RuntimeError("company/title marker not found in extracted text")
    page_samples = sorted({1, max(1, (pages + 1) // 2), pages})
    renders = [str(render_page(path, page)) for page in page_samples]
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": digest(path),
        "qpdf_return_code": qpdf.returncode,
        "rendered_pages": page_samples,
        "render_files": renders,
    }


def main() -> None:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    used_brokers: set[str] = set()
    for candidate in sorted(CANDIDATES, key=lambda item: item["priority"]):
        if len(records) >= 3:
            break
        if candidate["broker"] in used_brokers:
            continue
        destination = REPORT_DIR / candidate["filename"]
        try:
            resolved_url = download(candidate, destination)
            check = validate(candidate, destination)
            record = {
                "file": str(destination),
                "publish_date": candidate["date"],
                "broker": candidate["broker"],
                "title": candidate["title"],
                "official_research_page": "https://www.solex.cn/research.html",
                "official_pdf_url": candidate["url"],
                "resolved_pdf_url": resolved_url,
                **check,
            }
            records.append(record)
            used_brokers.add(candidate["broker"])
            print("SELECTED", record["publish_date"], record["broker"], record["pages"], record["title"], flush=True)
        except Exception as exc:  # noqa: BLE001
            destination.unlink(missing_ok=True)
            message = f"{candidate['date']} {candidate['broker']} {candidate['title']}: {exc!r}"
            errors.append(message)
            print("CANDIDATE_ERROR", message, flush=True)

    if len(records) != 3:
        raise RuntimeError(f"only obtained {len(records)} validated reports; errors: {' | '.join(errors)}")
    if len({record["sha256"] for record in records}) != 3:
        raise RuntimeError("duplicate PDF content detected")

    manifest = {
        "company": COMPANY,
        "stock_code": CODE,
        "checked_as_of": CHECKED_AS_OF,
        "source": "松霖科技官网投资者关系-研究报告",
        "selection_note": "优先选取机器人、IDM及公司首次覆盖/专题研究相关报告；若源文件临时不可用则采用官网同页的其他券商报告补足。",
        "reports": records,
        "download_errors": errors,
    }
    (VERIFY_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    with (VERIFY_DIR / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = [
            "file", "publish_date", "broker", "title", "pages", "bytes", "sha256",
            "official_research_page", "official_pdf_url", "resolved_pdf_url",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field, "") for field in fields})

    with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as handle:
        for record in records:
            relative = Path(record["file"]).relative_to(ROOT).as_posix()
            handle.write(f"{record['sha256']}  {relative}\n")

    readme = [
        f"{SHORT}（{CODE}）券商研究报告合集",
        f"核对日期：{CHECKED_AS_OF}",
        "",
        "来源：松霖科技官网投资者关系栏目中的研究报告页面及其直接链接PDF。",
        "本合集优先选择机器人、IDM及公司首次覆盖/专题研究相关报告，共3份。",
        "",
        "文件列表：",
    ]
    for index, record in enumerate(records, 1):
        readme.append(f"{index}. {record['publish_date']}｜{record['broker']}｜{record['title']}｜{record['pages']}页")
    readme.extend([
        "",
        "每份PDF均完成文件头、qpdf结构、页数、文本标识及首页/中间页/末页渲染检查。",
        "详细文件大小、来源及SHA-256校验值见02_说明与校验目录。",
        "报告仅供研究参考，不构成投资建议；版权归原券商及作者所有。",
    ])
    (ROOT / "README_文件说明.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")

    zip_path = Path(PACKAGE + ".zip")
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.as_posix())
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        pdf_count = sum(name.lower().endswith(".pdf") for name in archive.namelist())
        if bad:
            raise RuntimeError(f"bad ZIP member: {bad}")
        if pdf_count != 3:
            raise RuntimeError(f"ZIP contains {pdf_count} PDFs, expected 3")
    print("FINAL", zip_path, zip_path.stat().st_size, digest(zip_path), flush=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(RENDER_DIR, ignore_errors=True)
