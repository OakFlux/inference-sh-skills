from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

STOCK_CODE = "601717"
CURRENT_SHORT_NAME = "中创智领"
FORMER_SHORT_NAME = "郑煤机"
CURRENT_COMPANY = "中创智领（郑州）工业技术集团股份有限公司"
FORMER_COMPANY = "郑州煤矿机械集团股份有限公司"
PACKAGE_NAME = "中创智领_原郑煤机_2020-2025年报及2026年最新半年报_完整PDF"

OUT = Path(PACKAGE_NAME)
ANNUAL_DIR = OUT / "01_年度报告_2020-2025"
HALF_DIR = OUT / "02_最新半年度报告"
WORK = Path("_zhongchuangzhiling_work")
RENDERS = WORK / "renders"
for directory in (ANNUAL_DIR, HALF_DIR, WORK, RENDERS):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36"
)
HTML_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Referer": "https://money.finance.sina.com.cn/",
}
PDF_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, *, headers: dict[str, str], attempts: int = 7, timeout=(30, 360)) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            response = SESSION.get(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            )
            print(
                "GET",
                attempt,
                response.status_code,
                response.headers.get("content-type"),
                len(response.content),
                response.url,
                flush=True,
            )
            if response.status_code == 200 and response.content:
                return response
            errors.append(f"HTTP {response.status_code}/{len(response.content)}")
        except Exception as exc:  # pragma: no cover - network diagnostic
            errors.append(repr(exc))
        time.sleep(min(attempt * 2, 12))
    raise RuntimeError(f"Unable to fetch {url}: {' | '.join(errors[-8:])}")


def decode_html(response: requests.Response) -> str:
    for encoding in ("gb18030", "gbk", "utf-8"):
        try:
            text = response.content.decode(encoding)
            if any(
                marker in text
                for marker in (
                    CURRENT_SHORT_NAME,
                    FORMER_SHORT_NAME,
                    CURRENT_COMPANY,
                    FORMER_COMPANY,
                    "年度报告",
                    "半年度报告",
                )
            ):
                return text
        except Exception:
            continue
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def parse_sina_listing(page_type: str) -> list[dict[str, str]]:
    url = (
        "https://money.finance.sina.com.cn/corp/go.php/"
        f"vCB_Bulletin/stockid/{STOCK_CODE}/page_type/{page_type}.phtml"
    )
    response = fetch(url, headers=HTML_HEADERS, timeout=(30, 240))
    text = decode_html(response)
    soup = BeautifulSoup(text, "html.parser")
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split())
        href = urljoin(response.url, html.unescape(anchor["href"]))
        if "vCB_AllBulletinDetail.php" not in href:
            continue
        if not label:
            continue
        key = (label, href)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"title": label, "detail_url": href})
    print("SINA_LIST", page_type, json.dumps(rows, ensure_ascii=False, indent=2), flush=True)
    if not rows:
        raise RuntimeError(f"No announcement entries found on Sina listing: {page_type}")
    return rows


def extract_sina_pdf(detail_url: str) -> str:
    response = fetch(detail_url, headers=HTML_HEADERS, timeout=(30, 300))
    text = decode_html(response)
    candidates: list[str] = []
    patterns = (
        r"https?://file\.finance\.sina\.com\.cn/[^\"'<>\s]+?\.pdf(?:\?[^\"'<>\s]*)?",
        r"https?:\\/\\/file\.finance\.sina\.com\.cn\\/[^\"'<>\s]+?\.pdf(?:\?[^\"'<>\s]*)?",
        r"https?://[^\"'<>\s]+?\.pdf(?:\?[^\"'<>\s]*)?",
    )
    normalized = html.unescape(text).replace("\\/", "/")
    for pattern in patterns:
        for match in re.findall(pattern, normalized, flags=re.I):
            candidate = html.unescape(match).replace("\\/", "/")
            if candidate not in candidates:
                candidates.append(candidate)
    soup = BeautifulSoup(text, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = urljoin(response.url, html.unescape(anchor["href"]))
        if ".pdf" in href.lower() and href not in candidates:
            candidates.append(href)
    candidates = [
        candidate
        for candidate in candidates
        if "finance.sina.com.cn" in candidate or "sse.com.cn" in candidate
    ]
    if not candidates:
        raise RuntimeError(f"No report PDF link found in detail page: {detail_url}")
    candidates.sort(key=lambda value: ("file.finance.sina.com.cn" not in value, len(value)))
    print("PDF_CANDIDATES", detail_url, json.dumps(candidates, ensure_ascii=False), flush=True)
    return candidates[0]


def annual_score(title: str, year: int, position: int) -> int:
    normalized = compact(title)
    if str(year) not in normalized or "年度报告" not in normalized:
        return -10_000
    excluded = (
        "摘要",
        "英文版",
        "英文",
        "社会责任",
        "环境、社会",
        "审计报告",
        "董事会",
        "监事会",
        "问询",
        "回复",
        "取消",
    )
    if any(marker in normalized for marker in excluded):
        return -10_000
    score = 1000 - position
    if any(marker in normalized for marker in ("修订", "更正后", "更新后")):
        score += 200
    if CURRENT_SHORT_NAME in title or FORMER_SHORT_NAME in title:
        score += 20
    if CURRENT_COMPANY in title or FORMER_COMPANY in title:
        score += 20
    return score


def select_annual(rows: list[dict[str, str]], year: int) -> dict[str, str]:
    ranked = sorted(
        ((annual_score(row["title"], year, index), row) for index, row in enumerate(rows)),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if not ranked or ranked[0][0] < 0:
        raise RuntimeError(f"Unable to locate full {year} annual report")
    selected = ranked[0][1]
    print("SELECT_ANNUAL", year, selected, flush=True)
    return selected


def select_half_year(rows: list[dict[str, str]], year: int) -> dict[str, str]:
    valid: list[tuple[int, dict[str, str]]] = []
    for index, row in enumerate(rows):
        normalized = compact(row["title"])
        if str(year) not in normalized:
            continue
        if "半年度报告" not in normalized and "中期报告" not in normalized:
            continue
        if any(marker in normalized for marker in ("摘要", "英文版", "英文", "取消", "问询", "回复")):
            continue
        score = 1000 - index
        if any(marker in normalized for marker in ("修订", "更正后", "更新后")):
            score += 200
        valid.append((score, row))
    if not valid:
        raise RuntimeError(f"Unable to locate full {year} half-year report")
    selected = sorted(valid, key=lambda pair: pair[0], reverse=True)[0][1]
    print("SELECT_HALF", year, selected, flush=True)
    return selected


def download_pdf(url: str) -> tuple[bytes, str]:
    candidates = [url]
    if url.startswith("http://"):
        candidates.append("https://" + url[len("http://") :])
    errors: list[str] = []
    for candidate in candidates:
        for referer in (
            "https://money.finance.sina.com.cn/",
            "https://www.sse.com.cn/",
            "https://static.sse.com.cn/",
        ):
            try:
                response = fetch(
                    candidate,
                    headers={**PDF_HEADERS, "Referer": referer},
                    attempts=5,
                    timeout=(30, 900),
                )
            except Exception as exc:
                errors.append(f"{candidate} | {referer} | {exc!r}")
                continue
            if response.content.startswith(b"%PDF-") and len(response.content) > 30_000:
                return response.content, response.url
            errors.append(
                f"{candidate} | {referer} | invalid PDF {len(response.content)} bytes"
            )
    raise RuntimeError("PDF download failed: " + " || ".join(errors[-10:]))


def extract_sample_text(reader: PdfReader, max_pages: int = 80) -> str:
    pieces: list[str] = []
    page_count = len(reader.pages)
    indexes = list(range(min(max_pages, page_count)))
    for index in sorted(set(indexes + [page_count // 2, max(0, page_count - 2), page_count - 1])):
        try:
            pieces.append(reader.pages[index].extract_text() or "")
        except Exception as exc:
            print("TEXT_WARNING", index + 1, repr(exc), flush=True)
    return "\n".join(pieces)


def validate_pdf(path: Path, *, year: int, report_type: str, min_pages: int, render_prefix: str) -> dict[str, int | str]:
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise RuntimeError(f"PDF signature missing: {path.name}")

    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted and reader.decrypt("") == 0:
        raise RuntimeError(f"Encrypted PDF cannot be opened: {path.name}")
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"Unexpectedly short PDF: {path.name}, {pages} pages")

    text = extract_sample_text(reader)
    normalized = compact(text)
    identity_markers = (
        CURRENT_SHORT_NAME,
        FORMER_SHORT_NAME,
        CURRENT_COMPANY,
        FORMER_COMPANY,
        STOCK_CODE,
        "zzmj",
    )
    if not any(compact(marker) in normalized for marker in identity_markers):
        raise RuntimeError(f"Company identity validation failed: {path.name}")
    if str(year) not in normalized:
        raise RuntimeError(f"Report year validation failed: {path.name}")
    if report_type == "年度报告" and "年度报告" not in normalized:
        raise RuntimeError(f"Annual-report marker missing: {path.name}")
    if report_type == "半年度报告" and not any(
        marker in normalized for marker in ("半年度报告", "中期报告")
    ):
        raise RuntimeError(f"Half-year-report marker missing: {path.name}")

    check = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-1500:]}")
    if check.returncode == 3:
        print("QPDF_WARNING", path.name, check.stderr[-1500:], flush=True)

    for label, page_number in (
        ("first", 1),
        ("middle", max(1, pages // 2)),
        ("last", pages),
    ):
        prefix = RENDERS / f"{render_prefix}_{label}"
        render = subprocess.run(
            [
                "pdftoppm",
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-singlefile",
                "-png",
                "-r",
                "90",
                str(path),
                str(prefix),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        image = prefix.with_suffix(".png")
        if render.returncode != 0 or not image.exists() or image.stat().st_size < 5_000:
            raise RuntimeError(
                f"Render verification failed for {path.name} page {page_number}: "
                f"{render.stderr[-800:]}"
            )

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def disclosure_date_from_url(url: str) -> str:
    match = re.search(r"/(20\d{2}-\d{2}-\d{2})/", url)
    if match:
        return match.group(1)
    match = re.search(r"/(20\d{2})(\d{2})(\d{2})/", url)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return ""


def main() -> None:
    annual_rows = parse_sina_listing("ndbg")
    half_rows = parse_sina_listing("zqbg")

    targets: list[dict[str, object]] = []
    for year in range(2020, 2026):
        row = select_annual(annual_rows, year)
        targets.append(
            {
                "year": year,
                "report_type": "年度报告",
                "title": row["title"],
                "detail_url": row["detail_url"],
                "min_pages": 120,
            }
        )

    half_row = select_half_year(half_rows, 2026)
    targets.append(
        {
            "year": 2026,
            "report_type": "半年度报告",
            "title": half_row["title"],
            "detail_url": half_row["detail_url"],
            "min_pages": 80,
        }
    )

    records: list[dict[str, object]] = []
    seen_hashes: set[str] = set()

    for index, target in enumerate(targets, 1):
        year = int(target["year"])
        report_type = str(target["report_type"])
        source_pdf = extract_sina_pdf(str(target["detail_url"]))
        pdf_bytes, final_source_url = download_pdf(source_pdf)

        if report_type == "年度报告":
            name_at_time = FORMER_SHORT_NAME if year <= 2024 else CURRENT_SHORT_NAME
            destination = ANNUAL_DIR / f"{year}_{name_at_time}_{year}年年度报告.pdf"
        else:
            destination = HALF_DIR / f"{year}_{CURRENT_SHORT_NAME}_{year}年半年度报告.pdf"
        destination.write_bytes(pdf_bytes)

        metadata = validate_pdf(
            destination,
            year=year,
            report_type=report_type,
            min_pages=int(target["min_pages"]),
            render_prefix=f"{index:02d}_{year}",
        )
        digest = str(metadata["sha256"])
        if digest in seen_hashes:
            raise RuntimeError(f"Duplicate PDF detected: {destination.name}")
        seen_hashes.add(digest)

        record = {
            "file": str(destination.relative_to(OUT)),
            "year": year,
            "category": "Annual Report" if report_type == "年度报告" else "Latest Half-Year Report",
            "report_type": report_type,
            "original_title": target["title"],
            "detail_url": target["detail_url"],
            "source_url": final_source_url,
            "disclosure_date": disclosure_date_from_url(final_source_url),
            **metadata,
        }
        records.append(record)
        print("VERIFIED", json.dumps(record, ensure_ascii=False), flush=True)

    if len(records) != 7:
        raise RuntimeError(f"Expected 7 reports, got {len(records)}")
    annual_years = [
        int(record["year"])
        for record in records
        if record["category"] == "Annual Report"
    ]
    if annual_years != list(range(2020, 2026)):
        raise RuntimeError(f"Annual coverage mismatch: {annual_years}")
    half_records = [
        record for record in records if record["category"] == "Latest Half-Year Report"
    ]
    if len(half_records) != 1 or int(half_records[0]["year"]) != 2026:
        raise RuntimeError(f"Half-year coverage mismatch: {half_records}")

    total_pages = sum(int(record["pages"]) for record in records)
    total_bytes = sum(int(record["bytes"]) for record in records)
    manifest = {
        "company": CURRENT_COMPANY,
        "former_company_name": FORMER_COMPANY,
        "short_name": CURRENT_SHORT_NAME,
        "former_short_name": FORMER_SHORT_NAME,
        "ticker": "601717.SH",
        "h_share_ticker": "00564.HK",
        "stock_code": STOCK_CODE,
        "prepared_date": "2026-09-03",
        "name_change_note": (
            "2020—2024年度报告披露时证券简称为郑煤机；"
            "2025年度报告和2026年半年度报告使用中创智领名称。"
        ),
        "documents": records,
        "total_documents": len(records),
        "total_pages": total_pages,
        "total_bytes": total_bytes,
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT / "SHA256SUMS.txt").write_text(
        "".join(f"{record['sha256']}  {record['file']}\n" for record in records),
        encoding="utf-8",
    )

    lines = [
        f"{CURRENT_COMPANY}（601717.SH / 00564.HK）定期报告资料包",
        "",
        "内容范围：2020—2025年完整年度报告，以及截至2026年9月3日最新披露的2026年半年度报告。",
        "2020—2024年度报告披露时公司名称/证券简称为“郑州煤矿机械集团股份有限公司/郑煤机”；",
        "2025年公司更名为“中创智领（郑州）工业技术集团股份有限公司/中创智领”，证券代码601717保持不变。",
        "所有文件均为完整报告正文，已排除年度报告摘要、半年度报告摘要及英文版。",
        "",
        "文件清单：",
    ]
    for index, record in enumerate(records, 1):
        lines.extend(
            [
                f"{index}. {record['file']}",
                f"   原公告标题：{record['original_title']}",
                f"   报告类型：{record['report_type']}｜年份：{record['year']}｜页数：{record['pages']}",
                f"   披露日期：{record['disclosure_date'] or '以公告页面为准'}",
                f"   来源：{record['source_url']}",
                f"   SHA-256：{record['sha256']}",
                "",
            ]
        )
    lines.extend(
        [
            "核验项目：PDF文件头、结构与实际页数；公司名称/证券代码；报告年份和类型；",
            "每份PDF首页、中间页、末页渲染；逐文件SHA-256；重复文件检查；ZIP CRC。",
            f"合计：{len(records)}份PDF，{total_pages}页，未压缩PDF总大小{total_bytes / 1024 / 1024:.2f} MiB。",
            "资料仅供研究使用，版权归中创智领、郑煤机及原披露平台所有。",
        ]
    )
    (OUT / "README_来源与校验.txt").write_text("\n".join(lines), encoding="utf-8")

    archive = Path(PACKAGE_NAME + ".zip")
    with zipfile.ZipFile(
        archive,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        allowZip64=True,
    ) as bundle:
        for path in sorted(OUT.rglob("*")):
            if path.is_file():
                bundle.write(path, arcname=str(path.relative_to(OUT)))

    with zipfile.ZipFile(archive) as bundle:
        bad = bundle.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")
        pdf_members = [name for name in bundle.namelist() if name.lower().endswith(".pdf")]
        if len(pdf_members) != 7:
            raise RuntimeError(f"ZIP contains {len(pdf_members)} PDFs, expected 7")

    print(
        "FINAL_ZIP",
        archive.name,
        archive.stat().st_size,
        sha256_file(archive),
        total_pages,
        total_bytes,
        flush=True,
    )


if __name__ == "__main__":
    main()
