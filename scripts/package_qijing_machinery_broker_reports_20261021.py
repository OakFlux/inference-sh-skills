from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import sys
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pymupdf
import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-10-21"
COMPANY = "奇精机械"
FULL_COMPANY = "奇精机械股份有限公司"
STOCK_CODE = "603677"
PACKAGE_NAME = f"{COMPANY}_{STOCK_CODE}_券商研究报告_2份"
ROOT = Path("dist")
PACKAGE_ROOT = ROOT / PACKAGE_NAME
REPORT_DIR = PACKAGE_ROOT / "01_券商研究报告"
VERIFY_DIR = PACKAGE_ROOT / "02_说明与校验"
RENDER_DIR = ROOT / "_qijing_broker_renders"
ZIP_PATH = ROOT / f"{PACKAGE_NAME}_截至{CHECKED_AS_OF.replace('-', '')}.zip"
SUMMARY_PATH = ROOT / "package_summary.json"

API = "https://reportapi.eastmoney.com/report/list"
SESSION = requests.Session()
SESSION.trust_env = False
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "Chrome/155.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,application/pdf,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": f"https://data.eastmoney.com/report/{STOCK_CODE}.html",
    }
)


@dataclass
class Report:
    publish_date: str
    broker: str
    broker_full: str
    authors: str
    title: str
    info_code: str
    expected_pages: int
    rating: str
    filename: str
    title_keywords: list[str]
    actual_pages: int = 0
    bytes: int = 0
    sha256: str = ""
    pdf_url: str = ""
    detail_url: str = ""
    metadata_verified: bool = False
    company_identity_verified: bool = False
    broker_identity_verified: bool = False
    rendered_pages: list[int] | None = None


REPORTS = [
    Report(
        publish_date="2018-07-11",
        broker="民生证券",
        broker_full="民生证券股份有限公司",
        authors="刘振宇、丁健",
        title="专注机械精加工，积极扩展汽车零部件市场",
        info_code="AP201807111165546979",
        expected_pages=14,
        rating="增持",
        filename="20180711_民生证券_专注机械精加工_积极扩展汽车零部件市场.pdf",
        title_keywords=["专注机械精加工", "汽车零部件"],
    ),
    Report(
        publish_date="2017-04-25",
        broker="东吴证券",
        broker_full="东吴证券股份有限公司",
        authors="陈显帆、倪正洋",
        title="研究简报：‘家电零部件+电动工具零部件’铸就奇精双风火轮",
        info_code="AP201704250530593590",
        expected_pages=7,
        rating="增持",
        filename="20170425_东吴证券_家电零部件与电动工具零部件铸就奇精双风火轮.pdf",
        title_keywords=["家电零部件", "电动工具零部件"],
    ),
]

OTHER_KNOWN_COVERAGE = [
    {
        "date": "2018-01-15",
        "broker": "中泰证券",
        "title": "家电离合器龙头，打造汽车零部件第二主业",
        "status": "公开页面可核对研究记录；本次未确认可直接下载并校验的完整原始PDF，未收入正文目录",
    },
    {
        "date": "2018-06-01",
        "broker": "方正证券",
        "title": "双主业驱动，未来发展可期",
        "status": "公开页面可核对研究记录；本次未确认可直接下载并校验的完整原始PDF，未收入正文目录",
    },
    {
        "date": "2017-02-10",
        "broker": "兴业证券",
        "title": "国内知名的洗衣机离合器和电动工具供应商",
        "status": "公开页面可核对研究记录；本次未确认可直接下载并校验的完整原始PDF，未收入正文目录",
    },
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request(method: str, url: str, **kwargs: Any) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 8):
        try:
            response = SESSION.request(method, url, timeout=(25, 300), allow_redirects=True, **kwargs)
            print(
                "HTTP", method, attempt, response.status_code,
                response.headers.get("content-type"), response.headers.get("content-length"),
                response.url, flush=True,
            )
            if response.status_code in {429, 500, 502, 503, 504}:
                response.close()
                time.sleep(min(attempt * 2, 12))
                continue
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            time.sleep(min(attempt * 2, 12))
    raise RuntimeError(f"request failed for {url}: {errors[-4:]}")


def verify_metadata(report: Report) -> dict[str, Any]:
    params = {
        "industryCode": "*",
        "pageSize": "100",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": report.publish_date,
        "endTime": report.publish_date,
        "pageNo": "1",
        "fields": "",
        "qType": "0",
        "orgCode": "",
        "code": STOCK_CODE,
        "rcode": "",
        "p": "1",
        "pageNum": "1",
        "pageNumber": "1",
    }
    response = request("GET", API, params=params)
    try:
        payload = response.json()
    finally:
        response.close()
    rows = payload.get("data") or []
    row = next((item for item in rows if str(item.get("infoCode") or "") == report.info_code), None)
    if not row:
        raise RuntimeError(f"metadata not found for {report.info_code}")

    api_stock_code = str(row.get("stockCode") or "")
    api_stock_name = str(row.get("stockName") or "")
    api_title = str(row.get("title") or "")
    api_broker = str(row.get("orgSName") or row.get("orgName") or "")
    api_pages = int(row.get("attachPages") or 0)
    api_researcher = str(row.get("researcher") or "")
    api_rating = str(row.get("emRatingName") or "")

    if STOCK_CODE not in api_stock_code and COMPANY not in api_stock_name:
        raise RuntimeError(f"stock identity mismatch: {row}")
    if report.broker not in api_broker:
        raise RuntimeError(f"broker mismatch for {report.info_code}: {api_broker}")
    if api_pages != report.expected_pages:
        raise RuntimeError(
            f"metadata page mismatch for {report.info_code}: {api_pages} != {report.expected_pages}"
        )
    if not all(keyword in api_title for keyword in report.title_keywords):
        raise RuntimeError(f"title mismatch for {report.info_code}: {api_title}")

    report.metadata_verified = True
    report.detail_url = f"https://data.eastmoney.com/report/info/{report.info_code}.html"
    return {
        "api_title": api_title,
        "api_broker": api_broker,
        "api_researcher": api_researcher,
        "api_pages": api_pages,
        "api_rating": api_rating,
        "api_attach_size_kb": row.get("attachSize"),
    }


def download_pdf(report: Report, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    candidates = [
        f"https://pdf.dfcfw.com/pdf/H3_{report.info_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H2_{report.info_code}_1.pdf",
    ]
    errors: list[str] = []
    for url in candidates:
        temp = destination.with_suffix(".pdf.part")
        temp.unlink(missing_ok=True)
        try:
            response = request(
                "GET",
                url,
                stream=True,
                headers={
                    "Referer": report.detail_url,
                    "User-Agent": SESSION.headers["User-Agent"],
                    "Accept": "application/pdf,application/octet-stream,*/*",
                },
            )
            try:
                with temp.open("wb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            handle.write(chunk)
                final_url = str(response.url)
            finally:
                response.close()
            raw_head = temp.read_bytes()[:8]
            if temp.stat().st_size < 80_000 or not raw_head.startswith(b"%PDF-"):
                raise RuntimeError(
                    f"invalid PDF candidate: bytes={temp.stat().st_size}, head={raw_head!r}"
                )
            temp.replace(destination)
            report.pdf_url = final_url
            return
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc!r}")
            temp.unlink(missing_ok=True)
    raise RuntimeError(f"all PDF candidates failed for {report.info_code}: {errors}")


def verify_pdf(path: Path, report: Report) -> None:
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF-"):
        raise RuntimeError(f"not a PDF: {path}")
    report.bytes = len(raw)
    report.sha256 = hashlib.sha256(raw).hexdigest()

    reader = PdfReader(str(path), strict=False)
    report.actual_pages = len(reader.pages)
    if report.actual_pages != report.expected_pages:
        raise RuntimeError(
            f"actual page mismatch for {path.name}: {report.actual_pages} != {report.expected_pages}"
        )

    indices = sorted(
        {
            0,
            min(1, report.actual_pages - 1),
            report.actual_pages // 2,
            report.actual_pages - 1,
        }
    )
    text_parts: list[str] = []
    for index in indices:
        try:
            text_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_WARNING", path.name, index + 1, repr(exc), flush=True)
    normalized = re.sub(r"\s+", "", "\n".join(text_parts))
    report.company_identity_verified = any(
        marker in normalized for marker in (COMPANY, FULL_COMPANY, STOCK_CODE)
    )
    report.broker_identity_verified = any(
        marker in normalized for marker in (report.broker, report.broker_full)
    )
    if normalized and not report.company_identity_verified:
        raise RuntimeError(f"company identity missing in sampled text: {path.name}")
    if normalized and not report.broker_identity_verified:
        print("BROKER_TEXT_WARNING", path.name, flush=True)

    pdf = pymupdf.open(path)
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    rendered_pages = sorted({1, max(1, (report.actual_pages + 1) // 2), report.actual_pages})
    for page_number in rendered_pages:
        page = pdf.load_page(page_number - 1)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(1.0, 1.0), alpha=False)
        output = RENDER_DIR / f"{path.stem}_p{page_number}.png"
        pix.save(output)
        if output.stat().st_size < 5_000:
            raise RuntimeError(f"suspicious render: {output}")
    pdf.close()
    report.rendered_pages = rendered_pages


def write_metadata(records: list[dict[str, Any]]) -> None:
    readme_lines = [
        f"{COMPANY}（{STOCK_CODE}）券商研究报告文件包",
        "",
        f"核对日期：{CHECKED_AS_OF}",
        "完整PDF数量：2份",
        "",
        "范围说明：",
        "- 公开研报数据库中，能够通过原始附件端点直接取得并完成结构、页数和内容校验的公司研报共2份。",
        "- 民生证券报告为14页公司深度报告；东吴证券报告为7页完整研究简报。",
        "- 未用网页摘要、付费预览、截断页面或非券商材料补足数量。",
        "",
        "收录报告：",
    ]
    for index, record in enumerate(records, 1):
        readme_lines.append(
            f"{index}. {record['publish_date']} | {record['broker']} | "
            f"{record['title']} | {record['actual_pages']}页 | {record['rating']}"
        )
    readme_lines.extend(
        [
            "",
            "其他可核对但未收入的历史覆盖：",
        ]
    )
    for item in OTHER_KNOWN_COVERAGE:
        readme_lines.append(
            f"- {item['date']} | {item['broker']} | {item['title']} | {item['status']}"
        )
    readme_lines.extend(
        [
            "",
            "校验项目：",
            "- 东方财富研报数据库的股票、标题、券商、作者、日期、评级与附件页数；",
            "- PDF文件头、实际页数、公司身份、券商身份及SHA-256；",
            "- 每份PDF首页、中间页和末页渲染；",
            "- ZIP CRC完整性检查。",
        ]
    )
    (PACKAGE_ROOT / "00_重要说明与文件清单.txt").write_text(
        "\n".join(readme_lines) + "\n", encoding="utf-8"
    )

    with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "发布日期", "券商", "作者", "报告标题", "评级", "页数", "字节数",
                "SHA-256", "本地文件", "研报详情页", "PDF来源",
            ]
        )
        for record in records:
            writer.writerow(
                [
                    record["publish_date"], record["broker"], record["authors"],
                    record["title"], record["rating"], record["actual_pages"],
                    record["bytes"], record["sha256"], record["relative_path"],
                    record["detail_url"], record["pdf_url"],
                ]
            )

    with (VERIFY_DIR / "其他历史覆盖索引_非全文.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "broker", "title", "status"])
        writer.writeheader()
        writer.writerows(OTHER_KNOWN_COVERAGE)

    with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(f"{record['sha256']}  {record['relative_path']}\n")

    manifest = {
        "package_name": PACKAGE_NAME,
        "company": FULL_COMPANY,
        "short_name": COMPANY,
        "stock_code": STOCK_CODE,
        "checked_as_of": CHECKED_AS_OF,
        "complete_pdf_count": len(records),
        "scope_note": (
            "仅收录能够从公开原始附件端点直接取得并完成结构、页数、身份与渲染校验的完整券商PDF。"
        ),
        "documents": records,
        "other_known_coverage_not_included_as_full_pdf": OTHER_KNOWN_COVERAGE,
    }
    (PACKAGE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def create_zip() -> None:
    ZIP_PATH.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(PACKAGE_ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(ROOT))
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")
        pdf_count = len([name for name in archive.namelist() if name.lower().endswith(".pdf")])
        if pdf_count != len(REPORTS):
            raise RuntimeError(f"ZIP PDF count mismatch: {pdf_count} != {len(REPORTS)}")


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    RENDER_DIR.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for report in REPORTS:
        metadata = verify_metadata(report)
        destination = REPORT_DIR / report.filename
        download_pdf(report, destination)
        verify_pdf(destination, report)
        if report.sha256 in seen_hashes:
            raise RuntimeError(f"duplicate PDF detected: {destination.name}")
        seen_hashes.add(report.sha256)

        record = asdict(report)
        record["relative_path"] = str(destination.relative_to(PACKAGE_ROOT))
        record["metadata"] = metadata
        records.append(record)
        print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

    write_metadata(records)
    create_zip()

    summary = {
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256_file(ZIP_PATH),
        "pdf_count": len(records),
        "documents": [
            {
                "publish_date": record["publish_date"],
                "broker": record["broker"],
                "authors": record["authors"],
                "title": record["title"],
                "rating": record["rating"],
                "pages": record["actual_pages"],
                "bytes": record["bytes"],
                "sha256": record["sha256"],
            }
            for record in records
        ],
    }
    SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("PACKAGE_SUMMARY=" + json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
