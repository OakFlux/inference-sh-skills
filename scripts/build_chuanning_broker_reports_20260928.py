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

COMPANY = "川宁生物"
CODE = "301301"
AS_OF = "2026-09-28"
ROOT = Path(f"{COMPANY}_{CODE}_券商深度报告_3份")
VERIFY_DIR = Path("_verify_chuanning_broker")
ZIP_NAME = f"{COMPANY}_{CODE}_券商深度报告_3份_20260928.zip"
ROOT.mkdir(parents=True, exist_ok=True)
VERIFY_DIR.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})
REPORT_API = "https://reportapi.eastmoney.com/report/list"
PDF_TEMPLATE = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"

TARGETS = [
    {
        "org": "开源证券",
        "title_keyword": "抗生素中间体价格触底回升",
        "preferred_date": "2026-08-17",
        "label": "开源证券_公司首次覆盖报告_抗生素中间体价格触底回升_合成生物学开启新成长",
    },
    {
        "org": "中泰证券",
        "title_keyword": "抗生素龙头再添合成生物双翼",
        "preferred_date": "2025-12-28",
        "label": "中泰证券_公司深度报告_抗生素龙头再添合成生物双翼_成长值得期待",
    },
    {
        "org": "民生证券",
        "title_keyword": "抗生素龙头格局再优化",
        "preferred_date": "2024-08-01",
        "label": "民生证券_首次覆盖报告_抗生素龙头格局再优化_合成生物学拓宽成长边界",
    },
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def request_with_retry(url: str, *, params: dict[str, Any] | None = None) -> requests.Response:
    last: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = SESSION.get(url, params=params, timeout=(20, 180), allow_redirects=True)
            print(
                "HTTP",
                attempt,
                response.status_code,
                response.headers.get("content-type"),
                len(response.content),
                response.url,
                flush=True,
            )
            if response.status_code in {429, 500, 502, 503, 504}:
                time.sleep(attempt * 2)
                continue
            response.raise_for_status()
            return response
        except Exception as exc:
            last = exc
            if attempt < 5:
                time.sleep(attempt * 2)
    raise RuntimeError(f"GET failed after retries: {url}: {last}")


def parse_json_or_jsonp(text: str) -> Any:
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)
    match = re.search(r"^[^(]+\((.*)\)\s*;?$", text, flags=re.S)
    if not match:
        raise RuntimeError(f"Unexpected Eastmoney API payload prefix: {text[:120]!r}")
    return json.loads(match.group(1))


def list_reports() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for page in range(1, 8):
        params = {
            "industryCode": "*",
            "pageSize": "100",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": "2022-01-01",
            "endTime": AS_OF,
            "pageNo": str(page),
            "fields": "",
            "qType": "0",
            "orgCode": "",
            "code": CODE,
            "rcode": "",
            "p": str(page),
            "pageNum": str(page),
            "pageNumber": str(page),
        }
        response = request_with_retry(REPORT_API, params=params)
        payload = parse_json_or_jsonp(response.text)
        page_records = []
        if isinstance(payload, dict):
            page_records = payload.get("data") or payload.get("Data") or payload.get("result") or []
            if isinstance(page_records, dict):
                page_records = page_records.get("data") or page_records.get("list") or []
        elif isinstance(payload, list):
            page_records = payload
        if not isinstance(page_records, list):
            raise RuntimeError(f"Unexpected report list shape: {type(page_records)}")
        print("REPORT_PAGE", page, len(page_records), flush=True)
        if not page_records:
            break
        records.extend(dict(item) for item in page_records if isinstance(item, dict))
        if len(page_records) < 100:
            break
    print("REPORT_COUNT", len(records), flush=True)
    for item in records:
        print(
            "REPORT",
            str(item.get("publishDate") or "")[:10],
            item.get("orgSName"),
            item.get("attachPages"),
            item.get("infoCode"),
            item.get("title"),
            flush=True,
        )
    return records


def norm(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def choose_report(records: list[dict[str, Any]], target: dict[str, str]) -> dict[str, Any]:
    org = norm(target["org"])
    keyword = norm(target["title_keyword"])
    candidates = [
        item
        for item in records
        if org in norm(item.get("orgSName")) and keyword in norm(item.get("title"))
    ]
    if not candidates:
        # Fallback keeps the institution constraint and ranks by title token overlap.
        tokens = [t for t in re.split(r"[，、：:—\-]", target["title_keyword"]) if len(t) >= 4]
        org_records = [item for item in records if org in norm(item.get("orgSName"))]
        candidates = sorted(
            org_records,
            key=lambda item: (
                sum(norm(t) in norm(item.get("title")) for t in tokens),
                int(item.get("attachPages") or 0),
                str(item.get("publishDate") or ""),
            ),
            reverse=True,
        )[:3]
    if not candidates:
        raise RuntimeError(f"No report candidate found for {target}")

    preferred_date = target["preferred_date"]
    candidates.sort(
        key=lambda item: (
            str(item.get("publishDate") or "")[:10] == preferred_date,
            int(item.get("attachPages") or 0),
            str(item.get("publishDate") or ""),
        ),
        reverse=True,
    )
    chosen = dict(candidates[0])
    if not chosen.get("infoCode"):
        raise RuntimeError(f"Chosen report lacks infoCode: {chosen}")
    print("SELECTED", target["org"], json.dumps(chosen, ensure_ascii=False), flush=True)
    return chosen


def safe_filename(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", "", value)
    return value[:180]


def download_pdf(record: dict[str, Any], target: dict[str, str]) -> tuple[Path, str]:
    info_code = str(record["infoCode"])
    url = PDF_TEMPLATE.format(info_code=info_code)
    response = request_with_retry(url)
    data = response.content
    if not data.startswith(b"%PDF"):
        raise RuntimeError(f"Not a PDF for {info_code}: {data[:30]!r}")
    if len(data) < 200_000:
        raise RuntimeError(f"Suspiciously small report PDF: {info_code}, {len(data)} bytes")
    pubdate = str(record.get("publishDate") or "")[:10].replace("-", "")
    filename = f"{pubdate}_{safe_filename(target['label'])}.pdf"
    path = ROOT / filename
    path.write_bytes(data)
    return path, url


def validate_pdf(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 15:
        raise RuntimeError(f"Report is not deep enough or incomplete: {path.name}, {pages} pages")
    expected_pages = int(record.get("attachPages") or 0)
    if expected_pages and abs(pages - expected_pages) > 1:
        raise RuntimeError(
            f"Page count mismatch for {path.name}: actual={pages}, API={expected_pages}"
        )

    samples: list[str] = []
    for idx in sorted(set([0, 1, 2, max(0, pages // 2), pages - 1])):
        try:
            samples.append(reader.pages[idx].extract_text() or "")
        except Exception:
            pass
    text = "\n".join(samples).lower()
    if len(text.strip()) > 200 and not any(term in text for term in ("川宁", "301301", "chuanning")):
        raise RuntimeError(f"Company identity not found in {path.name}")

    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=180
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf validation failed for {path.name}: {qpdf.stderr}")

    for page_no, suffix in ((1, "first"), (pages, "last")):
        out_base = VERIFY_DIR / f"{path.stem}_{suffix}"
        result = subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-r",
                "72",
                "-f",
                str(page_no),
                "-l",
                str(page_no),
                "-singlefile",
                str(path),
                str(out_base),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        png = Path(str(out_base) + ".png")
        if result.returncode != 0 or not png.exists() or png.stat().st_size < 1000:
            raise RuntimeError(f"Render check failed for {path.name} page {page_no}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "first_last_page_rendered": True,
    }


def main() -> None:
    records = list_reports()
    output_records: list[dict[str, Any]] = []
    for target in TARGETS:
        record = choose_report(records, target)
        path, pdf_url = download_pdf(record, target)
        validation = validate_pdf(path, record)
        output = {
            "filename": path.name,
            "title": str(record.get("title") or ""),
            "institution": str(record.get("orgSName") or target["org"]),
            "analysts": str(record.get("researcher") or record.get("researcherList") or ""),
            "publish_date": str(record.get("publishDate") or "")[:10],
            "rating": str(record.get("emRatingName") or ""),
            "info_code": str(record.get("infoCode") or ""),
            "eastmoney_detail_url": f"https://data.eastmoney.com/report/info/{record.get('infoCode')}.html",
            "pdf_url": pdf_url,
            **validation,
        }
        output_records.append(output)
        print("PACKAGED", json.dumps(output, ensure_ascii=False), flush=True)

    if len(output_records) != 3:
        raise RuntimeError(f"Expected 3 reports, got {len(output_records)}")
    if len({item["sha256"] for item in output_records}) != 3:
        raise RuntimeError("Duplicate report content detected")

    readme_lines = [
        f"{COMPANY}（{CODE}）券商深度报告文件包",
        "",
        f"整理日期：{AS_OF}",
        "",
        "收录原则：仅收录可从东方财富研报中心公开PDF端点直接取得的完整公司深度或首次覆盖报告；未绕过登录、会员或付费限制。",
        "",
        "文件清单：",
    ]
    for idx, item in enumerate(output_records, 1):
        readme_lines.extend(
            [
                f"{idx}. {item['institution']}｜{item['title']}",
                f"   日期：{item['publish_date']}；页数：{item['pages']}；评级：{item['rating'] or '未标注'}",
                f"   PDF来源：{item['pdf_url']}",
            ]
        )
    readme_lines.extend(
        [
            "",
            "版权与使用说明：报告版权归相应证券研究机构及作者所有，本文件包仅作个人研究和资料整理使用，不构成投资建议，不得用于商业传播。",
        ]
    )
    (ROOT / "00_文件清单与来源说明.txt").write_text(
        "\n".join(readme_lines) + "\n", encoding="utf-8"
    )

    with (ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(output_records[0].keys()))
        writer.writeheader()
        writer.writerows(output_records)

    (ROOT / "manifest.json").write_text(
        json.dumps(
            {
                "company": COMPANY,
                "stock_code": CODE,
                "as_of": AS_OF,
                "source": "东方财富研报中心公开API与公开PDF端点",
                "reports": output_records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{item['sha256']}  {item['filename']}" for item in output_records) + "\n",
        encoding="utf-8",
    )

    zip_path = Path(ZIP_NAME)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=f"{ROOT.name}/{path.relative_to(ROOT).as_posix()}")
    with zipfile.ZipFile(zip_path, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC test failed at {bad}")
        pdf_count = sum(name.lower().endswith(".pdf") for name in zf.namelist())
        if pdf_count != 3:
            raise RuntimeError(f"Unexpected PDF count in ZIP: {pdf_count}")

    print("FINAL_ZIP", zip_path.name, zip_path.stat().st_size, sha256_file(zip_path), flush=True)
    print("FINAL_RECORDS", json.dumps(output_records, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
