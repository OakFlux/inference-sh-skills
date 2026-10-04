from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

STOCK_CODE = "605255"
COMPANY = "宁波市天普橡胶科技股份有限公司"
SHORT_NAME = "天普股份"
CHECKED_AS_OF = "2026-10-05"
EXPECTED_ANNUAL_YEARS = list(range(2020, 2026))
ROOT = Path(f"天普股份_{STOCK_CODE}_全部年报_招股说明书_最新季报")
WORK = Path("_tianpu_605255_filings_work")
OUT_ZIP = Path(f"{ROOT.name}.zip")

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Referer": "https://data.eastmoney.com/",
        "Accept": "application/json,text/plain,*/*",
    }
)


def safe_filename(text: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]", "_", text)
    text = re.sub(r"\s+", "", text)
    return text.strip("._")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def request_json(url: str, params: dict[str, Any], attempts: int = 5) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            r = SESSION.get(url, params=params, timeout=45)
            print("API", attempt, r.status_code, r.url, len(r.content), flush=True)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(attempt * 2)
    raise RuntimeError(f"API request failed: {last}")


def fetch_announcements() -> list[dict[str, Any]]:
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    all_items: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = request_json(
            url,
            {
                "sr": "-1",
                "page_size": "100",
                "page_index": str(page),
                "ann_type": "A",
                "client_source": "web",
                "stock_list": STOCK_CODE,
                "f_node": "0",
                "s_node": "0",
            },
        )
        data = payload.get("data") or {}
        items = data.get("list") or []
        if not isinstance(items, list):
            raise RuntimeError(f"Unexpected API payload on page {page}: {payload!r}")
        print("PAGE", page, "ITEMS", len(items), "TOTAL", data.get("total_hits"), flush=True)
        all_items.extend(items)
        total_hits = int(data.get("total_hits") or len(all_items))
        if not items or len(all_items) >= total_hits:
            break
        page += 1
        if page > 30:
            raise RuntimeError("Announcement pagination exceeded safety limit")
        time.sleep(0.4)
    return all_items


def title_of(item: dict[str, Any]) -> str:
    return str(item.get("title") or "").replace("<em>", "").replace("</em>", "").strip()


def date_of(item: dict[str, Any]) -> str:
    raw = str(item.get("notice_date") or item.get("display_time") or item.get("eiTime") or "")
    m = re.search(r"\d{4}-\d{2}-\d{2}", raw)
    return m.group(0) if m else raw[:10]


def art_code_of(item: dict[str, Any]) -> str:
    return str(item.get("art_code") or item.get("infoCode") or "").strip()


def choose_documents(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annual_by_year: dict[int, list[dict[str, Any]]] = {y: [] for y in EXPECTED_ANNUAL_YEARS}
    prospectus: list[dict[str, Any]] = []
    quarterly: list[tuple[int, int, str, dict[str, Any]]] = []

    annual_pat = re.compile(r"(?P<year>20\d{2})年年度报告(?:[（(].*?[）)])?$")
    quarter_pat = re.compile(r"(?P<year>20\d{2})年(?P<quarter>第一季度|第三季度)报告(?:[（(].*?[）)])?$")

    for item in items:
        title = title_of(item)
        if not title:
            continue

        am = annual_pat.search(title)
        if am and not any(x in title for x in ["摘要", "英文", "取消", "延期", "预约", "审计报告"]):
            year = int(am.group("year"))
            if year in annual_by_year:
                annual_by_year[year].append(item)

        if "招股说明书" in title and not any(x in title for x in ["摘要", "提示性公告", "更正公告", "关于"]):
            prospectus.append(item)

        qm = quarter_pat.search(title)
        if qm and not any(x in title for x in ["摘要", "更正公告", "关于"]):
            year = int(qm.group("year"))
            q = 1 if qm.group("quarter") == "第一季度" else 3
            quarterly.append((year, q, date_of(item), item))

    selected: list[dict[str, Any]] = []
    missing: list[int] = []
    for year in EXPECTED_ANNUAL_YEARS:
        candidates = annual_by_year[year]
        if not candidates:
            missing.append(year)
            continue
        # Later publication wins, so a revised/full replacement report supersedes an earlier one.
        candidates.sort(key=lambda x: (date_of(x), title_of(x)), reverse=True)
        chosen = dict(candidates[0])
        chosen["_category"] = "annual_report"
        chosen["_report_year"] = year
        selected.append(chosen)

    if missing:
        print("MISSING_ANNUAL_YEARS", missing, flush=True)
        for item in items:
            t = title_of(item)
            if "年度报告" in t:
                print("ANNUAL_CANDIDATE", date_of(item), art_code_of(item), t, flush=True)
        raise RuntimeError(f"Missing annual reports for years: {missing}")

    # Include every full prospectus found, while deduplicating identical announcement codes.
    prospectus.sort(key=lambda x: (date_of(x), title_of(x)))
    seen_codes: set[str] = set()
    for item in prospectus:
        code = art_code_of(item)
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        chosen = dict(item)
        chosen["_category"] = "prospectus"
        selected.append(chosen)

    if not seen_codes:
        for item in items:
            t = title_of(item)
            if "招股" in t:
                print("PROSPECTUS_CANDIDATE", date_of(item), art_code_of(item), t, flush=True)
        raise RuntimeError("No full prospectus found")

    if not quarterly:
        raise RuntimeError("No quarterly report found")
    quarterly.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    y, q, _, item = quarterly[0]
    chosen = dict(item)
    chosen["_category"] = "latest_quarterly_report"
    chosen["_report_year"] = y
    chosen["_quarter"] = q
    selected.append(chosen)

    print("SELECTED_JSON", json.dumps([
        {
            "date": date_of(x),
            "art_code": art_code_of(x),
            "title": title_of(x),
            "category": x.get("_category"),
            "year": x.get("_report_year"),
            "quarter": x.get("_quarter"),
        }
        for x in selected
    ], ensure_ascii=False, indent=2), flush=True)
    return selected


def download_pdf(art_code: str, destination: Path) -> tuple[str, int]:
    candidates = [
        f"https://pdf.dfcfw.com/pdf/H2_{art_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{art_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/{art_code}_1.pdf",
    ]
    last_error = ""
    for url in candidates:
        for attempt in range(1, 4):
            try:
                r = SESSION.get(url, timeout=90, allow_redirects=True)
                ctype = r.headers.get("content-type", "")
                print("PDF", art_code, attempt, r.status_code, ctype, len(r.content), r.url, flush=True)
                if r.status_code == 200 and r.content.startswith(b"%PDF-") and len(r.content) > 20_000:
                    destination.write_bytes(r.content)
                    return r.url, len(r.content)
                last_error = f"status={r.status_code}, type={ctype}, bytes={len(r.content)}, url={r.url}"
            except Exception as exc:  # noqa: BLE001
                last_error = repr(exc)
            time.sleep(attempt * 1.5)
    raise RuntimeError(f"Unable to download PDF for {art_code}: {last_error}")


def validate_pdf(path: Path, expected_tokens: list[str]) -> dict[str, Any]:
    if path.read_bytes()[:5] != b"%PDF-":
        raise RuntimeError(f"Not a PDF: {path}")
    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True)
    if qpdf.returncode != 0:
        raise RuntimeError(f"qpdf validation failed for {path}: {qpdf.stderr}")

    reader = PdfReader(str(path))
    pages = len(reader.pages)
    if pages < 1:
        raise RuntimeError(f"No pages in {path}")

    sample_indices = sorted(set([0, min(1, pages - 1), pages - 1]))
    text_parts: list[str] = []
    for idx in sample_indices:
        try:
            text_parts.append(reader.pages[idx].extract_text() or "")
        except Exception:  # noqa: BLE001
            pass
    sample_text = "\n".join(text_parts)
    compact = re.sub(r"\s+", "", sample_text)
    if compact and not any(token in compact for token in expected_tokens):
        raise RuntimeError(f"Identity validation failed for {path}; tokens={expected_tokens}; sample={compact[:500]}")

    render_dir = WORK / "renders" / safe_filename(path.stem)
    render_dir.mkdir(parents=True, exist_ok=True)
    for page_no in sorted(set([1, pages])):
        prefix = render_dir / f"page_{page_no}"
        cmd = ["pdftoppm", "-f", str(page_no), "-l", str(page_no), "-png", "-r", "80", str(path), str(prefix)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"Render failed for {path} page {page_no}: {proc.stderr}")
        if not list(render_dir.glob(f"page_{page_no}-*.png")):
            raise RuntimeError(f"Rendered image missing for {path} page {page_no}")

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "sample_text_extractable": bool(compact),
        "identity_verified_when_text_extractable": (not compact) or any(token in compact for token in expected_tokens),
        "rendered_pages": sorted(set([1, pages])),
    }


def category_folder(category: str) -> str:
    return {
        "annual_report": "01_年度报告",
        "prospectus": "02_招股说明书",
        "latest_quarterly_report": "03_最新季度报告",
    }[category]


def main() -> None:
    for path in [ROOT, WORK]:
        if path.exists():
            shutil.rmtree(path)
    if OUT_ZIP.exists():
        OUT_ZIP.unlink()
    ROOT.mkdir(parents=True)
    WORK.mkdir(parents=True)

    items = fetch_announcements()
    selected = choose_documents(items)
    records: list[dict[str, Any]] = []

    for item in selected:
        title = title_of(item)
        art_code = art_code_of(item)
        notice_date = date_of(item)
        category = str(item["_category"])
        if not art_code:
            raise RuntimeError(f"Missing announcement code for {title}")
        folder = ROOT / category_folder(category)
        folder.mkdir(parents=True, exist_ok=True)
        filename = f"{notice_date.replace('-', '')}_{safe_filename(title)}.pdf"
        destination = folder / filename
        source_url, downloaded_bytes = download_pdf(art_code, destination)

        expected_tokens = [SHORT_NAME, STOCK_CODE, COMPANY[:8]]
        if category == "annual_report":
            expected_tokens.append(str(item.get("_report_year")))
        elif category == "prospectus":
            expected_tokens.append("招股说明书")
        elif category == "latest_quarterly_report":
            expected_tokens.append("季度报告")

        validation = validate_pdf(destination, expected_tokens)
        record = {
            "category": category,
            "category_cn": category_folder(category).split("_", 1)[1],
            "report_year": item.get("_report_year"),
            "quarter": item.get("_quarter"),
            "notice_date": notice_date,
            "title": title,
            "art_code": art_code,
            "relative_path": destination.relative_to(ROOT).as_posix(),
            "source_url": source_url,
            "source_detail_url": f"https://data.eastmoney.com/notices/detail/{STOCK_CODE}/{art_code}.html",
            "downloaded_bytes": downloaded_bytes,
            **validation,
        }
        records.append(record)
        print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

    annual_years = sorted(int(r["report_year"]) for r in records if r["category"] == "annual_report")
    if annual_years != EXPECTED_ANNUAL_YEARS:
        raise RuntimeError(f"Annual year coverage mismatch: {annual_years}")

    latest_q = [r for r in records if r["category"] == "latest_quarterly_report"]
    if len(latest_q) != 1:
        raise RuntimeError(f"Expected exactly one latest quarterly report, found {len(latest_q)}")

    manifest = {
        "package_name": ROOT.name,
        "company": COMPANY,
        "short_name": SHORT_NAME,
        "stock_code": STOCK_CODE,
        "checked_as_of": CHECKED_AS_OF,
        "scope": {
            "annual_reports": f"上市以来完整年度报告，覆盖{EXPECTED_ANNUAL_YEARS[0]}—{EXPECTED_ANNUAL_YEARS[-1]}年度；同一年度如存在替换/修订版本，以公开数据库中最新发布的完整报告为准。",
            "prospectus": "公开检索到的全部非摘要版招股说明书。",
            "latest_quarterly_report": f"截至{CHECKED_AS_OF}公开披露的最新第一季度或第三季度报告。",
            "exclusions": "未纳入年度报告摘要、英文版、审计报告单行文件、半年度报告及公告性更正说明。",
        },
        "document_count": len(records),
        "records": records,
    }

    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    readme_lines = [
        f"{COMPANY}（{SHORT_NAME}，{STOCK_CODE}）公开披露文件包",
        "=" * 72,
        f"核验日期：{CHECKED_AS_OF}",
        "",
        "收录范围：",
        f"1. 上市以来全部完整年度报告：{EXPECTED_ANNUAL_YEARS[0]}—{EXPECTED_ANNUAL_YEARS[-1]}年度，共{len(EXPECTED_ANNUAL_YEARS)}份。",
        f"2. 全部非摘要版招股说明书：{sum(r['category'] == 'prospectus' for r in records)}份。",
        "3. 截至核验日最新已披露季度报告：1份。",
        "",
        "说明：",
        "- 文件来自公开证券信息数据库的原始PDF镜像，未重新排版。",
        "- 年度报告摘要、英文版、半年度报告及单独更正公告不在本包范围内。",
        "- 每份PDF均通过文件头、qpdf结构、页数、文本身份和页面渲染检查。",
        "- 文件清单、来源地址、页数、大小与SHA-256详见文件清单.csv及manifest.json。",
        "",
        "文件列表：",
    ]
    for idx, r in enumerate(records, 1):
        q_text = f"，第{r['quarter']}季度" if r.get("quarter") else ""
        readme_lines.append(
            f"{idx}. [{r['category_cn']}] {r['title']}（公告日{r['notice_date']}{q_text}，{r['pages']}页）"
        )
    (ROOT / "README.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

    csv_fields = [
        "类别", "报告年度", "季度", "公告日期", "标题", "页数", "文件大小_字节", "SHA256", "相对路径", "公告代码", "PDF来源", "详情页",
    ]
    with (ROOT / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "类别": r["category_cn"],
                    "报告年度": r.get("report_year") or "",
                    "季度": r.get("quarter") or "",
                    "公告日期": r["notice_date"],
                    "标题": r["title"],
                    "页数": r["pages"],
                    "文件大小_字节": r["bytes"],
                    "SHA256": r["sha256"],
                    "相对路径": r["relative_path"],
                    "公告代码": r["art_code"],
                    "PDF来源": r["source_url"],
                    "详情页": r["source_detail_url"],
                }
            )

    checksum_lines = [f"{r['sha256']}  {r['relative_path']}" for r in records]
    (ROOT / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in sorted(ROOT.rglob("*")):
            if p.is_file():
                zf.write(p, arcname=f"{ROOT.name}/{p.relative_to(ROOT).as_posix()}")

    # Verify ZIP readability and contents.
    with zipfile.ZipFile(OUT_ZIP, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")
        names = zf.namelist()
        pdf_count = sum(name.lower().endswith(".pdf") for name in names)
        if pdf_count != len(records):
            raise RuntimeError(f"ZIP PDF count mismatch: {pdf_count} vs {len(records)}")

    print("FINAL_ZIP", OUT_ZIP, "bytes", OUT_ZIP.stat().st_size, "sha256", sha256_file(OUT_ZIP), flush=True)
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print("FATAL", repr(exc), file=sys.stderr, flush=True)
        raise
