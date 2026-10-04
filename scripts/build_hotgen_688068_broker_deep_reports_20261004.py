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

CHECK_DATE = "2026-10-04"
COMPANY = "热景生物"
CODE = "688068"
PACKAGE_NAME = f"热景生物_{CODE}_券商深度报告_3份_截至{CHECK_DATE}"
ROOT = Path(PACKAGE_NAME)
REPORT_DIR = ROOT / "01_券商深度报告"
META_DIR = ROOT / "02_来源与校验"
WORK_DIR = Path("_hotgen_688068_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (REPORT_DIR, META_DIR, WORK_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://data.eastmoney.com/report/stock.jshtml?encodeUrl=",
})

TARGETS = [
    {
        "order": 1,
        "title_key": "全球首创心梗单抗，FIC潜力催化价值重估",
        "institution_key": "银河",
        "expected_date_prefix": "2026-08",
        "output_name": "01_中国银河证券_公司深度_全球首创心梗单抗_FIC潜力催化价值重估.pdf",
        "kind": "公司深度/首次覆盖",
    },
    {
        "order": 2,
        "title_key": "特色IVD与创新药双轮驱动，SGC001市场潜力大",
        "institution_key": "开源",
        "expected_date_prefix": "2025-07",
        "output_name": "02_开源证券_公司首次覆盖_特色IVD与创新药双轮驱动_SGC001市场潜力大.pdf",
        "kind": "公司首次覆盖",
    },
    {
        "order": 3,
        "title_key": "深耕IVD检测市场，战略性布局创新药产业",
        "institution_key": "中邮",
        "expected_date_prefix": "2024-12",
        "output_name": "03_中邮证券_公司首次覆盖_深耕IVD检测市场_战略性布局创新药产业.pdf",
        "kind": "公司首次覆盖",
    },
]


def norm(value: Any) -> str:
    return re.sub(r"[\s：:—–-]+", "", str(value or "")).lower()


def request(method: str, url: str, *, timeout: tuple[int, int] = (20, 180), **kwargs: Any) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 11):
        try:
            response = SESSION.request(method, url, timeout=timeout, allow_redirects=True, **kwargs)
            print(
                "HTTP", method, url, "attempt", attempt, "status", response.status_code,
                "type", response.headers.get("content-type"),
                "length", response.headers.get("content-length"),
                "final", response.url,
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            time.sleep(min(attempt * 2, 15))
    raise RuntimeError(f"request failed for {method} {url}: {errors[-10:]}")


def flatten(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from flatten(child)
    elif isinstance(value, list):
        for child in value:
            yield from flatten(child)


def fetch_report_rows() -> list[dict[str, Any]]:
    endpoint = "https://reportapi.eastmoney.com/report/list2"
    bodies = [
        {
            "pageSize": 200,
            "pageNo": 1,
            "p": 1,
            "pageNum": 1,
            "pageNumber": 1,
            "beginTime": "2024-01-01",
            "endTime": CHECK_DATE,
            "code": CODE,
            "industryCode": "*",
            "rating": None,
            "ratingChange": None,
            "orgCode": None,
            "rcode": "",
        },
        {
            "pageSize": 200,
            "pageNo": 1,
            "beginTime": "2024-01-01",
            "endTime": CHECK_DATE,
            "code": CODE,
            "industryCode": "*",
            "rating": "",
            "ratingChange": "",
            "orgCode": "",
            "rcode": "",
        },
    ]
    last_payload: Any = None
    for body in bodies:
        for mode in ("json", "form"):
            kwargs: dict[str, Any]
            if mode == "json":
                kwargs = {"json": body, "headers": {"Content-Type": "application/json"}}
            else:
                kwargs = {"data": body, "headers": {"Content-Type": "application/x-www-form-urlencoded"}}
            try:
                response = request("POST", endpoint, timeout=(20, 120), **kwargs)
            except Exception as exc:  # noqa: BLE001
                print("LIST2_ATTEMPT_ERROR", mode, repr(exc), flush=True)
                continue
            try:
                text = response.text.strip()
                print("LIST2_RAW_PREFIX", text[:1000], flush=True)
                if text.startswith("datatable(") and text.endswith(")"):
                    text = text[len("datatable("):-1]
                payload = json.loads(text)
                last_payload = payload
            except Exception as exc:  # noqa: BLE001
                print("LIST2_PARSE_ERROR", repr(exc), flush=True)
                response.close()
                continue
            finally:
                response.close()
            rows: list[dict[str, Any]] = []
            for item in flatten(payload):
                title = str(item.get("title") or item.get("Title") or "")
                code = str(item.get("stockCode") or item.get("stock_code") or item.get("code") or "")
                info_code = str(item.get("infoCode") or item.get("info_code") or item.get("encodeUrl") or "")
                if title and info_code and (not code or CODE in code or COMPANY in str(item)):
                    rows.append(dict(item))
            if rows:
                unique: dict[str, dict[str, Any]] = {}
                for row in rows:
                    key = str(row.get("infoCode") or row.get("encodeUrl"))
                    unique[key] = row
                result = list(unique.values())
                print("REPORT_ROWS", json.dumps(result, ensure_ascii=False, indent=2), flush=True)
                return result
    raise RuntimeError(f"No report rows returned. Last payload: {json.dumps(last_payload, ensure_ascii=False)[:3000]}")


def row_value(row: dict[str, Any], *keys: str) -> str:
    lowered = {str(k).lower(): v for k, v in row.items()}
    for key in keys:
        value = row.get(key)
        if value is None:
            value = lowered.get(key.lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def match_target(rows: list[dict[str, Any]], target: dict[str, Any]) -> dict[str, Any]:
    title_key = norm(target["title_key"])
    inst_key = norm(target["institution_key"])
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        title = row_value(row, "title", "reportTitle")
        institution = row_value(row, "orgSName", "orgName", "institution")
        date = row_value(row, "publishDate", "publish_date", "date")
        stock_name = row_value(row, "stockName", "stock_name")
        text = norm(title)
        score = 0
        if title_key in text:
            score += 1000
        else:
            # tolerate punctuation and subtitle differences
            tokens = [token for token in re.split(r"[,，。;；]+", target["title_key"]) if len(token) >= 4]
            score += sum(120 for token in tokens if norm(token) in text)
        if inst_key and inst_key in norm(institution):
            score += 200
        if str(date).startswith(target["expected_date_prefix"]):
            score += 100
        if COMPANY in stock_name or CODE in row_value(row, "stockCode", "code"):
            score += 50
        if score:
            scored.append((score, row))
    if not scored:
        raise RuntimeError(f"No row matched target: {target['title_key']}")
    scored.sort(key=lambda pair: pair[0], reverse=True)
    best_score, best = scored[0]
    print("TARGET_MATCH", target["title_key"], best_score, json.dumps(best, ensure_ascii=False, indent=2), flush=True)
    if best_score < 500:
        raise RuntimeError(f"Weak report match for {target['title_key']}: score={best_score}")
    return best


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_pdf(info_code: str, output: Path) -> str:
    candidates = [
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H2_{info_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/{info_code}.pdf",
    ]
    for url in candidates:
        temp = output.with_suffix(output.suffix + ".part")
        temp.unlink(missing_ok=True)
        try:
            response = request("GET", url, timeout=(30, 600), stream=True, headers={"Referer": "https://data.eastmoney.com/"})
        except Exception as exc:  # noqa: BLE001
            print("PDF_CANDIDATE_ERROR", url, repr(exc), flush=True)
            continue
        try:
            with temp.open("wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        handle.write(chunk)
            final_url = str(response.url)
        finally:
            response.close()
        head = temp.read_bytes()[:8] if temp.exists() else b""
        if temp.exists() and temp.stat().st_size > 30_000 and head.startswith(b"%PDF-"):
            temp.replace(output)
            print("PDF_DOWNLOADED", output, output.stat().st_size, final_url, flush=True)
            return final_url
        print("PDF_INVALID", url, temp.stat().st_size if temp.exists() else 0, head, flush=True)
        temp.unlink(missing_ok=True)
    raise RuntimeError(f"Unable to download PDF for {info_code}")


def render_page(path: Path, page_number: int, tag: str) -> None:
    prefix = RENDER_DIR / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{tag}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number), "-r", "90",
            "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    image = Path(str(prefix) + ".png")
    if process.returncode != 0 or not image.exists() or image.stat().st_size < 1000:
        raise RuntimeError(f"Render failed for {path.name} page {page_number}: {process.stderr[-1200:]}")
    image.unlink()


def validate_pdf(path: Path, expected_title: str) -> dict[str, Any]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=600)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {check.stderr[-2000:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 3:
        raise RuntimeError(f"Unexpectedly short report: {path.name}, {pages} pages")
    sample_indices = list(range(min(5, pages)))
    sample_text = "\n".join((reader.pages[i].extract_text() or "") for i in sample_indices)
    normalized = norm(sample_text)
    if COMPANY not in sample_text and CODE not in sample_text and "热景" not in sample_text:
        raise RuntimeError(f"Issuer identity not found in {path.name}")
    title_tokens = [token for token in re.split(r"[,，。;；]+", expected_title) if len(token) >= 4]
    title_match_count = sum(1 for token in title_tokens if norm(token) in normalized)
    render_page(path, 1, "first")
    if pages > 1:
        render_page(path, pages, "last")
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "first_and_last_pages_rendered": True,
        "issuer_identity_verified": True,
        "title_token_matches": title_match_count,
    }


def main() -> None:
    rows = fetch_report_rows()
    selected: list[dict[str, Any]] = []
    used_codes: set[str] = set()
    for target in TARGETS:
        row = match_target(rows, target)
        info_code = row_value(row, "infoCode", "info_code", "encodeUrl")
        if not info_code:
            raise RuntimeError(f"Missing infoCode for {target['title_key']}")
        if info_code in used_codes:
            raise RuntimeError(f"Duplicate report selected: {info_code}")
        used_codes.add(info_code)
        output = REPORT_DIR / target["output_name"]
        source_pdf_url = download_pdf(info_code, output)
        validation = validate_pdf(output, target["title_key"])
        record = {
            "order": target["order"],
            "kind": target["kind"],
            "title": row_value(row, "title", "reportTitle") or target["title_key"],
            "institution": row_value(row, "orgSName", "orgName") or target["institution_key"],
            "analysts": row_value(row, "researcher", "researcherName", "author"),
            "publish_date": row_value(row, "publishDate", "publish_date"),
            "rating": row_value(row, "ratingName", "rating"),
            "info_code": info_code,
            "stock_code": row_value(row, "stockCode", "code") or CODE,
            "stock_name": row_value(row, "stockName") or COMPANY,
            "eastmoney_detail_url": f"https://data.eastmoney.com/report/info/{info_code}.html",
            "source_pdf_url": source_pdf_url,
            "relative_path": output.relative_to(ROOT).as_posix(),
            **validation,
        }
        selected.append(record)

    selected.sort(key=lambda item: item["order"])
    readme = [
        f"{COMPANY}（{CODE}.SH）券商深度研究报告资料包",
        f"核对日期：{CHECK_DATE}",
        "",
        "本资料包优先选择真正的公司深度或首次覆盖报告，均为公开渠道取得的券商原始PDF。",
        "报告仅供研究参考，不构成投资建议。",
        "",
        "收录文件：",
    ]
    for idx, record in enumerate(selected, 1):
        readme.extend([
            f"{idx}. {record['institution']}：《{record['title']}》",
            f"   类型：{record['kind']}",
            f"   日期：{record['publish_date']}",
            f"   分析师：{record['analysts'] or '公开元数据未列明'}",
            f"   评级：{record['rating'] or '公开元数据未列明'}",
            f"   页数：{record['pages']}",
            f"   文件：{record['relative_path']}",
            f"   PDF来源：{record['source_pdf_url']}",
            f"   研报页面：{record['eastmoney_detail_url']}",
            f"   SHA-256：{record['sha256']}",
            "",
        ])
    readme.extend([
        "校验说明：",
        "- 每份文件检查PDF文件头、QPDF结构、实际页数及公司名称/证券代码。",
        "- 每份文件均渲染首页与末页验证可读性。",
        "- ZIP生成后执行完整性测试。",
    ])
    (META_DIR / "README_文件清单与来源说明.txt").write_text("\n".join(readme), encoding="utf-8")
    (META_DIR / "manifest.json").write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")
    with (META_DIR / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(selected[0].keys()))
        writer.writeheader()
        writer.writerows(selected)
    (META_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{item['sha256']}  {item['relative_path']}" for item in selected) + "\n",
        encoding="utf-8",
    )

    zip_path = Path(PACKAGE_NAME + ".zip")
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.as_posix())
    with zipfile.ZipFile(zip_path, "r") as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP integrity failure: {bad}")
    print("FINAL_ZIP", zip_path, zip_path.stat().st_size, flush=True)
    print("FINAL_MANIFEST", json.dumps(selected, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
