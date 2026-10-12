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

COMPANY = "华金资本"
FULL_COMPANY = "珠海华金资本股份有限公司"
CODE = "000532"
CHECKED_AS_OF = "2026-10-12"
PACKAGE_NAME = "华金资本_000532_2020-2025年报及最新季报"
PACKAGE_DIR = Path(PACKAGE_NAME)
ANNUAL_DIR = PACKAGE_DIR / "01_年度报告"
QUARTER_DIR = PACKAGE_DIR / "02_最新季报"
VERIFY_DIR = Path("_verify_huajin_000532")

for directory in (ANNUAL_DIR, QUARTER_DIR, VERIFY_DIR):
    directory.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
}


def get(url: str, referer: str | None = None, require_pdf: bool = False) -> requests.Response:
    last: requests.Response | Exception | None = None
    for attempt in range(1, 5):
        headers = dict(HEADERS)
        if referer:
            headers["Referer"] = referer
        try:
            response = session.get(url, headers=headers, timeout=180, allow_redirects=True)
            print(
                "HTTP",
                attempt,
                response.status_code,
                response.headers.get("content-type"),
                len(response.content),
                response.url,
                flush=True,
            )
            last = response
            if response.status_code == 200 and (
                not require_pdf or response.content.startswith(b"%PDF")
            ):
                return response
        except Exception as exc:  # noqa: BLE001
            print("REQUEST_ERROR", attempt, url, repr(exc), flush=True)
            last = exc
        time.sleep(attempt * 2)
    if isinstance(last, Exception):
        raise last
    if last is None:
        raise RuntimeError(f"No response received for {url}")
    return last


def collect_entries(page_type: str) -> list[dict[str, str]]:
    list_url = (
        "https://vip.stock.finance.sina.com.cn/corp/go.php/"
        f"vCB_Bulletin/stockid/{CODE}/page_type/{page_type}.phtml"
    )
    response = get(list_url)
    response.encoding = response.apparent_encoding or "gb18030"
    soup = BeautifulSoup(response.text, "html.parser")

    entries: list[dict[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        href = anchor.get("href", "").strip()
        if not title or "vCB_AllBulletinDetail.php" not in href:
            continue
        parent_text = (
            re.sub(r"\s+", " ", anchor.parent.get_text(" ", strip=True))
            if anchor.parent
            else title
        )
        date_match = re.search(r"(20\d{2}-\d{2}-\d{2})", parent_text)
        entries.append(
            {
                "title": title,
                "detail_url": urljoin(response.url, href),
                "announcement_date": date_match.group(1) if date_match else "",
                "list_url": list_url,
            }
        )

    deduplicated: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in entries:
        if entry["detail_url"] in seen:
            continue
        seen.add(entry["detail_url"])
        deduplicated.append(entry)

    print(
        "ENTRIES",
        page_type,
        len(deduplicated),
        json.dumps(deduplicated[:20], ensure_ascii=False),
        flush=True,
    )
    return deduplicated


def resolve_pdf_url(entry: dict[str, object]) -> str:
    detail_url = str(entry["detail_url"])
    response = get(detail_url, referer=str(entry["list_url"]))
    response.encoding = response.apparent_encoding or "gb18030"
    soup = BeautifulSoup(response.text, "html.parser")

    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        text = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True))
        full_url = urljoin(response.url, anchor["href"].strip())
        if (
            ("下载公告" in text or full_url.lower().endswith(".pdf"))
            and "file.finance.sina.com.cn" in full_url
        ):
            links.append(full_url)

    if not links:
        pattern = re.compile(
            r"https?://file\.finance\.sina\.com\.cn/[^\"'<>\s]+?\.PDF",
            re.IGNORECASE,
        )
        links.extend(match.group(0) for match in pattern.finditer(response.text))

    if not links:
        raise RuntimeError(f"No PDF link resolved from {detail_url}")
    return links[0]


annual_entries = collect_entries("ndbg")
quarter_entries = collect_entries("yjdbg") + collect_entries("sjdbg")

selected: list[dict[str, object]] = []
for year in range(2020, 2026):
    candidates = [
        entry
        for entry in annual_entries
        if f"{year}年年度报告" in entry["title"]
        and "摘要" not in entry["title"]
        and "英文" not in entry["title"]
    ]
    if not candidates:
        raise RuntimeError(f"No annual report found for {year}")
    candidates.sort(
        key=lambda entry: (
            int(any(token in entry["title"] for token in ("更新后", "修订版", "更正后"))),
            entry["announcement_date"],
            len(entry["title"]),
        ),
        reverse=True,
    )
    chosen: dict[str, object] = dict(candidates[0])
    chosen.update(
        {
            "period": f"{year}年度",
            "type": "年度报告",
            "year": year,
            "quarter": 0,
            "filename": f"华金资本_{year}年年度报告.pdf",
            "destination_dir": ANNUAL_DIR,
        }
    )
    selected.append(chosen)

quarter_candidates: list[tuple[int, int, dict[str, str]]] = []
for entry in quarter_entries:
    title = entry["title"]
    if "摘要" in title or "英文" in title:
        continue
    year_match = re.search(r"(20\d{2})年", title)
    if not year_match:
        continue
    year = int(year_match.group(1))
    if "第三季度报告" in title or "三季度报告" in title:
        quarter = 3
    elif "第一季度报告" in title or "一季度报告" in title:
        quarter = 1
    else:
        continue
    quarter_candidates.append((year, quarter, entry))

if not quarter_candidates:
    raise RuntimeError("No quarterly report found")
quarter_candidates.sort(
    key=lambda item: (item[0], item[1], item[2]["announcement_date"]),
    reverse=True,
)
quarter_year, quarter_number, quarter_entry = quarter_candidates[0]
quarter_name = "第一季度" if quarter_number == 1 else "第三季度"
quarter_selected: dict[str, object] = dict(quarter_entry)
quarter_selected.update(
    {
        "period": f"{quarter_year}年{quarter_name}",
        "type": "季度报告",
        "year": quarter_year,
        "quarter": quarter_number,
        "filename": f"华金资本_{quarter_year}年{quarter_name}报告.pdf",
        "destination_dir": QUARTER_DIR,
    }
)
selected.append(quarter_selected)

print(
    "SELECTED",
    json.dumps(
        [
            {key: value for key, value in entry.items() if key != "destination_dir"}
            for entry in selected
        ],
        ensure_ascii=False,
        indent=2,
    ),
    flush=True,
)

records: list[dict[str, object]] = []
seen_hashes: set[str] = set()

for index, entry in enumerate(selected, 1):
    pdf_url = resolve_pdf_url(entry)
    response = get(pdf_url, referer=str(entry["detail_url"]), require_pdf=True)
    if not response.content.startswith(b"%PDF") or len(response.content) < 50_000:
        raise RuntimeError(
            f"Invalid PDF response for {entry['title']}: {len(response.content)} bytes"
        )

    destination_dir = entry["destination_dir"]
    if not isinstance(destination_dir, Path):
        raise TypeError("destination_dir must be a Path")
    path = destination_dir / str(entry["filename"])
    path.write_bytes(response.content)

    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    if sha256 in seen_hashes:
        raise RuntimeError(f"Duplicate PDF detected: {path}")
    seen_hashes.add(sha256)

    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)], text=True, capture_output=True, check=False
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(
            f"qpdf check failed for {path}: {qpdf.stdout}\n{qpdf.stderr}"
        )

    reader = PdfReader(str(path))
    page_count = len(reader.pages)
    if page_count < 5:
        raise RuntimeError(f"Unexpectedly short report: {path}, pages={page_count}")

    text_path = VERIFY_DIR / f"{index:02d}.txt"
    subprocess.run(
        [
            "pdftotext",
            "-f",
            "1",
            "-l",
            str(min(10, page_count)),
            str(path),
            str(text_path),
        ],
        check=True,
    )
    text = text_path.read_text(encoding="utf-8", errors="ignore")
    compact_text = re.sub(r"\s+", "", text)
    if (
        COMPANY not in compact_text
        and FULL_COMPANY not in compact_text
        and CODE not in compact_text
    ):
        raise RuntimeError(f"Company identity check failed for {path}")
    if str(entry["year"]) not in compact_text:
        raise RuntimeError(f"Report year check failed for {path}")

    render_pages = sorted({1, max(1, (page_count + 1) // 2), page_count})
    rendered_files: list[str] = []
    for page_number in render_pages:
        base = VERIFY_DIR / f"{index:02d}_p{page_number}"
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
                "100",
                str(path),
                str(base),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if render.returncode != 0:
            raise RuntimeError(
                f"PDF render failed for {path}, page {page_number}: {render.stderr}"
            )
        image = Path(str(base) + ".png")
        if not image.exists() or image.stat().st_size < 10_000:
            raise RuntimeError(f"Invalid render output: {image}")
        rendered_files.append(str(image))

    record: dict[str, object] = {
        "period": entry["period"],
        "type": entry["type"],
        "announcement_date": entry["announcement_date"],
        "source_title": entry["title"],
        "relative_path": str(path.relative_to(PACKAGE_DIR)),
        "pages": page_count,
        "bytes": path.stat().st_size,
        "sha256": sha256,
        "list_url": entry["list_url"],
        "detail_url": entry["detail_url"],
        "source_url": pdf_url,
        "download_final_url": response.url,
        "qpdf_return_code": qpdf.returncode,
        "rendered_pages": render_pages,
        "render_files": rendered_files,
        "company_identity_verified": True,
    }
    records.append(record)
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

latest = records[-1]
readme = f"""华金资本（000532）2020—2025年年度报告及最新季报

核对日期：{CHECKED_AS_OF}

收录范围
- 2020—2025年年度报告全文，共6份。
- 最新已披露季报：{latest['period']}报告，公告日期：{latest['announcement_date'] or '见来源清单'}。
- 半年度报告属于中期报告，不按“季报”口径收录。

来源及筛选
- 文件来自新浪财经公司公告PDF镜像，内容为上市公司披露的原始PDF。
- 已排除年度报告摘要、英文版及其他非全文文件；若同一年度存在更新后版本，优先采用更新后版本。

校验
- 每份PDF均检查文件头、qpdf结构、实际页数、公司名称或股票代码、报告年份。
- 每份PDF均渲染首页、中间页和末页验证可正常显示。
- 文件来源和页数见“文件清单.csv”与“manifest.json”；逐文件SHA-256见“SHA256SUMS.txt”。
"""
(PACKAGE_DIR / "README.txt").write_text(readme, encoding="utf-8")

csv_fields = [
    "period",
    "type",
    "announcement_date",
    "source_title",
    "relative_path",
    "pages",
    "bytes",
    "sha256",
    "detail_url",
    "source_url",
    "download_final_url",
    "qpdf_return_code",
    "company_identity_verified",
]
with (PACKAGE_DIR / "文件清单.csv").open(
    "w", encoding="utf-8-sig", newline=""
) as csv_file:
    writer = csv.DictWriter(csv_file, fieldnames=csv_fields)
    writer.writeheader()
    for record in records:
        writer.writerow({key: record.get(key, "") for key in csv_fields})

with (PACKAGE_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as hash_file:
    for record in records:
        hash_file.write(f"{record['sha256']}  {record['relative_path']}\n")

manifest = {
    "package_name": PACKAGE_NAME,
    "company": FULL_COMPANY,
    "short_name": COMPANY,
    "stock_code": CODE,
    "checked_as_of": CHECKED_AS_OF,
    "annual_report_years": list(range(2020, 2026)),
    "latest_quarterly_report": str(latest["period"]) + "报告",
    "document_count": len(records),
    "records": records,
}
(PACKAGE_DIR / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)

zip_path = Path(PACKAGE_NAME + ".zip")
with zipfile.ZipFile(
    zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
) as archive:
    for item in sorted(PACKAGE_DIR.rglob("*")):
        if item.is_file():
            archive.write(item, arcname=str(item))

with zipfile.ZipFile(zip_path, "r") as archive:
    bad_file = archive.testzip()
    if bad_file:
        raise RuntimeError(f"ZIP integrity failure at {bad_file}")

zip_sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
print(
    "FINAL_ZIP",
    zip_path,
    "bytes",
    zip_path.stat().st_size,
    "sha256",
    zip_sha256,
    flush=True,
)
