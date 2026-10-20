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

COMPANY = "横河精密"
HISTORICAL_NAME = "横河模具"
CODE = "300539"
AS_OF = "2026-10-20"
ROOT = Path(f"{COMPANY}_{CODE}_券商研究报告_3份_截至{AS_OF.replace('-', '')}")
VERIFY_DIR = Path("_verify_henghe_precision_broker_reports")
ZIP_NAME = f"{COMPANY}_{CODE}_券商研究报告_3份_截至{AS_OF.replace('-', '')}.zip"
ROOT.mkdir(parents=True, exist_ok=True)
VERIFY_DIR.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://data.eastmoney.com/",
    }
)
REPORT_API = "https://reportapi.eastmoney.com/report/list"
PDF_TEMPLATES = (
    "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
    "https://pdf.dfcfw.com/pdf/H2_{info_code}_1.pdf",
    "https://pdf.dfcfw.com/pdf/H1_{info_code}_1.pdf",
)

TARGETS: list[dict[str, Any]] = [
    {
        "order": 1,
        "org": "浙商证券",
        "title_keyword": "优质精密制造企业新能源汽车结构件打开成长空间",
        "preferred_date": "2023-06-20",
        "report_class": "公司深度报告",
        "min_pages": 20,
        "filename_label": "浙商证券_公司深度报告_优质精密制造企业_新能源汽车结构件打开成长空间",
    },
    {
        "order": 2,
        "org": "东北证券",
        "title_keyword": "25H1业绩显著增长积极布局新兴赛道",
        "preferred_date": "2025-09-03",
        "report_class": "首次覆盖报告",
        "min_pages": 5,
        "filename_label": "东北证券_首次覆盖报告_25H1业绩显著增长_积极布局新兴赛道",
    },
    {
        "order": 3,
        "org": "浙商证券",
        "title_keyword": "全球无人机新秀崛起无人机机器人家电汽零三箭齐发",
        "preferred_date": "2026-05-11",
        "report_class": "推荐报告",
        "min_pages": 4,
        "filename_label": "浙商证券_推荐报告_全球无人机新秀崛起_无人机机器人家电汽零三箭齐发",
    },
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request_with_retry(url: str, *, params: dict[str, Any] | None = None) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, 8):
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
            if response.status_code in {403, 408, 425, 429, 500, 502, 503, 504}:
                response.close()
                time.sleep(min(attempt * 2, 12))
                continue
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < 7:
                time.sleep(min(attempt * 2, 12))
    raise RuntimeError(f"GET failed after retries: {url}: {last_error}")


def parse_json_or_jsonp(text: str) -> Any:
    payload = text.strip()
    if payload.startswith("{") or payload.startswith("["):
        return json.loads(payload)
    match = re.search(r"^[^(]+\((.*)\)\s*;?$", payload, flags=re.S)
    if not match:
        raise RuntimeError(f"Unexpected Eastmoney API payload prefix: {payload[:160]!r}")
    return json.loads(match.group(1))


def normalize(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").lower())


def list_reports() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for page in range(1, 10):
        params = {
            "industryCode": "*",
            "pageSize": "100",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": "2016-01-01",
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
        try:
            payload = parse_json_or_jsonp(response.text)
        finally:
            response.close()
        page_records: Any = []
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

    unique: dict[str, dict[str, Any]] = {}
    for item in records:
        info_code = str(item.get("infoCode") or "")
        if info_code:
            unique[info_code] = item
    records = list(unique.values())
    print("REPORT_COUNT", len(records), flush=True)
    for item in sorted(records, key=lambda row: str(row.get("publishDate") or ""), reverse=True):
        print(
            "REPORT",
            str(item.get("publishDate") or "")[:10],
            item.get("orgSName"),
            item.get("attachPages"),
            item.get("infoCode"),
            item.get("title"),
            flush=True,
        )
    Path("report_catalog.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return records


def choose_report(records: list[dict[str, Any]], target: dict[str, Any]) -> dict[str, Any]:
    org_key = normalize(target["org"])
    title_key = normalize(target["title_keyword"])
    candidates = [
        item
        for item in records
        if org_key in normalize(item.get("orgSName"))
        and (title_key in normalize(item.get("title")) or normalize(item.get("title")) in title_key)
    ]

    if not candidates:
        tokens = [
            token
            for token in re.split(r"[，、：:；;（）()\-—\s]+", str(target["title_keyword"]))
            if len(normalize(token)) >= 3
        ]
        org_records = [item for item in records if org_key in normalize(item.get("orgSName"))]
        scored: list[tuple[int, int, str, dict[str, Any]]] = []
        for item in org_records:
            title_norm = normalize(item.get("title"))
            overlap = sum(normalize(token) in title_norm for token in tokens)
            scored.append(
                (
                    overlap,
                    int(item.get("attachPages") or 0),
                    str(item.get("publishDate") or ""),
                    item,
                )
            )
        scored.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
        candidates = [row[3] for row in scored if row[0] > 0][:5]

    if not candidates:
        raise RuntimeError(f"No report candidate found for target: {target}")

    preferred_date = str(target["preferred_date"])
    candidates.sort(
        key=lambda item: (
            str(item.get("publishDate") or "")[:10] == preferred_date,
            normalize(target["title_keyword"]) in normalize(item.get("title")),
            int(item.get("attachPages") or 0),
            str(item.get("publishDate") or ""),
        ),
        reverse=True,
    )
    selected = dict(candidates[0])
    if not selected.get("infoCode"):
        raise RuntimeError(f"Selected report lacks infoCode: {selected}")
    print("SELECTED", json.dumps({"target": target, "record": selected}, ensure_ascii=False), flush=True)
    return selected


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]", "_", value)
    cleaned = re.sub(r"\s+", "", cleaned)
    return cleaned[:180]


def download_pdf(record: dict[str, Any], target: dict[str, Any]) -> tuple[Path, str]:
    info_code = str(record["infoCode"])
    errors: list[str] = []
    for template in PDF_TEMPLATES:
        url = template.format(info_code=info_code)
        try:
            response = request_with_retry(url)
            try:
                data = response.content
                content_type = str(response.headers.get("content-type") or "")
            finally:
                response.close()
            if not data.startswith(b"%PDF"):
                errors.append(f"{url}: not PDF, type={content_type}, prefix={data[:24]!r}")
                continue
            if len(data) < 80_000:
                errors.append(f"{url}: suspiciously small PDF, {len(data)} bytes")
                continue
            publish_date = str(record.get("publishDate") or target["preferred_date"])[:10].replace("-", "")
            filename = f"{target['order']:02d}_{publish_date}_{safe_filename(str(target['filename_label']))}.pdf"
            path = ROOT / filename
            path.write_bytes(data)
            return path, url
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc!r}")
    raise RuntimeError(f"Unable to download PDF for {info_code}: {errors}")


def render_page(path: Path, page_no: int, suffix: str) -> None:
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
        raise RuntimeError(f"Render check failed for {path.name} page {page_no}: {result.stderr[-1000:]}")


def validate_pdf(path: Path, record: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=180
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf validation failed for {path.name}: {qpdf.stderr[-2000:]}")

    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Encrypted PDF cannot be opened: {path.name}: {exc!r}") from exc
    pages = len(reader.pages)
    min_pages = int(target["min_pages"])
    if pages < min_pages:
        raise RuntimeError(f"Incomplete or too-short report: {path.name}, {pages} pages < {min_pages}")

    expected_pages = int(record.get("attachPages") or 0)
    if expected_pages and abs(pages - expected_pages) > 1:
        raise RuntimeError(f"Page-count mismatch: {path.name}, actual={pages}, API={expected_pages}")

    sample_indices = sorted({0, 1, min(2, pages - 1), max(0, pages // 2), pages - 1})
    samples: list[str] = []
    for index in sample_indices:
        try:
            samples.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_EXTRACT_WARNING", path.name, index + 1, repr(exc), flush=True)
    text = normalize("\n".join(samples))
    identity_terms = (normalize(COMPANY), normalize(HISTORICAL_NAME), CODE)
    if len(text) > 200 and not any(term in text for term in identity_terms):
        raise RuntimeError(f"Company identity not found in sampled text: {path.name}")

    first_text_parts: list[str] = []
    for index in range(min(4, pages)):
        try:
            first_text_parts.append(reader.pages[index].extract_text() or "")
        except Exception:
            pass
    first_text = normalize("\n".join(first_text_parts))
    org_text = normalize(target["org"])
    if len(first_text) > 200 and org_text and org_text not in first_text:
        print("ORG_MARKER_WARNING", path.name, target["org"], flush=True)

    render_page(path, 1, "first")
    render_page(path, pages, "last")

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
        validation = validate_pdf(path, record, target)
        output = {
            "filename": path.name,
            "report_class": target["report_class"],
            "title": str(record.get("title") or target["title_keyword"]),
            "institution": str(record.get("orgSName") or target["org"]),
            "analysts": str(record.get("researcher") or record.get("researcherList") or ""),
            "publish_date": str(record.get("publishDate") or target["preferred_date"])[:10],
            "rating": str(record.get("emRatingName") or record.get("ratingName") or ""),
            "info_code": str(record.get("infoCode") or ""),
            "declared_pages": int(record.get("attachPages") or 0) or None,
            "eastmoney_detail_url": f"https://data.eastmoney.com/report/info/{record.get('infoCode')}.html",
            "pdf_url": pdf_url,
            **validation,
        }
        output_records.append(output)
        print("PACKAGED", json.dumps(output, ensure_ascii=False), flush=True)

    if len(output_records) != 3:
        raise RuntimeError(f"Expected 3 reports, got {len(output_records)}")
    if len({item["sha256"] for item in output_records}) != 3:
        raise RuntimeError("Duplicate report contents detected")

    readme_lines = [
        f"{COMPANY}（{CODE}）券商研究报告文件包",
        "",
        f"整理日期：{AS_OF}",
        "",
        "收录说明：本包优先保留1份正式公司深度报告，并补充2份较新的首次覆盖/推荐报告，以兼顾系统性和时效性。",
        "PDF均通过东方财富研报中心公开PDF端点取得，未绕过登录、会员或付费限制。",
        "",
        "文件清单：",
    ]
    for index, item in enumerate(output_records, 1):
        readme_lines.extend(
            [
                f"{index}. {item['institution']}｜{item['report_class']}｜{item['title']}",
                f"   日期：{item['publish_date']}；页数：{item['pages']}；评级：{item['rating'] or '公开数据未标注'}",
                f"   来源：{item['eastmoney_detail_url']}",
            ]
        )
    readme_lines.extend(
        [
            "",
            "校验：每份PDF均完成文件头、页数、公司身份、qpdf结构检查及首末页渲染检查；ZIP已完成CRC测试。",
            "",
            "版权与使用说明：报告版权归相应证券研究机构及作者所有，本文件包仅供个人研究和资料整理使用，不构成投资建议，不得用于商业传播。",
        ]
    )
    (ROOT / "00_文件清单与来源说明.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

    csv_fields = list(output_records[0].keys())
    with (ROOT / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields)
        writer.writeheader()
        writer.writerows(output_records)

    manifest = {
        "company": COMPANY,
        "stock_code": CODE,
        "as_of": AS_OF,
        "source": "东方财富研报中心公开API及公开PDF端点",
        "selection_policy": "1份正式公司深度报告 + 2份较新的首次覆盖或推荐报告",
        "reports": output_records,
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(f"{item['sha256']}  {item['filename']}" for item in output_records) + "\n",
        encoding="utf-8",
    )

    zip_path = Path(ZIP_NAME)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=f"{ROOT.name}/{path.relative_to(ROOT).as_posix()}")

    with zipfile.ZipFile(zip_path, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC test failed at {bad}")
        pdf_names = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
        if len(pdf_names) != 3:
            raise RuntimeError(f"Unexpected PDF count in ZIP: {len(pdf_names)}")

    summary = {
        "zip": zip_path.name,
        "zip_bytes": zip_path.stat().st_size,
        "zip_sha256": sha256_file(zip_path),
        "pdf_count": 3,
        "reports": output_records,
    }
    Path("package_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("FINAL", json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
