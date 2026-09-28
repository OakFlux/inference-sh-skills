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

CHECKED_AS_OF = "2026-09-28"
COMPANY = "珂玛科技"
STOCK_CODE = "301611"
PACKAGE = "珂玛科技_301611_券商深度报告_3份"
ROOT = Path(PACKAGE)
REPORT_DIR = ROOT / "01_券商深度报告"
VERIFY_DIR = ROOT / "02_说明与校验"
WORK_DIR = Path("_kema_301611_broker_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (REPORT_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(text: str, limit: int = 72) -> str:
    text = re.sub(r"[\\/:*?\"<>|]", "_", text)
    text = re.sub(r"\s+", "", text)
    return text[:limit].strip("._")


def request(url: str, *, params: dict[str, str] | None = None, stream: bool = False,
            referer: str | None = None, timeout: tuple[int, int] = (20, 360)) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        headers = dict(HEADERS)
        if referer:
            headers["Referer"] = referer
        try:
            response = SESSION.get(
                url, params=params, headers=headers, timeout=timeout,
                stream=stream, allow_redirects=True,
            )
            print(
                "HTTP", response.url, "attempt", attempt,
                "status", response.status_code,
                "type", response.headers.get("content-type"),
                "length", response.headers.get("content-length"),
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(attempt * 2, 10))
    raise RuntimeError(f"request failed for {url}: {errors[-6:]}")


def fetch_report_records() -> list[dict[str, Any]]:
    params = {
        "cb": "datatable",
        "qType": "0",
        "orgCode": "",
        "author": "",
        "p": "1",
        "pageNo": "1",
        "pageNum": "1",
        "pageSize": "500",
        "code": STOCK_CODE,
        "industryCode": "",
        "industry": "",
        "rating": "",
        "ratingChange": "",
        "beginTime": "2024-01-01",
        "endTime": CHECKED_AS_OF,
        "fields": "",
    }
    response = request(
        "https://reportapi.eastmoney.com/report/list",
        params=params,
        referer=f"https://data.eastmoney.com/report/{STOCK_CODE}.html",
        timeout=(20, 120),
    )
    try:
        text = response.text.strip()
    finally:
        response.close()
    if text.startswith("datatable(") and text.endswith(")"):
        text = text[len("datatable("):-1]
    payload = json.loads(text)
    records = payload.get("data") or []
    print("REPORT_COUNT", len(records), flush=True)
    normalized: list[dict[str, Any]] = []
    for item in records:
        record = {
            "title": str(item.get("title") or "").strip(),
            "stock_name": str(item.get("stockName") or "").strip(),
            "stock_code": str(item.get("stockCode") or "").strip(),
            "broker": str(item.get("orgSName") or item.get("orgName") or "").strip(),
            "broker_full": str(item.get("orgName") or "").strip(),
            "publish_date": str(item.get("publishDate") or "").split(" ")[0],
            "info_code": str(item.get("infoCode") or "").strip(),
            "rating": str(item.get("emRatingName") or "").strip(),
            "researcher": str(item.get("researcher") or "").strip(),
            "report_type": item.get("reportType"),
        }
        if record["info_code"]:
            normalized.append(record)
            print("REPORT", json.dumps(record, ensure_ascii=False), flush=True)
    return normalized


def candidate_score(record: dict[str, Any]) -> tuple[int, str]:
    title = record["title"]
    score = 0
    if "首次覆盖" in title:
        score += 120
    if "深度" in title or "公司深度" in title:
        score += 100
    if any(keyword in title for keyword in (
        "先进陶瓷", "陶瓷加热器", "静电卡盘", "半导体", "核心零部件",
        "国产化", "国产替代", "龙头", "成长逻辑",
    )):
        score += 35
    if any(keyword in title for keyword in (
        "点评", "一季报", "半年报", "三季报", "年报", "业绩预告", "跟踪",
    )):
        score -= 70
    if record["broker"] in {"华西证券", "国元证券", "华金证券", "中信建投", "国金证券", "民生证券", "东吴证券"}:
        score += 15
    return score, record["publish_date"]


def ranked_candidates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered = []
    for record in records:
        if record["stock_code"] and record["stock_code"] != STOCK_CODE:
            continue
        if any(keyword in record["title"] for keyword in ("行业周报", "行业点评", "业绩预告")):
            continue
        score, _ = candidate_score(record)
        if score < 45:
            continue
        item = dict(record)
        item["score"] = score
        filtered.append(item)
    filtered.sort(key=lambda row: (row["score"], row["publish_date"]), reverse=True)
    print("RANKED", json.dumps(filtered, ensure_ascii=False, indent=2), flush=True)
    return filtered


def download_candidate(record: dict[str, Any], destination: Path) -> tuple[str, list[str]]:
    info_code = record["info_code"]
    urls = [
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}.pdf",
        f"https://pdf.dfcfw.com/pdf/H2_{info_code}_1.pdf",
    ]
    errors: list[str] = []
    for url in urls:
        temp = destination.with_suffix(destination.suffix + ".part")
        temp.unlink(missing_ok=True)
        try:
            response = request(
                url, stream=True,
                referer=f"https://data.eastmoney.com/report/info/{info_code}.html",
                timeout=(25, 420),
            )
            try:
                with temp.open("wb") as fh:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            fh.write(chunk)
                final_url = str(response.url)
            finally:
                response.close()
            size = temp.stat().st_size
            head = temp.read_bytes()[:8]
            if size < 120_000 or not head.startswith(b"%PDF-"):
                raise RuntimeError(f"not a valid report PDF: size={size}, head={head!r}")
            temp.replace(destination)
            print("DOWNLOADED", destination, size, final_url, flush=True)
            return final_url, errors
        except Exception as exc:  # noqa: BLE001
            temp.unlink(missing_ok=True)
            message = f"{url} | {exc!r}"
            errors.append(message)
            print("CANDIDATE_DOWNLOAD_FAILED", message, flush=True)
    raise RuntimeError(f"all PDF URLs failed for {info_code}: {errors}")


def render_page(path: Path, page_number: int, suffix: str) -> None:
    prefix = RENDER_DIR / f"{path.stem}_{suffix}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
            "-r", "84", "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=240,
    )
    png = Path(str(prefix) + ".png")
    valid = (
        process.returncode == 0 and png.exists() and png.stat().st_size > 1000
        and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(
            f"render validation failed for {path.name} page {page_number}: "
            f"return={process.returncode}, stderr={process.stderr[-1500:]}"
        )
    png.unlink()


def validate_report(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-2000:]}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 12:
        raise RuntimeError(f"report is too short for deep/coverage use: {pages} pages")

    render_page(path, 1, "first")
    render_page(path, pages, "last")

    sample_indices = list(range(min(8, pages)))
    if pages > 8:
        sample_indices.append(pages - 1)
    text = "\n".join((reader.pages[index].extract_text() or "") for index in sample_indices)
    normalized = re.sub(r"\s+", "", text)
    company_ok = COMPANY in normalized or STOCK_CODE in normalized
    broker_ok = record["broker"] in normalized or record["broker_full"] in normalized
    deep_ok = any(marker in normalized for marker in (
        "首次覆盖", "公司深度", "深度研究", "投资要点", "核心观点", "投资评级",
    ))
    if text.strip() and not company_ok:
        raise RuntimeError(f"company identity missing in {path.name}")
    if text.strip() and not broker_ok:
        raise RuntimeError(f"broker identity missing in {path.name}")
    if text.strip() and not deep_ok:
        raise RuntimeError(f"deep/coverage marker missing in {path.name}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "render_verified_first_and_last_page": True,
        "company_identity_verified_when_text_extractable": company_ok,
        "broker_identity_verified_when_text_extractable": broker_ok,
        "deep_report_marker_verified_when_text_extractable": deep_ok,
        "sample_text_extractable": bool(text.strip()),
    }


records = fetch_report_records()
candidates = ranked_candidates(records)
if not candidates:
    raise RuntimeError("No deep/first-coverage candidate reports found")

selected: list[dict[str, Any]] = []
used_brokers: set[str] = set()
used_hashes: set[str] = set()
errors: list[str] = []

for record in candidates:
    if len(selected) >= 3:
        break
    if record["broker"] in used_brokers:
        continue
    filename = (
        f"{record['publish_date'].replace('-', '')}_{safe_name(record['broker'], 18)}_"
        f"{safe_name(record['title'], 64)}.pdf"
    )
    destination = REPORT_DIR / filename
    try:
        final_url, failed_urls = download_candidate(record, destination)
        validation = validate_report(destination, record)
        if validation["sha256"] in used_hashes:
            destination.unlink(missing_ok=True)
            continue
        used_hashes.add(validation["sha256"])
        used_brokers.add(record["broker"])
        selected_record = {
            "date": record["publish_date"],
            "broker": record["broker"],
            "broker_full": record["broker_full"],
            "title": record["title"],
            "stock_code": STOCK_CODE,
            "rating": record["rating"],
            "researcher": record["researcher"],
            "info_code": record["info_code"],
            "relative_path": str(destination.relative_to(ROOT)),
            "source": "东方财富研报原文PDF镜像",
            "report_page_url": f"https://data.eastmoney.com/report/info/{record['info_code']}.html",
            "source_url": final_url,
            "failed_download_candidates_before_success": failed_urls,
            **validation,
        }
        selected.append(selected_record)
        print("SELECTED", json.dumps(selected_record, ensure_ascii=False), flush=True)
    except Exception as exc:  # noqa: BLE001
        destination.unlink(missing_ok=True)
        message = f"{record['broker']} | {record['title']} | {record['info_code']} | {exc!r}"
        errors.append(message)
        print("REJECTED", message, flush=True)

if len(selected) < 2:
    raise RuntimeError(f"Only {len(selected)} validated deep reports available; errors={errors}")

manifest = {
    "package_name": PACKAGE,
    "company": COMPANY,
    "stock_code": STOCK_CODE,
    "checked_as_of": CHECKED_AS_OF,
    "selection_principles": [
        "优先选择首次覆盖、公司深度或明确围绕公司核心业务展开的长篇报告。",
        "优先选择不同券商，避免内容重复。",
        "排除财报点评、业绩预告点评、行业周报及短篇网页摘要。",
        "每份PDF须不少于12页，并通过公司、券商及深度/覆盖标识核验。",
    ],
    "report_count": len(selected),
    "records": selected,
    "rejected_candidates": errors,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as fh:
    writer = csv.writer(fh)
    writer.writerow([
        "文件", "发布日期", "券商", "标题", "页数", "字节数", "评级", "研究员",
        "InfoCode", "SHA-256", "报告页面", "PDF来源网址",
    ])
    for record in selected:
        writer.writerow([
            record["relative_path"], record["date"], record["broker"], record["title"],
            record["pages"], record["bytes"], record["rating"], record["researcher"],
            record["info_code"], record["sha256"], record["report_page_url"], record["source_url"],
        ])

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as fh:
    for record in selected:
        fh.write(f"{record['sha256']}  {record['relative_path']}\n")

report_lines = []
for index, record in enumerate(selected, 1):
    report_lines.append(
        f"{index}. {record['date']} | {record['broker']} | {record['title']} | "
        f"{record['pages']}页 | {record['info_code']}"
    )
readme = f"""{COMPANY}（{STOCK_CODE}）券商深度报告文件包

核对日期：{CHECKED_AS_OF}

本包收录{len(selected)}份完整PDF：
""" + "\n".join(report_lines) + """

筛选口径：
- 首选首次覆盖、公司深度、核心业务专题等完整报告；
- 排除财报点评、业绩预告点评、行业周报、网页摘要及过短文件；
- 尽量选择不同券商，以减少观点和模型重复。

校验项目：
- PDF文件头与文件大小；
- qpdf结构检查；
- 页数检查（不少于12页）；
- 公司名称或证券代码核验；
- 券商署名核验；
- 首次覆盖/深度研究/核心观点等标识核验；
- 首尾页实际渲染检查；
- SHA-256去重及ZIP完整性测试。

来源：东方财富研报原文PDF镜像。详细页面及PDF地址见《文件清单.csv》和manifest.json。
"""
(VERIFY_DIR / "README.txt").write_text(readme, encoding="utf-8")

zip_path = Path(PACKAGE + ".zip")
zip_path.unlink(missing_ok=True)
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, path.as_posix())

with zipfile.ZipFile(zip_path, "r") as archive:
    bad_member = archive.testzip()
    if bad_member:
        raise RuntimeError(f"ZIP integrity test failed at {bad_member}")
    pdf_count = sum(1 for name in archive.namelist() if name.lower().endswith(".pdf"))
    if pdf_count != len(selected):
        raise RuntimeError(f"ZIP PDF count mismatch: expected {len(selected)}, got {pdf_count}")

print("FINAL_ZIP", zip_path, "bytes", zip_path.stat().st_size, "sha256", sha256(zip_path), flush=True)
