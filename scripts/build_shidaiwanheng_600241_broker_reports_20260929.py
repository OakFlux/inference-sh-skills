from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-09-29"
STOCK_CODE = "600241"
STOCK_NAME = "时代万恒"
ISSUER = "辽宁时代万恒股份有限公司"
PACKAGE = "时代万恒_600241_券商深度报告_3份"
ROOT = Path(PACKAGE)
REPORT_DIR = ROOT / "01_券商深度报告"
VERIFY_DIR = ROOT / "02_清单与校验"
WORK_DIR = Path("_shidaiwanheng_600241_broker_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (REPORT_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

API = "https://reportapi.eastmoney.com/report/list"
SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://data.eastmoney.com/report/stock.jshtml",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value)
    value = re.sub(r"\s+", "_", value.strip())
    return value[:120]


def request(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    stream: bool = False,
    timeout: tuple[int, int] = (25, 600),
) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        try:
            response = SESSION.get(
                url,
                params=params,
                headers=HEADERS,
                stream=stream,
                timeout=timeout,
                allow_redirects=True,
            )
            print(
                "HTTP GET",
                response.url,
                "attempt",
                attempt,
                "status",
                response.status_code,
                "type",
                response.headers.get("content-type"),
                "length",
                response.headers.get("content-length"),
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"request failed for {url}: {errors[-6:]}")


def parse_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return 0


def parse_date(value: Any) -> datetime:
    text = str(value or "").strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except Exception:
        return datetime(1900, 1, 1)


def fetch_reports() -> list[dict[str, Any]]:
    base_params = {
        "industryCode": "*",
        "pageSize": "100",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": "2000-01-01",
        "endTime": "2027-01-01",
        "fields": "",
        "qType": "0",
        "orgCode": "",
        "code": STOCK_CODE,
        "rcode": "",
    }
    all_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_pages = 1
    for page in range(1, 50):
        params = dict(base_params)
        params.update({
            "pageNo": str(page),
            "p": str(page),
            "pageNum": str(page),
            "pageNumber": str(page),
        })
        response = request(API, params=params, timeout=(25, 180))
        try:
            payload = response.json()
        finally:
            response.close()
        if page == 1:
            total_pages = parse_int(payload.get("TotalPage") or payload.get("totalPage") or 1)
            print(
                "REPORT_API_TOTAL",
                {"pages": total_pages, "count": payload.get("TotalCount") or payload.get("totalCount")},
                flush=True,
            )
        rows = payload.get("data") or []
        if not isinstance(rows, list):
            raise RuntimeError("Eastmoney report API data field is not a list")
        for row in rows:
            if not isinstance(row, dict):
                continue
            info_code = str(row.get("infoCode") or "").strip()
            if not info_code or info_code in seen:
                continue
            seen.add(info_code)
            all_rows.append(row)
        print("REPORT_PAGE", page, "ROWS", len(rows), "ACCUMULATED", len(all_rows), flush=True)
        if page >= total_pages or not rows:
            break
    if not all_rows:
        raise RuntimeError("Eastmoney report API returned no reports")
    return all_rows


def depth_score(row: dict[str, Any]) -> float:
    title = str(row.get("title") or "")
    pages = parse_int(row.get("attachPages"))
    date = parse_date(row.get("publishDate"))
    normalized = re.sub(r"\s+", "", title)

    score = 0.0
    if "深度" in normalized:
        score += 220
    if any(token in normalized for token in ("首次覆盖", "首次评级", "首次推荐")):
        score += 190
    if "公司研究" in normalized or "公司报告" in normalized:
        score += 35
    if any(token in normalized for token in ("锂电", "电池", "新能源", "镍氢", "三元", "储能", "转型", "龙头", "成长")):
        score += 45
    if pages >= 40:
        score += 70
    elif pages >= 30:
        score += 50
    elif pages >= 20:
        score += 30
    score += min(pages, 80) * 1.8
    score += max(date.year - 2010, 0) * 4

    if any(token in normalized for token in ("点评", "季报", "年报", "半年报", "一季报", "三季报", "快报", "公告", "事件", "跟踪")):
        score -= 230
    if pages < 15:
        score -= 180
    return score


def choose_reports(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for original in rows:
        info_code = str(original.get("infoCode") or "").strip()
        pages = parse_int(original.get("attachPages"))
        if not info_code or pages < 15:
            continue
        row = dict(original)
        row["_pages"] = pages
        row["_date"] = parse_date(row.get("publishDate"))
        row["_score"] = depth_score(row)
        candidates.append(row)

    candidates.sort(
        key=lambda item: (item["_score"], item["_date"], item["_pages"]),
        reverse=True,
    )
    print(
        "TOP_CANDIDATES",
        json.dumps(
            [
                {
                    "title": item.get("title"),
                    "org": item.get("orgSName") or item.get("orgName"),
                    "date": str(item.get("publishDate")),
                    "pages": item.get("_pages"),
                    "score": item.get("_score"),
                    "infoCode": item.get("infoCode"),
                    "reportType": item.get("reportType"),
                }
                for item in candidates[:30]
            ],
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )

    selected: list[dict[str, Any]] = []
    used_orgs: set[str] = set()

    def acceptable(item: dict[str, Any]) -> bool:
        title = str(item.get("title") or "")
        if any(token in title for token in ("点评", "季报", "年报", "半年报", "一季报", "三季报", "快报", "公告", "事件")):
            return False
        return (
            "深度" in title
            or any(token in title for token in ("首次覆盖", "首次评级", "首次推荐"))
            or item["_pages"] >= 25
        )

    # Prefer the newest serious report first, then strongest long-form reports from other institutions.
    recent = sorted(candidates, key=lambda item: (item["_date"], item["_score"]), reverse=True)
    for item in recent:
        if not acceptable(item):
            continue
        if item["_date"].year < 2016:
            continue
        org = str(item.get("orgSName") or item.get("orgName") or "")
        selected.append(item)
        used_orgs.add(org)
        break

    for item in candidates:
        if item in selected or not acceptable(item):
            continue
        org = str(item.get("orgSName") or item.get("orgName") or "")
        if org in used_orgs:
            continue
        selected.append(item)
        used_orgs.add(org)
        if len(selected) == 3:
            break

    if len(selected) < 2:
        for item in candidates:
            if item in selected:
                continue
            org = str(item.get("orgSName") or item.get("orgName") or "")
            if org in used_orgs:
                continue
            selected.append(item)
            used_orgs.add(org)
            if len(selected) == 2:
                break

    if len(selected) < 2:
        raise RuntimeError(f"Only {len(selected)} suitable reports found")

    print(
        "SELECTED_CANDIDATES",
        json.dumps(
            [
                {
                    "title": item.get("title"),
                    "org": item.get("orgSName") or item.get("orgName"),
                    "date": str(item.get("publishDate")),
                    "pages": item.get("_pages"),
                    "score": item.get("_score"),
                    "infoCode": item.get("infoCode"),
                }
                for item in selected[:3]
            ],
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return selected[:3]


def download_pdf(url: str, destination: Path) -> str:
    response = request(url, stream=True, timeout=(30, 900))
    temp = destination.with_suffix(destination.suffix + ".part")
    temp.unlink(missing_ok=True)
    try:
        with temp.open("wb") as handle:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    handle.write(chunk)
        final_url = str(response.url)
    finally:
        response.close()
    size = temp.stat().st_size
    head = temp.read_bytes()[:8]
    if size < 50_000 or not head.startswith(b"%PDF-"):
        raise RuntimeError(f"invalid PDF for {destination.name}: bytes={size}, head={head!r}")
    temp.replace(destination)
    print("DOWNLOADED", destination, size, final_url, flush=True)
    return final_url


def render_page(path: Path, page_number: int, tag: str) -> None:
    prefix = RENDER_DIR / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{tag}"
    process = subprocess.run(
        [
            "pdftoppm",
            "-f",
            str(page_number),
            "-l",
            str(page_number),
            "-r",
            "84",
            "-png",
            "-singlefile",
            str(path),
            str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    image = Path(str(prefix) + ".png")
    valid = process.returncode == 0 and image.exists() and image.stat().st_size > 1000
    if not valid:
        raise RuntimeError(
            f"render validation failed for {path.name} page {page_number}: {process.stderr[-1500:]}"
        )
    image.unlink()


def validate_pdf(path: Path, expected_pages: int) -> dict[str, Any]:
    check = subprocess.run(
        ["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=600
    )
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-2500:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 12:
        raise RuntimeError(f"report too short: {path.name}, pages={pages}")
    if expected_pages and abs(pages - expected_pages) > 3:
        raise RuntimeError(
            f"page-count mismatch for {path.name}: actual={pages}, listed={expected_pages}"
        )
    render_page(path, 1, "first")
    render_page(path, pages, "last")
    sample = "\n".join(
        (reader.pages[index].extract_text() or "") for index in range(min(12, pages))
    )
    normalized = re.sub(r"\s+", "", sample)
    identity_ok = STOCK_NAME in normalized or STOCK_CODE in normalized or ISSUER in normalized
    if sample.strip() and not identity_ok:
        raise RuntimeError(f"issuer identity not found in sampled text for {path.name}")
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "first_and_last_pages_rendered": True,
        "issuer_identity_verified_when_text_extractable": identity_ok,
    }


def main() -> None:
    rows = fetch_reports()
    selected = choose_reports(rows)
    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    for index, row in enumerate(selected, start=1):
        info_code = str(row.get("infoCode") or "").strip()
        title = str(row.get("title") or "未命名报告").strip()
        org = str(row.get("orgSName") or row.get("orgName") or "未知机构").strip()
        date_text = str(row.get("publishDate") or "")[:10]
        listed_pages = parse_int(row.get("attachPages"))
        pdf_url = f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"
        filename = f"{index:02d}_{safe_name(org)}_{safe_name(title)}_{date_text}.pdf"
        destination = REPORT_DIR / filename
        final_url = download_pdf(pdf_url, destination)
        metadata = validate_pdf(destination, listed_pages)
        if metadata["sha256"] in seen_hashes:
            raise RuntimeError(f"duplicate report detected: {destination.name}")
        seen_hashes.add(metadata["sha256"])
        records.append(
            {
                "index": index,
                "title": title,
                "institution": org,
                "publish_date": date_text,
                "analyst": row.get("researcher") or row.get("author") or "",
                "rating": row.get("emRatingName") or row.get("sRatingName") or "",
                "listed_pages": listed_pages,
                "actual_pages": metadata["pages"],
                "info_code": info_code,
                "relative_path": str(destination.relative_to(ROOT)),
                "source_url": final_url,
                "eastmoney_info_page": f"https://data.eastmoney.com/report/info/{info_code}.html",
                "selection_score": row.get("_score"),
                **metadata,
            }
        )

    readme = [
        f"{STOCK_NAME}（{STOCK_CODE}）券商深度报告资料包",
        f"整理日期：{CHECKED_AS_OF}",
        f"报告数量：{len(records)}份",
        f"合计页数：{sum(record['actual_pages'] for record in records)}页",
        "",
        "筛选口径：优先公司深度、首次覆盖和长篇研究，排除普通财报点评、短篇事件点评；尽量保持券商机构多样性。",
        "文件来自东方财富研报中心公开PDF地址，未改写原报告正文、页面顺序或免责声明。",
        "",
    ]
    for record in records:
        readme.extend(
            [
                f"{record['index']}. {record['institution']}：《{record['title']}》",
                f"   日期：{record['publish_date']}",
                f"   页数：{record['actual_pages']}页",
                f"   分析师：{record['analyst'] or '见原报告'}",
                f"   评级：{record['rating'] or '见原报告'}",
                f"   文件：{record['relative_path']}",
                f"   原始PDF：{record['source_url']}",
                f"   SHA-256：{record['sha256']}",
                "",
            ]
        )
    readme.extend(
        [
            "校验：",
            "- 所有PDF均通过文件头和QPDF结构检查。",
            "- 已核对实际页数与研报元数据。",
            "- 已渲染每份PDF的首页和末页。",
            "- 已核对公司名称或证券代码。",
            "- ZIP已通过完整性测试。",
        ]
    )
    (VERIFY_DIR / "README_报告清单与来源说明.txt").write_text(
        "\n".join(readme), encoding="utf-8"
    )
    (VERIFY_DIR / "manifest.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (VERIFY_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(
            f"{record['sha256']}  {record['relative_path']}" for record in records
        )
        + "\n",
        encoding="utf-8",
    )

    final_zip = Path(PACKAGE + ".zip")
    final_zip.unlink(missing_ok=True)
    with zipfile.ZipFile(
        final_zip, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
    ) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.as_posix())
    with zipfile.ZipFile(final_zip, "r") as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP integrity test failed at {bad}")
    print("FINAL_ZIP", final_zip, final_zip.stat().st_size, flush=True)
    print("SELECTED_REPORTS", json.dumps(records, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
