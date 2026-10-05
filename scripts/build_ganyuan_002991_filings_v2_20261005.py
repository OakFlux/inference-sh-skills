from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any, Iterable

import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-10-05"
COMPANY = "甘源食品股份有限公司"
SHORT_NAME = "甘源食品"
STOCK_CODE = "002991"
PACKAGE = "甘源食品_002991_全部年报_招股说明书_最新季报"
ROOT = Path(PACKAGE)
ANNUAL_DIR = ROOT / "01_年度报告"
PROSPECTUS_DIR = ROOT / "02_招股说明书"
QUARTER_DIR = ROOT / "03_最新季度报告"
VERIFY_DIR = ROOT / "04_说明与校验"
WORK_DIR = Path("_ganyuan_002991_filings_v2_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (ANNUAL_DIR, PROSPECTUS_DIR, QUARTER_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
    "Accept": "application/pdf,application/octet-stream;q=0.9,text/html;q=0.7,*/*;q=0.5",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

PROSPECTUSES: list[dict[str, Any]] = [
    {
        "date": "2019-10-25",
        "title": "甘源食品股份有限公司首次公开发行股票招股说明书（申报稿2019年10月14日报送）",
        "version": "申报稿",
        "filename": "20191025_甘源食品_首次公开发行股票招股说明书_申报稿2019年10月14日报送.pdf",
        "urls": [
            "https://www.csrc.gov.cn/pub/zjhpublic/G00306202/201910/P020191025616629063683.pdf",
            "http://www.csrc.gov.cn/pub/zjhpublic/G00306202/201910/P020191025616629063683.pdf",
        ],
        "detail_url": "https://ipo.qianzhan.com/zjh/Detail-f4462f0a3d0658b50cc6c7c5e14cc654.html",
        "source": "中国证监会预先披露文件（前瞻IPO页面保留原始附件路径）",
        "required": False,
    },
    {
        "date": "2020-07-21",
        "title": "甘源食品股份有限公司首次公开发行股票招股说明书",
        "version": "正式发行版",
        "filename": "20200721_甘源食品_首次公开发行股票招股说明书_正式发行版.pdf",
        "urls": [
            "https://static.cninfo.com.cn/finalpage/2020-07-21/1208051937.PDF",
            "http://static.cninfo.com.cn/finalpage/2020-07-21/1208051937.PDF",
        ],
        "detail_url": "https://www.cninfo.com.cn/new/disclosure/detail?stockCode=002991&announcementId=1208051937&orgId=9900039782&announcementTime=2020-07-21",
        "source": "巨潮资讯网正式发行版原始PDF",
        "required": True,
        "announcement_id": "1208051937",
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request(url: str, *, stream: bool = False, referer: str | None = None,
            timeout: tuple[int, int] = (25, 420), allow_redirects: bool = True) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        headers = dict(HEADERS)
        if referer:
            headers["Referer"] = referer
        try:
            response = SESSION.get(
                url,
                headers=headers,
                timeout=timeout,
                stream=stream,
                allow_redirects=allow_redirects,
            )
            print(
                "HTTP", attempt, response.status_code,
                response.headers.get("content-type"),
                response.headers.get("content-length"),
                response.url,
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(attempt * 2, 10))
    raise RuntimeError(f"request failed for {url}: {errors[-6:]}")


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", "", value).strip("._")
    return value[:180] or "document"


def notice_date(item: dict[str, Any]) -> str:
    return str(item.get("notice_date") or item.get("display_time") or item.get("noticeDate") or "")[:10]


def item_title(item: dict[str, Any]) -> str:
    return str(item.get("title") or item.get("notice_title") or "")


def revision_priority(title: str) -> int:
    t = normalize(title)
    if any(word in t for word in ("更新后", "更正后", "修订版", "更新版")):
        return 4
    if any(word in t for word in ("更新", "更正", "修订")):
        return 3
    return 1


def fetch_all_notices() -> list[dict[str, Any]]:
    notices: list[dict[str, Any]] = []
    for page in range(1, 41):
        url = (
            "https://np-anotice-stock.eastmoney.com/api/security/ann"
            f"?sr=-1&page_size=100&page_index={page}&ann_type=A&client_source=web"
            f"&stock_list={STOCK_CODE}&f_node=0&s_node=0"
        )
        response = request(url, timeout=(20, 120))
        try:
            payload = response.json()
        finally:
            response.close()
        data = payload.get("data") or {}
        batch = data.get("list") or []
        total = int(data.get("total_hits") or data.get("total") or 0)
        print("NOTICE_PAGE", page, "ITEMS", len(batch), "TOTAL", total, flush=True)
        notices.extend(batch)
        if not batch or len(notices) >= total or len(batch) < 100:
            break
    if not notices:
        raise RuntimeError("no company announcements returned")
    return notices


def valid_annual(title: str) -> bool:
    t = normalize(title)
    excluded = (
        "摘要", "英文版", "英文", "取消", "审计报告", "财务报表",
        "社会责任报告", "内部控制", "独立董事", "董事会", "监事会",
        "问询函", "回复", "更正公告", "关于", "说明", "提示性公告",
    )
    return not any(word in t for word in excluded)


def valid_quarter(title: str) -> bool:
    t = normalize(title)
    return not any(word in t for word in (
        "英文版", "英文", "取消", "更正公告", "关于", "说明", "提示性公告",
        "审阅报告", "财务报表",
    ))


def select_annual_and_quarter(notices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for year in range(2020, 2026):
        marker = f"{year}年年度报告"
        candidates = [
            item for item in notices
            if marker in normalize(item_title(item)) and valid_annual(item_title(item))
        ]
        if not candidates:
            raise RuntimeError(f"annual report not found for {year}")
        candidates.sort(
            key=lambda row: (
                revision_priority(item_title(row)), notice_date(row),
                str(row.get("art_code") or ""),
            ),
            reverse=True,
        )
        chosen = dict(candidates[0])
        chosen.update({"category": "annual_report", "report_year": year, "quarter": None})
        selected.append(chosen)

    q_candidates: list[tuple[int, int, int, str, dict[str, Any]]] = []
    pattern = re.compile(r"(20\d{2})年(第一季度|第三季度)报告")
    for item in notices:
        title = item_title(item)
        if not valid_quarter(title):
            continue
        match = pattern.search(normalize(title))
        if not match:
            continue
        year = int(match.group(1))
        quarter = 1 if match.group(2) == "第一季度" else 3
        q_candidates.append((year, quarter, revision_priority(title), notice_date(item), item))
    if not q_candidates:
        raise RuntimeError("no first- or third-quarter report found")
    q_candidates.sort(key=lambda row: (row[0], row[1], row[2], row[3]), reverse=True)
    year, quarter, _, _, item = q_candidates[0]
    chosen = dict(item)
    chosen.update({"category": "latest_quarterly_report", "report_year": year, "quarter": quarter})
    selected.append(chosen)

    print(
        "SELECTED_NOTICES",
        json.dumps([
            {
                "date": notice_date(item),
                "art_code": item.get("art_code"),
                "title": item_title(item),
                "category": item["category"],
                "year": item["report_year"],
                "quarter": item["quarter"],
            }
            for item in selected
        ], ensure_ascii=False, indent=2),
        flush=True,
    )
    return selected


def download_to(urls: Iterable[str], destination: Path, *, referer: str | None = None,
                minimum_bytes: int = 20_000) -> str:
    errors: list[str] = []
    for url in urls:
        for redirects in (True, False):
            temp = destination.with_suffix(destination.suffix + ".part")
            temp.unlink(missing_ok=True)
            try:
                response = request(
                    url, stream=True, referer=referer,
                    allow_redirects=redirects,
                )
                try:
                    with temp.open("wb") as fh:
                        for chunk in response.iter_content(1024 * 1024):
                            if chunk:
                                fh.write(chunk)
                    final_url = str(response.url)
                    content_type = str(response.headers.get("content-type") or "")
                finally:
                    response.close()
                size = temp.stat().st_size
                head = temp.read_bytes()[:8]
                print("DOWNLOAD_CANDIDATE", url, redirects, size, content_type, head, final_url, flush=True)
                if size < minimum_bytes or not head.startswith(b"%PDF-"):
                    raise RuntimeError(
                        f"not a valid PDF payload: size={size}, type={content_type}, head={head!r}"
                    )
                temp.replace(destination)
                return final_url
            except Exception as exc:  # noqa: BLE001
                temp.unlink(missing_ok=True)
                errors.append(f"{url} redirects={redirects}: {exc!r}")
    raise RuntimeError(f"all download candidates failed for {destination.name}: {errors}")


def download_notice_pdf(art_code: str, destination: Path) -> str:
    return download_to(
        [
            f"https://pdf.dfcfw.com/pdf/H2_{art_code}_1.pdf",
            f"https://pdf.dfcfw.com/pdf/H3_{art_code}_1.pdf",
        ],
        destination,
        referer="https://data.eastmoney.com/notices/",
    )


def render_page(path: Path, page_number: int, suffix: str) -> str:
    prefix = RENDER_DIR / f"{path.stem}_{suffix}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
            "-r", "105", "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    png = Path(str(prefix) + ".png")
    if not (
        process.returncode == 0 and png.exists() and png.stat().st_size > 3000
        and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    ):
        raise RuntimeError(
            f"render failed for {path.name} page {page_number}: "
            f"return={process.returncode}, stderr={process.stderr[-1500:]}"
        )
    return str(png.relative_to(WORK_DIR))


def validate_pdf(path: Path, *, category: str, year: int | None = None,
                 quarter: int | None = None, minimum_pages: int = 5) -> dict[str, Any]:
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
    if pages < minimum_pages:
        raise RuntimeError(f"unexpectedly short PDF: {path.name}, pages={pages}")

    indices = sorted({0, min(1, pages - 1), min(2, pages - 1), max(0, pages // 2), pages - 1})
    text_parts: list[str] = []
    for index in indices:
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_WARNING", path.name, index + 1, repr(exc), flush=True)
    text = normalize("\n".join(text_parts))
    identity_ok = COMPANY in text or SHORT_NAME in text or STOCK_CODE in text
    if text and not identity_ok:
        raise RuntimeError(f"company identity not found in sampled text: {path.name}")

    marker_ok = True
    if category == "annual_report" and year:
        marker_ok = f"{year}年年度报告" in text if text else False
    elif category == "prospectus":
        marker_ok = "招股说明书" in text if text else False
    elif category == "latest_quarterly_report" and quarter:
        quarter_cn = "第一季度" if quarter == 1 else "第三季度"
        marker_ok = quarter_cn in text and "报告" in text if text else False
    if text and not marker_ok:
        print("MARKER_WARNING", path.name, category, year, quarter, flush=True)

    render_pages = sorted({1, max(1, (pages + 1) // 2), pages})
    renders = [
        render_page(path, pageno, f"p{pageno}")
        for pageno in render_pages
    ]
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "sample_text_extractable": bool(text),
        "identity_verified_when_text_extractable": identity_ok,
        "document_marker_verified_when_text_extractable": marker_ok,
        "rendered_pages": render_pages,
        "render_files": renders,
    }


notices = fetch_all_notices()
selected = select_annual_and_quarter(notices)
records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()
unavailable_optional: list[dict[str, Any]] = []

for item in selected:
    art_code = str(item.get("art_code") or "").strip()
    title = item_title(item)
    date = notice_date(item)
    if not art_code:
        raise RuntimeError(f"missing art_code: {title}")

    if item["category"] == "annual_report":
        destination = ANNUAL_DIR / f"{date.replace('-', '')}_{STOCK_CODE}_{item['report_year']}年年度报告.pdf"
        category_cn = "年度报告"
        version = "年度完整报告"
    else:
        quarter_cn = "第一季度" if item["quarter"] == 1 else "第三季度"
        destination = QUARTER_DIR / f"{date.replace('-', '')}_{STOCK_CODE}_{item['report_year']}年{quarter_cn}报告.pdf"
        category_cn = "最新季度报告"
        version = "季度完整报告"

    source_url = download_notice_pdf(art_code, destination)
    validation = validate_pdf(
        destination,
        category=item["category"],
        year=item["report_year"],
        quarter=item["quarter"],
        minimum_pages=5,
    )
    if validation["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate notice PDF: {destination.name}")
    seen_hashes.add(validation["sha256"])
    record = {
        "category": item["category"],
        "category_cn": category_cn,
        "version": version,
        "report_year": item["report_year"],
        "quarter": item["quarter"],
        "notice_date": date,
        "title": title,
        "art_code": art_code,
        "relative_path": str(destination.relative_to(ROOT)),
        "source": "东方财富公告镜像（原始披露PDF）",
        "source_url": source_url,
        "source_detail_url": f"https://data.eastmoney.com/notices/detail/{STOCK_CODE}/{art_code}.html",
        **validation,
    }
    records.append(record)
    print("VALIDATED_NOTICE", json.dumps(record, ensure_ascii=False), flush=True)

for item in PROSPECTUSES:
    destination = PROSPECTUS_DIR / item["filename"]
    try:
        source_url = download_to(
            item["urls"],
            destination,
            referer=item["detail_url"],
            minimum_bytes=100_000,
        )
        validation = validate_pdf(
            destination,
            category="prospectus",
            minimum_pages=50,
        )
    except Exception as exc:  # noqa: BLE001
        destination.unlink(missing_ok=True)
        if item["required"]:
            raise
        unavailable_optional.append({
            "title": item["title"],
            "version": item["version"],
            "detail_url": item["detail_url"],
            "reason": repr(exc),
        })
        print("OPTIONAL_PROSPECTUS_UNAVAILABLE", json.dumps(unavailable_optional[-1], ensure_ascii=False), flush=True)
        continue

    if validation["sha256"] in seen_hashes:
        destination.unlink(missing_ok=True)
        print("SKIP_DUPLICATE_PROSPECTUS", item["title"], validation["sha256"], flush=True)
        continue
    seen_hashes.add(validation["sha256"])
    record = {
        "category": "prospectus",
        "category_cn": "招股说明书",
        "version": item["version"],
        "report_year": None,
        "quarter": None,
        "notice_date": item["date"],
        "title": item["title"],
        "art_code": item.get("announcement_id", ""),
        "relative_path": str(destination.relative_to(ROOT)),
        "source": item["source"],
        "source_url": source_url,
        "source_detail_url": item["detail_url"],
        **validation,
    }
    records.append(record)
    print("VALIDATED_PROSPECTUS", json.dumps(record, ensure_ascii=False), flush=True)

annual_years = sorted(r["report_year"] for r in records if r["category"] == "annual_report")
if annual_years != list(range(2020, 2026)):
    raise RuntimeError(f"annual report coverage mismatch: {annual_years}")
formal = [r for r in records if r["category"] == "prospectus" and r["version"] == "正式发行版"]
if len(formal) != 1:
    raise RuntimeError(f"formal prospectus count mismatch: {len(formal)}")
quarter_records = [r for r in records if r["category"] == "latest_quarterly_report"]
if len(quarter_records) != 1:
    raise RuntimeError(f"latest quarterly report count mismatch: {len(quarter_records)}")
latest_quarter = quarter_records[0]

# Order for readability: annual reports, prospectuses, then latest quarter.
records.sort(key=lambda r: (
    {"annual_report": 1, "prospectus": 2, "latest_quarterly_report": 3}[r["category"]],
    r["notice_date"],
    r["title"],
))

manifest = {
    "package_name": PACKAGE,
    "company": COMPANY,
    "short_name": SHORT_NAME,
    "stock_code": STOCK_CODE,
    "checked_as_of": CHECKED_AS_OF,
    "scope": {
        "annual_reports": "上市以来2020—2025年度完整年度报告；同一年度若存在更新、修订或更正版本，采用后续披露的最新完整版本。",
        "prospectus": "收录巨潮资讯网正式发行版；同时尝试收录中国证监会2019年10月预先披露申报稿。",
        "latest_quarterly_report": (
            f"截至{CHECKED_AS_OF}公开披露的最新第一季度或第三季度报告："
            f"{latest_quarter['report_year']}年第{latest_quarter['quarter']}季度报告。"
        ),
        "exclusions": "排除年度报告摘要、英文版、招股说明书摘要、招股意向书、发行公告、半年度报告以及仅说明更正事项的公告。",
    },
    "document_count": len(records),
    "unavailable_optional_documents": unavailable_optional,
    "records": records,
}
(ROOT / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as fh:
    writer = csv.writer(fh)
    writer.writerow([
        "类别", "版本", "报告年度", "季度", "披露日期", "标题", "页数",
        "字节数", "SHA-256", "文件路径", "公告代码", "来源说明", "PDF来源", "详情页",
    ])
    for record in records:
        writer.writerow([
            record["category_cn"], record["version"], record["report_year"],
            record["quarter"], record["notice_date"], record["title"],
            record["pages"], record["bytes"], record["sha256"],
            record["relative_path"], record["art_code"], record["source"],
            record["source_url"], record["source_detail_url"],
        ])

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as fh:
    for record in records:
        fh.write(f"{record['sha256']}  {record['relative_path']}\n")

readme = [
    f"{SHORT_NAME}（{STOCK_CODE}）全部年报、招股说明书及最新季报",
    "",
    f"核对日期：{CHECKED_AS_OF}",
    f"公司全称：{COMPANY}",
    f"PDF数量：{len(records)}份",
    "",
    "收录范围：",
    "- 2020—2025年度报告全文，共6份；",
    "- 2020年7月21日正式发行版招股说明书；",
    "- 中国证监会2019年10月预先披露申报稿（如原始附件仍可正常取得）；",
    f"- 最新季报：{latest_quarter['report_year']}年第{latest_quarter['quarter']}季度报告；",
    "- 未混入年报摘要、英文版、招股说明书摘要、招股意向书或半年度报告。",
    "",
    "文件列表：",
]
for i, record in enumerate(records, 1):
    readme.append(
        f"{i}. {record['notice_date']} | {record['category_cn']} | {record['version']} | "
        f"{record['title']} | {record['pages']}页"
    )
if unavailable_optional:
    readme.extend(["", "未能取得的可选历史版本："])
    for item in unavailable_optional:
        readme.append(f"- {item['title']}：旧版证监会附件目前无法返回有效PDF，正式发行版已完整收录。")
readme.extend([
    "",
    "校验项目：",
    "- PDF文件头、qpdf结构及实际页数；",
    "- 公司名称或股票代码、报告期间和文档类型；",
    "- 每份PDF首页、中间页与末页实际渲染；",
    "- SHA-256重复文件检查；",
    "- ZIP CRC完整性测试。",
])
(VERIFY_DIR / "README.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")

zip_path = Path(PACKAGE + ".zip")
zip_path.unlink(missing_ok=True)
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, path.as_posix())
with zipfile.ZipFile(zip_path, "r") as archive:
    bad = archive.testzip()
    if bad:
        raise RuntimeError(f"ZIP CRC failure at {bad}")
    pdf_count = sum(1 for name in archive.namelist() if name.lower().endswith(".pdf"))
    if pdf_count != len(records):
        raise RuntimeError(f"ZIP PDF count mismatch: {pdf_count} != {len(records)}")

print("FINAL_ZIP", zip_path, "bytes", zip_path.stat().st_size, "sha256", sha256(zip_path), flush=True)
print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
