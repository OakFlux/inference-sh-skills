from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from pypdf import PdfReader

COMPANY_SHORT = "国货航"
COMPANY_FULL = "中国国际货运航空股份有限公司"
COMPANY_EN = "Air China Cargo Co., Ltd."
STOCK_CODE = "001391"
AS_OF_DATE = "2026-09-27"
PACKAGE_STEM = "国货航_001391_所有年报_招股说明书及最新季报"
ROOT = Path(PACKAGE_STEM)
ANNUAL_DIR = ROOT / "01_年度报告"
PROSPECTUS_DIR = ROOT / "02_招股说明书"
QUARTER_DIR = ROOT / "03_最新季报"
INTERIM_DIR = ROOT / "04_最新半年度报告_补充"
NOTES_DIR = ROOT / "05_资料说明"
PREVIEW_DIR = Path("_previews_air_china_cargo_filings")
RESULT_JSON = Path("air_china_cargo_filings_result.json")
ZIP_PATH = Path(f"{PACKAGE_STEM}.zip")

COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Referer": "https://www.cninfo.com.cn/",
    "Origin": "https://www.cninfo.com.cn",
}


def compact(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize(value: str) -> str:
    return "".join(ch for ch in compact(value).upper() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def request_json(
    client: httpx.Client,
    url: str,
    *,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    label: str,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = client.post(url, data=data, params=params, timeout=120)
            print(
                "HTTP_JSON",
                json.dumps(
                    {
                        "label": label,
                        "attempt": attempt,
                        "status": response.status_code,
                        "bytes": len(response.content),
                        "url": str(response.url),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            excerpt = ""
            try:
                excerpt = response.text[:500]  # type: ignore[possibly-undefined]
            except Exception:
                pass
            print("JSON_RETRY", label, attempt, repr(exc), excerpt, flush=True)
            time.sleep(attempt * 3)
    raise RuntimeError(f"Failed JSON request {label}: {last_error!r}")


def recursive_dicts(value: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    if isinstance(value, dict):
        output.append(value)
        for child in value.values():
            output.extend(recursive_dicts(child))
    elif isinstance(value, list):
        for child in value:
            output.extend(recursive_dicts(child))
    return output


def discover_org_id(client: httpx.Client) -> str:
    for keyword in (STOCK_CODE, COMPANY_SHORT, COMPANY_FULL):
        payload = request_json(
            client,
            "https://www.cninfo.com.cn/new/information/topSearch/query",
            data={"keyWord": keyword, "maxNum": "30"},
            label=f"topSearch:{keyword}",
        )
        for item in recursive_dicts(payload):
            code = compact(str(item.get("code") or item.get("secCode") or item.get("stockCode") or ""))
            org_id = compact(str(item.get("orgId") or item.get("orgid") or ""))
            name = compact(str(item.get("zwjc") or item.get("secName") or item.get("name") or ""))
            if code == STOCK_CODE and org_id:
                print("ORG_MATCH", json.dumps({"keyword": keyword, "code": code, "name": name, "orgId": org_id}, ensure_ascii=False), flush=True)
                return org_id

    fallback = client.get(
        "https://www.cninfo.com.cn/new/data/szse_stock.json",
        headers={**COMMON_HEADERS, "Accept": "application/json,text/plain,*/*"},
        timeout=120,
    )
    print("STOCK_LIST", fallback.status_code, len(fallback.content), str(fallback.url), flush=True)
    fallback.raise_for_status()
    payload = fallback.json()
    for item in recursive_dicts(payload):
        code = compact(str(item.get("code") or item.get("secCode") or item.get("stockCode") or ""))
        org_id = compact(str(item.get("orgId") or item.get("orgid") or ""))
        if code == STOCK_CODE and org_id:
            print("ORG_MATCH_FALLBACK", json.dumps(item, ensure_ascii=False), flush=True)
            return org_id
    raise RuntimeError(f"Unable to discover CNINFO orgId for {STOCK_CODE}")


def query_announcements(client: httpx.Client, org_id: str) -> list[dict[str, Any]]:
    all_items: list[dict[str, Any]] = []
    page_size = 50
    for page in range(1, 41):
        data = {
            "pageNum": str(page),
            "pageSize": str(page_size),
            "column": "szse",
            "tabName": "fulltext",
            "plate": "sz",
            "stock": f"{STOCK_CODE},{org_id}",
            "searchkey": "",
            "secid": "",
            "category": "",
            "trade": "",
            "seDate": f"2018-01-01~{AS_OF_DATE}",
            "sortName": "time",
            "sortType": "desc",
            "isHLtitle": "true",
        }
        payload = request_json(
            client,
            "https://www.cninfo.com.cn/new/hisAnnouncement/query",
            data=data,
            label=f"hisAnnouncement:p{page}",
        )
        announcements = payload.get("announcements") if isinstance(payload, dict) else None
        if not announcements:
            print("ANNOUNCEMENT_PAGE_EMPTY", page, json.dumps(payload, ensure_ascii=False)[:1200], flush=True)
            break
        for item in announcements:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            item["clean_title"] = compact(str(item.get("announcementTitle") or ""))
            item["official_url"] = urljoin("https://static.cninfo.com.cn/", str(item.get("adjunctUrl") or ""))
            all_items.append(item)
        total_pages = 0
        try:
            total_pages = int(payload.get("totalpages") or payload.get("totalPages") or 0)
        except Exception:
            total_pages = 0
        print("ANNOUNCEMENT_PAGE", page, len(announcements), "TOTAL_PAGES", total_pages, flush=True)
        if (total_pages and page >= total_pages) or len(announcements) < page_size:
            break

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in sorted(all_items, key=lambda x: int(x.get("announcementTime") or 0), reverse=True):
        key = str(item.get("announcementId") or item.get("adjunctUrl") or item.get("clean_title") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    print("ANNOUNCEMENT_TOTAL", len(deduped), flush=True)
    for item in deduped:
        title = item.get("clean_title", "")
        if any(token in title for token in ("年度报告", "季度报告", "半年度报告", "招股说明书")):
            print("CANDIDATE", json.dumps({"title": title, "time": item.get("announcementTime"), "url": item.get("official_url")}, ensure_ascii=False), flush=True)
    return deduped


def announcement_timestamp(item: dict[str, Any]) -> int:
    try:
        return int(item.get("announcementTime") or 0)
    except Exception:
        return 0


def publication_date(item: dict[str, Any]) -> str:
    stamp = announcement_timestamp(item)
    if stamp:
        return datetime.fromtimestamp(stamp / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    match = re.search(r"/(20\d{2})-(\d{2})-(\d{2})/", str(item.get("official_url") or ""))
    if match:
        return "-".join(match.groups())
    return ""


def is_full_report_title(title: str) -> bool:
    bad = ("摘要", "英文版", "取消", "提示性公告", "董事会", "监事会", "审计报告", "意见", "说明")
    return not any(token in title for token in bad)


def select_documents(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annual_by_year: dict[int, dict[str, Any]] = {}
    prospectus_candidates: list[dict[str, Any]] = []
    quarter_candidates: list[dict[str, Any]] = []
    interim_candidates: list[dict[str, Any]] = []

    for item in items:
        title = compact(str(item.get("clean_title") or item.get("announcementTitle") or ""))
        if not title or not str(item.get("adjunctUrl") or "").lower().endswith(".pdf"):
            continue

        annual_match = re.search(r"(20\d{2})年年度报告", title)
        if annual_match and is_full_report_title(title):
            year = int(annual_match.group(1))
            current = annual_by_year.get(year)
            if current is None or announcement_timestamp(item) > announcement_timestamp(current):
                annual_by_year[year] = item

        if "招股说明书" in title and not any(
            token in title
            for token in (
                "摘要",
                "提示性公告",
                "关于",
                "回复",
                "问询",
                "法律意见书",
                "保荐",
                "核查",
                "差异情况说明",
                "财务报表",
                "审计报告",
            )
        ):
            prospectus_candidates.append(item)

        if re.search(r"20\d{2}年(?:第一|第三)季度报告", title) and is_full_report_title(title):
            quarter_candidates.append(item)

        if re.search(r"20\d{2}年半年度报告", title) and is_full_report_title(title):
            interim_candidates.append(item)

    if not annual_by_year:
        raise RuntimeError("No full annual reports found")

    annual_years = sorted(annual_by_year)
    print("ANNUAL_YEARS_FOUND", annual_years, flush=True)

    def prospectus_score(item: dict[str, Any]) -> tuple[int, int]:
        title = compact(str(item.get("clean_title") or ""))
        score = 0
        if "首次公开发行股票并在主板上市招股说明书" in title:
            score += 100
        if not any(token in title for token in ("申报稿", "上会稿", "注册稿", "预披露")):
            score += 80
        if title.endswith("招股说明书"):
            score += 30
        return score, announcement_timestamp(item)

    if not prospectus_candidates:
        raise RuntimeError("No full prospectus found")
    prospectus = max(prospectus_candidates, key=prospectus_score)

    if not quarter_candidates:
        raise RuntimeError("No quarterly report found")
    latest_quarter = max(quarter_candidates, key=announcement_timestamp)
    latest_interim = max(interim_candidates, key=announcement_timestamp) if interim_candidates else None

    selected: list[dict[str, Any]] = []
    for year in annual_years:
        item = dict(annual_by_year[year])
        item.update(
            {
                "document_kind": "annual_report",
                "fiscal_period": str(year),
                "expected_year": year,
                "minimum_pages": 50,
                "output_path": f"01_年度报告/国货航_{year}年年度报告.pdf",
                "preview_name": f"annual_{year}_first",
            }
        )
        selected.append(item)

    prospectus_item = dict(prospectus)
    prospectus_item.update(
        {
            "document_kind": "prospectus",
            "fiscal_period": "首次公开发行",
            "expected_year": 2024,
            "minimum_pages": 100,
            "output_path": "02_招股说明书/国货航_首次公开发行股票并在主板上市招股说明书.pdf",
            "preview_name": "prospectus_first",
        }
    )
    selected.append(prospectus_item)

    quarter_title = compact(str(latest_quarter.get("clean_title") or ""))
    quarter_year_match = re.search(r"(20\d{2})年", quarter_title)
    quarter_year = int(quarter_year_match.group(1)) if quarter_year_match else 2026
    quarter_label_match = re.search(r"(第一|第三)季度报告", quarter_title)
    quarter_label = quarter_label_match.group(1) if quarter_label_match else "最新"
    quarter_item = dict(latest_quarter)
    quarter_item.update(
        {
            "document_kind": "quarterly_report",
            "fiscal_period": f"{quarter_year}年{quarter_label}季度",
            "expected_year": quarter_year,
            "minimum_pages": 5,
            "output_path": f"03_最新季报/国货航_{quarter_year}年{quarter_label}季度报告.pdf",
            "preview_name": "latest_quarter_first",
        }
    )
    selected.append(quarter_item)

    if latest_interim and announcement_timestamp(latest_interim) > announcement_timestamp(latest_quarter):
        interim_title = compact(str(latest_interim.get("clean_title") or ""))
        interim_year_match = re.search(r"(20\d{2})年", interim_title)
        interim_year = int(interim_year_match.group(1)) if interim_year_match else quarter_year
        interim_item = dict(latest_interim)
        interim_item.update(
            {
                "document_kind": "interim_report",
                "fiscal_period": f"{interim_year}年半年度",
                "expected_year": interim_year,
                "minimum_pages": 30,
                "output_path": f"04_最新半年度报告_补充/国货航_{interim_year}年半年度报告.pdf",
                "preview_name": "latest_interim_first",
            }
        )
        selected.append(interim_item)

    print("SELECTED_DOCUMENTS", flush=True)
    for item in selected:
        print(
            json.dumps(
                {
                    "kind": item["document_kind"],
                    "title": item.get("clean_title"),
                    "date": publication_date(item),
                    "url": item.get("official_url"),
                    "output": item["output_path"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return selected


def download_pdf(client: httpx.Client, url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, 6):
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            if temporary.exists():
                temporary.unlink()
            with client.stream(
                "GET",
                url,
                headers={
                    **COMMON_HEADERS,
                    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
                    "Referer": "https://www.cninfo.com.cn/",
                },
                timeout=httpx.Timeout(300.0, connect=60.0),
            ) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            size = temporary.stat().st_size
            if size < 80_000:
                raise RuntimeError(f"Downloaded file is too small: {size} bytes")
            with temporary.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise RuntimeError("Downloaded content is not a PDF")
            temporary.replace(destination)
            print("DOWNLOADED", destination, size, url, flush=True)
            return
        except Exception as exc:
            last_error = exc
            print("DOWNLOAD_RETRY", attempt, url, repr(exc), flush=True)
            time.sleep(attempt * 4)
    raise RuntimeError(f"Failed to download {url}: {last_error!r}")


def extract_text(path: Path, max_pages: int = 20) -> str:
    pieces: list[str] = []
    try:
        reader = PdfReader(str(path), strict=False)
        for page in reader.pages[: min(max_pages, len(reader.pages))]:
            try:
                pieces.append(page.extract_text() or "")
            except Exception:
                continue
    except Exception:
        pass
    temp_txt = path.with_suffix(".pdftotext.txt")
    try:
        subprocess.run(
            ["pdftotext", "-f", "1", "-l", str(max_pages), str(path), str(temp_txt)],
            check=False,
            timeout=240,
            capture_output=True,
            text=True,
        )
        if temp_txt.exists():
            pieces.append(temp_txt.read_text(encoding="utf-8", errors="ignore"))
    finally:
        temp_txt.unlink(missing_ok=True)
    return "\n".join(pieces)


def render_first_page(path: Path, preview_name: str) -> Path:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    output_stem = PREVIEW_DIR / preview_name
    subprocess.run(
        ["pdftoppm", "-f", "1", "-singlefile", "-png", "-r", "120", str(path), str(output_stem)],
        check=True,
        timeout=300,
        capture_output=True,
        text=True,
    )
    preview = output_stem.with_suffix(".png")
    if not preview.exists() or preview.stat().st_size < 8_000:
        raise RuntimeError(f"First-page rendering failed for {path}")
    return preview


def validate_document(path: Path, item: dict[str, Any]) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size < 80_000:
        raise RuntimeError(f"Missing or undersized PDF: {path}")
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise RuntimeError(f"Invalid PDF header: {path}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < int(item["minimum_pages"]):
        raise RuntimeError(f"Unexpected page count for {path}: {pages}")

    check = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf validation failed for {path}: {check.stderr[-1600:]}")

    extracted = normalize(extract_text(path))
    company_markers = [normalize(COMPANY_FULL), normalize(COMPANY_SHORT), normalize(COMPANY_EN), STOCK_CODE]
    company_found = any(marker and marker in extracted for marker in company_markers) if extracted else False
    year_found = str(item["expected_year"]) in extracted if extracted else False
    if len(extracted) > 800 and not company_found:
        raise RuntimeError(f"Company marker not found in extracted text for {path}")

    preview = render_first_page(path, str(item["preview_name"]))
    record = {
        "filename": str(path.relative_to(ROOT)),
        "announcement_title": compact(str(item.get("clean_title") or item.get("announcementTitle") or "")),
        "company": COMPANY_FULL,
        "stock_code": STOCK_CODE,
        "document_kind": item["document_kind"],
        "fiscal_period": item["fiscal_period"],
        "release_date": publication_date(item),
        "official_source_url": item["official_url"],
        "announcement_id": item.get("announcementId"),
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "company_marker_found": company_found,
        "expected_year_found": year_found,
        "first_page_preview": str(preview),
    }
    print("VERIFIED", json.dumps(record, ensure_ascii=False), flush=True)
    return record


def write_notes(records: list[dict[str, Any]], org_id: str, selected: list[dict[str, Any]]) -> None:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).isoformat()
    annual_years = sorted(int(item["fiscal_period"]) for item in records if item["document_kind"] == "annual_report")
    quarter = next(item for item in records if item["document_kind"] == "quarterly_report")
    interim = next((item for item in records if item["document_kind"] == "interim_report"), None)
    manifest = {
        "package": PACKAGE_STEM,
        "company": COMPANY_FULL,
        "short_name": COMPANY_SHORT,
        "stock_code": STOCK_CODE,
        "cninfo_org_id": org_id,
        "as_of_date": AS_OF_DATE,
        "generated_at_utc": generated,
        "source": "巨潮资讯网（深圳证券交易所法定信息披露平台）公告PDF",
        "annual_report_years": annual_years,
        "latest_quarterly_report": quarter["fiscal_period"],
        "latest_interim_report_supplement": interim["fiscal_period"] if interim else None,
        "file_count": len(records),
        "records": records,
    }
    (NOTES_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (NOTES_DIR / "selected_announcements.json").write_text(
        json.dumps(
            [
                {
                    "announcement_title": compact(str(item.get("clean_title") or "")),
                    "announcement_time": item.get("announcementTime"),
                    "announcement_id": item.get("announcementId"),
                    "official_source_url": item.get("official_url"),
                    "output_path": item.get("output_path"),
                }
                for item in selected
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (NOTES_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{item['sha256']}  {item['filename']}" for item in records) + "\n",
        encoding="utf-8",
    )

    lines = [
        f"公司：{COMPANY_FULL}（证券简称：{COMPANY_SHORT}）",
        f"证券代码：{STOCK_CODE}",
        f"资料截至：{AS_OF_DATE}",
        "来源：巨潮资讯网官方公告PDF",
        "",
        "收录口径：",
        f"1. 收录巨潮资讯网可检索到的全部完整年度报告：{', '.join(str(year) for year in annual_years)}。",
        "2. 收录首次公开发行股票并在深圳证券交易所主板上市的完整招股说明书。",
        f"3. 最新正式季报为{quarter['fiscal_period']}报告。",
    ]
    if interim:
        lines.append(f"4. 另附披露时间更晚的{interim['fiscal_period']}报告，便于获得更新财务数据；该文件不是季度报告。")
    lines.extend(["", "文件清单："])
    for item in records:
        lines.append(
            f"- {item['filename']} | {item['pages']}页 | 发布日 {item['release_date']} | "
            f"SHA-256 {item['sha256']} | {item['official_source_url']}"
        )
    (NOTES_DIR / "资料清单与来源说明.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def package_zip() -> dict[str, Any]:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file_path in sorted(ROOT.rglob("*")):
            if file_path.is_file():
                archive.write(file_path, file_path.as_posix())
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad_file = archive.testzip()
        if bad_file:
            raise RuntimeError(f"ZIP integrity test failed at {bad_file}")
    return {
        "zip_filename": ZIP_PATH.name,
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256(ZIP_PATH),
    }


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    if PREVIEW_DIR.exists():
        shutil.rmtree(PREVIEW_DIR)
    for folder in (ANNUAL_DIR, PROSPECTUS_DIR, QUARTER_DIR, INTERIM_DIR, NOTES_DIR, PREVIEW_DIR):
        folder.mkdir(parents=True, exist_ok=True)

    with httpx.Client(http2=True, follow_redirects=True, headers=COMMON_HEADERS) as client:
        try:
            warm = client.get("https://www.cninfo.com.cn/new/index", timeout=90)
            print("WARMUP", warm.status_code, len(warm.content), str(warm.url), flush=True)
        except Exception as exc:
            print("WARMUP_WARNING", repr(exc), flush=True)
        org_id = discover_org_id(client)
        announcements = query_announcements(client, org_id)
        selected = select_documents(announcements)

        records: list[dict[str, Any]] = []
        for item in selected:
            destination = ROOT / str(item["output_path"])
            download_pdf(client, str(item["official_url"]), destination)
            records.append(validate_document(destination, item))

    write_notes(records, org_id, selected)
    zip_info = package_zip()
    result = {
        **zip_info,
        "pdf_count": len(records),
        "annual_report_years": sorted(int(item["fiscal_period"]) for item in records if item["document_kind"] == "annual_report"),
        "prospectus_count": sum(1 for item in records if item["document_kind"] == "prospectus"),
        "latest_quarterly_report": next(item["fiscal_period"] for item in records if item["document_kind"] == "quarterly_report"),
        "latest_interim_report_supplement": next((item["fiscal_period"] for item in records if item["document_kind"] == "interim_report"), None),
        "records": records,
    }
    RESULT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PACKAGE_COMPLETE", json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
