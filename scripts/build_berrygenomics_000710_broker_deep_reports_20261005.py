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

CHECK_DATE = "2026-10-05"
COMPANY = "贝瑞基因"
FULL_COMPANY = "成都市贝瑞和康基因技术股份有限公司"
ALT_COMPANY = "贝瑞和康"
CODE = "000710"
PACKAGE_NAME = f"贝瑞基因_{CODE}_券商深度报告_3份_截至{CHECK_DATE}"
ROOT = Path(PACKAGE_NAME)
REPORT_DIR = ROOT / "01_券商深度报告"
META_DIR = ROOT / "02_来源与校验"
WORK_DIR = Path("_berrygenomics_000710_broker_work")
RENDER_DIR = WORK_DIR / "renders"
ZIP_PATH = Path(PACKAGE_NAME + ".zip")
for directory in (REPORT_DIR, META_DIR, WORK_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://data.eastmoney.com/report/stock.jshtml?encodeUrl=",
})


def request(method: str, url: str, *, timeout: tuple[int, int] = (20, 180), **kwargs: Any) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 8):
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
            time.sleep(min(2 * attempt, 12))
    raise RuntimeError(f"request failed for {method} {url}: {errors[-7:]}")


def normalize(text: Any) -> str:
    return re.sub(r"[\s：:—–\-，,。；;（）()]+", "", str(text or "")).lower()


def safe_name(text: str, limit: int = 70) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    text = re.sub(r"\s+", "_", text).strip("_.")
    return text[:limit] or "report"


def fetch_rows() -> list[dict[str, Any]]:
    endpoint = "https://reportapi.eastmoney.com/report/list2"
    bodies = [
        {
            "pageSize": 200,
            "pageNo": 1,
            "p": 1,
            "pageNum": 1,
            "pageNumber": 1,
            "beginTime": "2017-01-01",
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
            "beginTime": "2017-01-01",
            "endTime": CHECK_DATE,
            "code": CODE,
        },
    ]
    rows: list[dict[str, Any]] = []
    for body in bodies:
        try:
            response = request(
                "POST", endpoint,
                json=body,
                headers={"Content-Type": "application/json"},
                timeout=(20, 180),
            )
            try:
                payload = response.json()
            finally:
                response.close()
            data = payload.get("data", []) if isinstance(payload, dict) else []
            if isinstance(data, list) and data:
                rows = [row for row in data if isinstance(row, dict)]
                break
        except Exception as exc:  # noqa: BLE001
            print("LIST2_ERROR", repr(exc), flush=True)
    if not rows:
        raise RuntimeError("No broker report rows returned for 000710")
    exact = [row for row in rows if str(row.get("stockCode", "")) == CODE]
    if exact:
        rows = exact
    print("REPORT_COUNT", len(rows), flush=True)
    compact = [
        {
            "title": row.get("title"),
            "institution": row.get("orgSName") or row.get("orgName"),
            "date": row.get("publishDate"),
            "pages": row.get("attachPages"),
            "size_kb": row.get("attachSize"),
            "infoCode": row.get("infoCode"),
            "rating": row.get("emRatingName") or row.get("sRatingName"),
            "researcher": row.get("researcher"),
        }
        for row in rows
    ]
    print("REPORT_ROWS", json.dumps(compact, ensure_ascii=False, indent=2), flush=True)
    return rows


def candidate_score(row: dict[str, Any]) -> int:
    title = normalize(row.get("title"))
    pages = int(row.get("attachPages") or 0)
    score = pages * 12
    if "公司深度" in title or "深度报告" in title or "深度研究" in title:
        score += 1200
    if "首次覆盖" in title or "首次评级" in title:
        score += 1100
    if "深度" in title:
        score += 700
    if "基因检测" in title or "肿瘤早筛" in title or "测序" in title or "精准医疗" in title:
        score += 180
    if any(token in title for token in ("点评", "季报", "年报", "中报", "业绩", "快报")):
        score -= 700
    if pages < 8:
        score -= 1000
    elif pages >= 25:
        score += 280
    elif pages >= 15:
        score += 160
    date = str(row.get("publishDate") or "")[:10]
    if date >= "2020-01-01":
        score += 60
    return score


def select_reports(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=lambda row: (candidate_score(row), str(row.get("publishDate") or "")), reverse=True)
    print(
        "RANKED",
        json.dumps([
            {
                "score": candidate_score(row),
                "title": row.get("title"),
                "institution": row.get("orgSName") or row.get("orgName"),
                "date": row.get("publishDate"),
                "pages": row.get("attachPages"),
                "infoCode": row.get("infoCode"),
            }
            for row in ranked
        ], ensure_ascii=False, indent=2),
        flush=True,
    )
    selected: list[dict[str, Any]] = []
    used_orgs: set[str] = set()
    used_codes: set[str] = set()

    # First pass: substantial deep or first-coverage reports from different institutions.
    for row in ranked:
        title = normalize(row.get("title"))
        pages = int(row.get("attachPages") or 0)
        code = str(row.get("infoCode") or "")
        org = str(row.get("orgSName") or row.get("orgName") or "未知机构")
        if not re.fullmatch(r"AP\d+", code, flags=re.I):
            continue
        if pages < 10:
            continue
        if not any(token in title for token in ("深度", "首次覆盖", "首次评级")):
            continue
        if org in used_orgs or code in used_codes:
            continue
        selected.append(row)
        used_orgs.add(org)
        used_codes.add(code)
        if len(selected) == 3:
            break

    # Second pass: fill with substantial company reports, still preferring institution diversity.
    if len(selected) < 3:
        for row in ranked:
            pages = int(row.get("attachPages") or 0)
            code = str(row.get("infoCode") or "")
            org = str(row.get("orgSName") or row.get("orgName") or "未知机构")
            if not re.fullmatch(r"AP\d+", code, flags=re.I) or pages < 10 or code in used_codes:
                continue
            if org in used_orgs and len(used_orgs) >= 2:
                continue
            selected.append(row)
            used_orgs.add(org)
            used_codes.add(code)
            if len(selected) == 3:
                break

    if len(selected) < 2:
        raise RuntimeError(f"Only {len(selected)} substantial broker reports could be selected")
    print("SELECTED", json.dumps([
        {
            "title": row.get("title"),
            "institution": row.get("orgSName") or row.get("orgName"),
            "date": row.get("publishDate"),
            "pages": row.get("attachPages"),
            "infoCode": row.get("infoCode"),
        }
        for row in selected
    ], ensure_ascii=False, indent=2), flush=True)
    return selected


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_pdf(info_code: str, destination: Path) -> str:
    candidates = [
        f"https://pdf.dfcfw.com/pdf/H3_{info_code.upper()}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H2_{info_code.upper()}_1.pdf",
    ]
    errors: list[str] = []
    for url in candidates:
        temp = destination.with_suffix(destination.suffix + ".part")
        temp.unlink(missing_ok=True)
        try:
            response = request("GET", url, timeout=(20, 420), stream=True)
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
            if size < 30_000 or not head.startswith(b"%PDF-"):
                raise RuntimeError(f"invalid PDF bytes={size}, head={head!r}")
            temp.replace(destination)
            return final_url
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc!r}")
            temp.unlink(missing_ok=True)
    raise RuntimeError(f"failed to download {info_code}: {errors}")


def render_page(path: Path, page_number: int, tag: str) -> None:
    prefix = RENDER_DIR / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{tag}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
            "-r", "84", "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    image = Path(str(prefix) + ".png")
    valid = (
        process.returncode == 0 and image.exists() and image.stat().st_size > 1000
        and image.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(f"render validation failed for {path.name} page {page_number}: {process.stderr[-1500:]}")
    image.unlink()


def validate_pdf(path: Path, expected_pages: int | None) -> dict[str, Any]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {check.stderr[-2500:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 8:
        raise RuntimeError(f"report too short: {path.name}, pages={pages}")
    if expected_pages and abs(pages - expected_pages) > 1:
        raise RuntimeError(f"page mismatch for {path.name}: actual={pages}, expected={expected_pages}")
    render_page(path, 1, "first")
    render_page(path, pages, "last")
    indices = sorted({0, 1, min(3, pages - 1), pages // 2, pages - 1})
    sample = "\n".join((reader.pages[index].extract_text() or "") for index in indices)
    normalized = re.sub(r"\s+", "", sample)
    identity_ok = any(marker in normalized for marker in (COMPANY, FULL_COMPANY, ALT_COMPANY, CODE))
    if sample.strip() and not identity_ok:
        raise RuntimeError(f"issuer identity not found in sampled text: {path.name}")
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "render_verified_first_and_last_page": True,
        "issuer_identity_verified_when_text_extractable": identity_ok,
        "sample_text_extractable": bool(sample.strip()),
    }


def main() -> None:
    rows = fetch_rows()
    selected = select_reports(rows)
    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for index, row in enumerate(selected, start=1):
        title = str(row.get("title") or "未命名报告")
        institution = str(row.get("orgSName") or row.get("orgName") or "未知机构")
        date = str(row.get("publishDate") or "")[:10]
        info_code = str(row.get("infoCode") or "")
        pages_expected = int(row.get("attachPages") or 0) or None
        filename = f"{index:02d}_{safe_name(institution)}_{safe_name(title)}_{date}.pdf"
        destination = REPORT_DIR / filename
        source_url = download_pdf(info_code, destination)
        metadata = validate_pdf(destination, pages_expected)
        if metadata["sha256"] in seen_hashes:
            raise RuntimeError(f"duplicate report detected: {destination.name}")
        seen_hashes.add(metadata["sha256"])
        record = {
            "title": title,
            "institution": institution,
            "publish_date": date,
            "researcher": row.get("researcher") or "",
            "rating": row.get("emRatingName") or row.get("sRatingName") or "",
            "info_code": info_code,
            "declared_pages": pages_expected,
            "declared_size_kb": row.get("attachSize"),
            "relative_path": str(destination.relative_to(ROOT)),
            "source": "东方财富研报公开分发PDF",
            "source_url": source_url,
            **metadata,
        }
        records.append(record)
        print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

    manifest = {
        "company": COMPANY,
        "full_company_name": FULL_COMPANY,
        "stock_code": CODE,
        "checked_as_of": CHECK_DATE,
        "report_count": len(records),
        "reports": records,
    }
    (META_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with (META_DIR / "报告清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "title", "institution", "publish_date", "researcher", "rating", "info_code",
            "declared_pages", "pages", "bytes", "sha256", "relative_path", "source", "source_url",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({key: record.get(key, "") for key in fieldnames})
    (META_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{row['sha256']}  {row['relative_path']}" for row in records) + "\n",
        encoding="utf-8",
    )
    readme = [
        f"{COMPANY}（{CODE}）券商深度研究报告资料包",
        "",
        f"核对日期：{CHECK_DATE}",
        f"报告数量：{len(records)}份",
        "",
        "说明：",
        "1. 报告均为公开渠道取得的券商原始PDF。",
        "2. 优先选择公司深度、首次覆盖或篇幅较长的公司研究报告。",
        "3. 每份PDF已检查文件头、实际页数、qpdf结构、公司名称或证券代码，并渲染首页和末页验证可读性。",
        "4. 详细来源、页数和SHA-256见报告清单.csv、manifest.json和SHA256SUMS.txt。",
        "",
        "报告清单：",
    ]
    for row in records:
        readme.append(
            f"- {row['institution']}｜{row['title']}｜{row['publish_date']}｜{row['pages']}页｜{row['researcher']}"
        )
    (META_DIR / "README.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")

    ZIP_PATH.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(path))
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP integrity failure at {bad}")
    if ZIP_PATH.stat().st_size < 100_000:
        raise RuntimeError("ZIP unexpectedly small")
    print("FINAL_ZIP", ZIP_PATH, ZIP_PATH.stat().st_size, flush=True)
    print("REPORT_COUNT", len(records), flush=True)
    print("TOTAL_PAGES", sum(row["pages"] for row in records), flush=True)


if __name__ == "__main__":
    main()
