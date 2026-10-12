from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path

import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-10-12"
PACKAGE_NAME = "慈文传媒_002343_券商深度报告_3份"
PACKAGE_DIR = Path(PACKAGE_NAME)
REPORTS_DIR = PACKAGE_DIR / "01_券商深度报告"
VERIFY_DIR = Path("_verify_ciwen_reports")

REPORTS_DIR.mkdir(parents=True, exist_ok=True)
VERIFY_DIR.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "application/pdf,text/html,application/xhtml+xml,*/*;q=0.8",
}


def fetch_report_index() -> list[dict]:
    api_url = "https://reportapi.eastmoney.com/report/list"
    params = {
        "pageSize": "100",
        "pageNo": "1",
        "code": "002343",
        "qType": "0",
        "industryCode": "*",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": "2010-01-01",
        "endTime": CHECKED_AS_OF,
        "orgCode": "",
        "rcode": "",
        "fields": "",
    }
    response = session.get(
        api_url,
        params=params,
        headers={**HEADERS, "Referer": "https://data.eastmoney.com/report/stock.jshtml"},
        timeout=90,
    )
    print("API", response.status_code, response.headers.get("content-type"), len(response.content), response.url, flush=True)
    response.raise_for_status()
    rows = response.json().get("data") or []
    if not rows:
        raise RuntimeError("Eastmoney report API returned no records")
    return rows


PRIMARY_SPECS = [
    {
        "key": "发布重要战略纲要",
        "preferred_org": "民生证券",
        "filename": "20240731_民生证券_首次覆盖_发布重要战略纲要先锋转型未来可期.pdf",
        "classification": "首次覆盖报告",
    },
    {
        "key": "长视频内容领军者",
        "preferred_org": "民生证券",
        "filename": "20180523_民生证券_深度报告_长视频内容领军者充分享受付费市场红利.pdf",
        "classification": "公司深度报告",
    },
    {
        "key": "头部剧龙头公司",
        "preferred_org": "平安证券",
        "filename": "20180327_平安证券_首次覆盖_头部剧龙头公司引领行业变革.pdf",
        "classification": "公司首次覆盖报告",
    },
]

FALLBACK_SPECS = [
    {
        "key": "业内顶级剧王",
        "preferred_org": "国金证券",
        "filename": "20170914_国金证券_深度研究_业内顶级剧王.pdf",
        "classification": "公司深度研究",
    },
    {
        "key": "破茧化蝶",
        "preferred_org": "西南证券",
        "filename": "20170106_西南证券_深度报告_破茧化蝶老牌影视蜕变网生龙头.pdf",
        "classification": "公司深度报告",
    },
    {
        "key": "领航内容制作精品化新时代",
        "preferred_org": "中国国际金融",
        "filename": "20161209_中金公司_首次覆盖_领航内容制作精品化新时代.pdf",
        "classification": "首次覆盖报告",
    },
]


def locate(rows: list[dict], spec: dict) -> dict | None:
    matches = [row for row in rows if spec["key"] in (row.get("title") or "")]
    preferred_org = spec.get("preferred_org")
    if preferred_org:
        preferred = [
            row
            for row in matches
            if preferred_org in ((row.get("orgSName") or "") + (row.get("orgName") or ""))
        ]
        if preferred:
            matches = preferred
    return matches[0] if matches else None


def choose_reports(rows: list[dict]) -> list[tuple[dict, dict]]:
    selected: list[tuple[dict, dict]] = []
    used_info: set[str] = set()
    for spec in PRIMARY_SPECS:
        row = locate(rows, spec)
        if row and row.get("infoCode") not in used_info:
            selected.append((spec, row))
            used_info.add(row["infoCode"])
        else:
            print("PRIMARY_NOT_FOUND", json.dumps(spec, ensure_ascii=False), flush=True)

    for spec in FALLBACK_SPECS:
        if len(selected) >= 3:
            break
        row = locate(rows, spec)
        if row and row.get("infoCode") not in used_info:
            selected.append((spec, row))
            used_info.add(row["infoCode"])

    if len(selected) < 3:
        print(
            "AVAILABLE_TITLES",
            json.dumps(
                [
                    {
                        "title": row.get("title"),
                        "org": row.get("orgSName"),
                        "infoCode": row.get("infoCode"),
                        "pages": row.get("attachPages"),
                    }
                    for row in rows
                ],
                ensure_ascii=False,
                indent=2,
            ),
            flush=True,
        )
        raise RuntimeError(f"Only {len(selected)} target reports found; expected 3")
    return selected[:3]


def get_with_retries(url: str, referer: str, require_pdf: bool = False) -> requests.Response:
    last_response: requests.Response | None = None
    last_error: Exception | None = None
    for attempt in range(1, 5):
        try:
            response = session.get(
                url,
                headers={**HEADERS, "Referer": referer},
                timeout=180,
                allow_redirects=True,
            )
            print(
                "HTTP",
                attempt,
                response.status_code,
                response.headers.get("content-type"),
                len(response.content),
                response.url,
                flush=True,
            )
            last_response = response
            if response.status_code == 200 and (
                not require_pdf or response.content.startswith(b"%PDF")
            ):
                return response
        except Exception as exc:  # noqa: BLE001
            print("REQUEST_ERROR", attempt, url, repr(exc), flush=True)
            last_error = exc
        time.sleep(attempt * 2)
    if last_error and last_response is None:
        raise last_error
    assert last_response is not None
    return last_response


def download_report(row: dict, out_path: Path) -> tuple[str, str, str]:
    info_code = row["infoCode"]
    detail_url = f"https://data.eastmoney.com/report/info/{info_code}.html"
    candidates = [
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf?{int(time.time() * 1000)}",
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.PDF",
    ]
    errors: list[str] = []
    for url in candidates:
        try:
            response = get_with_retries(url, detail_url, require_pdf=True)
            if (
                response.status_code == 200
                and response.content.startswith(b"%PDF")
                and len(response.content) > 100_000
            ):
                out_path.write_bytes(response.content)
                return url, response.url, detail_url
            errors.append(
                f"{url}: status={response.status_code} bytes={len(response.content)}"
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc!r}")
    raise RuntimeError(
        "PDF download failed for " + info_code + ": " + " | ".join(errors)
    )


def validate_report(index: int, spec: dict, row: dict) -> dict:
    path = REPORTS_DIR / spec["filename"]
    source_url, final_url, detail_url = download_report(row, path)
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()

    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)], text=True, capture_output=True, check=False
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path}: {qpdf.stdout}\n{qpdf.stderr}")

    reader = PdfReader(str(path))
    pages = len(reader.pages)
    expected_pages = int(row.get("attachPages") or 0)
    if pages < 10:
        raise RuntimeError(f"Report unexpectedly short: {path}, pages={pages}")
    if expected_pages and pages != expected_pages:
        raise RuntimeError(
            f"Page mismatch for {path}: got {pages}, API={expected_pages}"
        )

    text_path = VERIFY_DIR / f"{index:02d}.txt"
    subprocess.run(["pdftotext", str(path), str(text_path)], check=True)
    text = text_path.read_text(encoding="utf-8", errors="ignore")
    normalized = re.sub(r"\s+", "", text)
    if "慈文传媒" not in normalized and "002343" not in normalized:
        raise RuntimeError(f"Company identity check failed: {path}")

    broker_short = row.get("orgSName") or ""
    broker_full = row.get("orgName") or ""
    if broker_short and broker_short not in text and broker_full not in text:
        print("BROKER_TEXT_NOT_EXTRACTED", path, broker_short, flush=True)

    render_pages = sorted({1, max(1, (pages + 1) // 2), pages})
    render_files: list[str] = []
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
                "105",
                str(path),
                str(base),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if render.returncode != 0:
            raise RuntimeError(
                f"Render failed {path} page {page_number}: {render.stderr}"
            )
        image = Path(str(base) + ".png")
        if not image.exists() or image.stat().st_size < 10_000:
            raise RuntimeError(f"Render output invalid: {image}")
        render_files.append(str(image))

    record = {
        "date": (row.get("publishDate") or "")[:10],
        "broker": row.get("orgSName") or row.get("orgName"),
        "broker_full_name": row.get("orgName"),
        "researchers": row.get("researcher"),
        "title": row.get("title"),
        "classification": spec["classification"],
        "rating": row.get("emRatingName") or row.get("sRatingName") or "",
        "infoCode": row.get("infoCode"),
        "relative_path": str(path.relative_to(PACKAGE_DIR)),
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256,
        "source_url": source_url,
        "download_final_url": final_url,
        "detail_url": detail_url,
        "qpdf_return_code": qpdf.returncode,
        "rendered_pages": render_pages,
        "render_files": render_files,
        "company_identity_verified": True,
    }
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)
    return record


def write_metadata(records: list[dict]) -> None:
    readme_lines = [
        "慈文传媒（002343）券商深度报告资料包",
        "",
        f"核对日期：{CHECKED_AS_OF}",
        f"收录数量：{len(records)}份",
        "",
        "筛选口径",
        "- 仅收录明确标注为首次覆盖、公司深度或公司首次覆盖的系统性研究报告。",
        "- 未使用季报点评、年报点评、事件点评、新闻稿或网页摘要凑数。",
        "- PDF来自东方财富研报附件镜像，保留券商原始排版。",
        "",
        "文件概览",
    ]
    for i, record in enumerate(records, 1):
        readme_lines.append(
            f"{i}. {record['date']}｜{record['broker']}｜{record['title']}｜"
            f"{record['pages']}页｜{record['researchers']}"
        )
    readme_lines.extend(
        [
            "",
            "校验说明",
            "- 每份PDF均检查PDF文件头、qpdf结构、实际页数、慈文传媒或股票代码身份。",
            "- 每份PDF均渲染首页、中间页和末页，验证可正常显示。",
            "- SHA-256见 SHA256SUMS.txt；完整来源与元数据见 文件清单.csv 和 manifest.json。",
            "",
        ]
    )
    (PACKAGE_DIR / "README.txt").write_text(
        "\n".join(readme_lines), encoding="utf-8"
    )

    fields = [
        "date",
        "broker",
        "broker_full_name",
        "researchers",
        "title",
        "classification",
        "rating",
        "infoCode",
        "relative_path",
        "pages",
        "bytes",
        "sha256",
        "detail_url",
        "source_url",
        "download_final_url",
    ]
    with (PACKAGE_DIR / "文件清单.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field, "") for field in fields})

    with (PACKAGE_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as file:
        for record in records:
            file.write(f"{record['sha256']}  {record['relative_path']}\n")

    manifest = {
        "package_name": PACKAGE_NAME,
        "company": "慈文传媒股份有限公司",
        "stock_code": "002343",
        "checked_as_of": CHECKED_AS_OF,
        "document_count": len(records),
        "selection_policy": "首次覆盖/公司深度报告；排除短篇财报点评和网页摘要",
        "records": records,
    }
    (PACKAGE_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def build_zip() -> Path:
    zip_path = Path(PACKAGE_NAME + ".zip")
    with zipfile.ZipFile(
        zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for item in sorted(PACKAGE_DIR.rglob("*")):
            if item.is_file():
                archive.write(item, arcname=str(item))
    with zipfile.ZipFile(zip_path, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP integrity failed at {bad}")
    return zip_path


def main() -> None:
    rows = fetch_report_index()
    selected = choose_reports(rows)
    records: list[dict] = []
    seen_hashes: set[str] = set()
    for index, (spec, row) in enumerate(selected, 1):
        record = validate_report(index, spec, row)
        if record["sha256"] in seen_hashes:
            raise RuntimeError(f"Duplicate PDF detected: {record['relative_path']}")
        seen_hashes.add(record["sha256"])
        records.append(record)

    write_metadata(records)
    zip_path = build_zip()
    zip_sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    print(
        "FINAL_ZIP",
        zip_path,
        "bytes",
        zip_path.stat().st_size,
        "sha256",
        zip_sha,
        flush=True,
    )


if __name__ == "__main__":
    main()
