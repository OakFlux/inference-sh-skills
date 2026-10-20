from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

AS_OF = "2026-10-20"
COMPANY = "全志科技"
FULL_COMPANY = "珠海全志科技股份有限公司"
STOCK_CODE = "300458"
ANNUAL_YEARS = list(range(2015, 2026))

PACKAGE_NAME = f"{COMPANY}_{STOCK_CODE}_全部年报_招股说明书_最新季报_截至{AS_OF.replace('-', '')}"
ROOT = Path(PACKAGE_NAME)
ANNUAL_DIR = ROOT / "01_年度报告"
PROSPECTUS_DIR = ROOT / "02_招股说明书"
QUARTER_DIR = ROOT / "03_最新季报"
SOURCE_DIR = ROOT / "04_来源与校验"
WORK_DIR = Path("_allwinner_300458_work")
RENDER_DIR = WORK_DIR / "renders"
ZIP_PATH = Path(PACKAGE_NAME + ".zip")
SUMMARY_PATH = Path("package_summary.json")

NOTICE_API = "https://np-anotice-stock.eastmoney.com/api/security/ann"

SESSION = requests.Session()
SESSION.trust_env = False
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "Chrome/155.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,application/pdf,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
)


@dataclass
class Document:
    document_type: str
    report_period: str
    title: str
    publication_date: str
    announcement_id: str
    source_pdf_url: str
    source_detail_url: str
    relative_path: str
    pages: int = 0
    bytes: int = 0
    sha256: str = ""
    qpdf_return_code: int = -1
    company_identity_verified_when_text_extractable: bool = False
    first_last_page_rendered: bool = False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request(
    method: str,
    url: str,
    *,
    timeout: tuple[int, int] = (20, 300),
    **kwargs: Any,
) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 9):
        try:
            response = SESSION.request(
                method,
                url,
                timeout=timeout,
                allow_redirects=True,
                **kwargs,
            )
            print(
                "HTTP",
                method,
                url,
                "attempt",
                attempt,
                "status",
                response.status_code,
                "type",
                response.headers.get("content-type"),
                "length",
                response.headers.get("content-length"),
                "final",
                response.url,
                flush=True,
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
    raise RuntimeError(f"request failed for {method} {url}: {errors[-8:]}")


def title_of(row: dict[str, Any]) -> str:
    return str(row.get("title_ch") or row.get("title") or "").strip()


def date_of(row: dict[str, Any]) -> str:
    raw = str(
        row.get("notice_date")
        or row.get("display_time")
        or row.get("sort_date")
        or ""
    )
    match = re.search(r"\d{4}-\d{2}-\d{2}", raw)
    return match.group(0) if match else ""


def columns_of(row: dict[str, Any]) -> list[str]:
    columns = row.get("columns") or []
    return [
        str(item.get("column_name") or "")
        for item in columns
        if isinstance(item, dict)
    ]


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def fetch_notice_rows() -> list[dict[str, Any]]:
    for ann_type in ("A", "SZSA", "SZ", "CYB"):
        collected: list[dict[str, Any]] = []
        for page in range(1, 31):
            params = {
                "sr": "-1",
                "page_size": "100",
                "page_index": str(page),
                "ann_type": ann_type,
                "client_source": "web",
                "stock_list": STOCK_CODE,
                "f_node": "0",
                "s_node": "0",
                "begin_time": "2014-01-01",
                "end_time": AS_OF,
            }
            response = request("GET", NOTICE_API, params=params, timeout=(20, 180))
            try:
                payload = response.json()
            finally:
                response.close()
            rows = (((payload or {}).get("data") or {}).get("list") or [])
            print("NOTICE_PAGE", ann_type, page, "rows", len(rows), flush=True)
            collected.extend(row for row in rows if isinstance(row, dict))
            if len(rows) < 100:
                break
        if collected:
            print("NOTICE_ROWS_COUNT", len(collected), "ANN_TYPE", ann_type, flush=True)
            for row in collected:
                title = title_of(row)
                if any(token in title for token in ("年度报告", "季度报告", "招股说明书")):
                    print(
                        "CANDIDATE",
                        date_of(row),
                        title,
                        row.get("art_code"),
                        row.get("columns"),
                        flush=True,
                    )
            return collected
    raise RuntimeError(f"No announcement rows returned for stock {STOCK_CODE}")


def annual_score(row: dict[str, Any], year: int) -> int:
    title = compact(title_of(row))
    columns = columns_of(row)
    score = 0
    if "年度报告全文" in columns:
        score += 1000
    if re.search(fr"{year}年年度报告(?:全文)?(?:[(（].*(?:修订|更新|更正).*[)）])?$", title):
        score += 600
    if f"{year}年年度报告" in title:
        score += 350
    if any(token in title for token in ("修订版", "更新后", "更正版", "修订后", "更正后")):
        score += 150
    if any(
        token in title
        for token in (
            "摘要",
            "英文",
            "取消",
            "提示性公告",
            "审计报告",
            "问询函",
            "回复公告",
            "社会责任报告",
            "环境报告",
            "书面确认意见",
            "签章页",
        )
    ):
        score -= 5000
    return score


def select_annual(rows: list[dict[str, Any]], year: int) -> dict[str, Any]:
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for row in rows:
        title = compact(title_of(row))
        if f"{year}年年度报告" not in title:
            continue
        if not row.get("art_code"):
            continue
        score = annual_score(row, year)
        if score > 0:
            candidates.append((score, date_of(row), row))
    if not candidates:
        related = [title_of(row) for row in rows if str(year) in title_of(row)]
        raise RuntimeError(f"No annual report found for {year}; related={related[:60]}")
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = dict(candidates[0][2])
    selected["title_norm"] = title_of(selected)
    selected["date_norm"] = date_of(selected)
    selected["fiscal_year"] = year
    selected["selection_score"] = candidates[0][0]
    print("SELECTED_ANNUAL", year, json.dumps(selected, ensure_ascii=False, indent=2), flush=True)
    return selected


def prospectus_score(row: dict[str, Any]) -> int:
    title = compact(title_of(row))
    score = 0
    if "首次公开发行股票并在创业板上市招股说明书" in title:
        score += 2000
    if "首次公开发行" in title and "创业板" in title and "招股说明书" in title:
        score += 1000
    if title.endswith("招股说明书"):
        score += 500
    if "招股说明书" in title:
        score += 300
    if date_of(row).startswith("2015-"):
        score += 250
    if any(
        token in title
        for token in (
            "申报稿",
            "注册稿",
            "上会稿",
            "摘要",
            "提示性公告",
            "确认意见",
            "签章页",
            "反馈意见",
            "问询回复",
            "审核问询",
            "保荐书",
            "法律意见书",
            "更正公告",
        )
    ):
        score -= 5000
    return score


def select_prospectus(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    seen_titles: list[str] = []
    for row in rows:
        title = title_of(row)
        if "招股说明书" not in compact(title):
            continue
        seen_titles.append(f"{date_of(row)} {title} {row.get('art_code')}")
        if not row.get("art_code"):
            continue
        score = prospectus_score(row)
        if score > 0:
            candidates.append((score, date_of(row), row))
    print("PROSPECTUS_CANDIDATES", json.dumps(seen_titles, ensure_ascii=False, indent=2), flush=True)
    if not candidates:
        raise RuntimeError(f"No final prospectus found; candidates={seen_titles[:80]}")
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = dict(candidates[0][2])
    selected["title_norm"] = title_of(selected)
    selected["date_norm"] = date_of(selected)
    selected["selection_score"] = candidates[0][0]
    print("SELECTED_PROSPECTUS", json.dumps(selected, ensure_ascii=False, indent=2), flush=True)
    return selected


def quarter_rank(title: str) -> int:
    title = compact(title)
    if any(token in title for token in ("第三季度报告", "三季度报告")):
        return 3
    if any(token in title for token in ("第一季度报告", "一季度报告")):
        return 1
    return 0


def quarter_year(title: str) -> int:
    match = re.search(r"(20\d{2})年", compact(title))
    return int(match.group(1)) if match else 0


def select_latest_quarter(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[tuple[int, int, int, str, dict[str, Any]]] = []
    for row in rows:
        title = compact(title_of(row))
        if "季度报告" not in title or not row.get("art_code"):
            continue
        if any(
            token in title
            for token in (
                "摘要",
                "英文",
                "取消",
                "提示性公告",
                "更正公告",
                "书面确认意见",
                "签章页",
            )
        ):
            continue
        rank = quarter_rank(title)
        year = quarter_year(title)
        if not rank or not year:
            continue
        column_bonus = int(
            any(name in {"一季度报告全文", "三季度报告全文"} for name in columns_of(row))
        )
        candidates.append((year, rank, column_bonus, date_of(row), row))
    if not candidates:
        raise RuntimeError("No strict first- or third-quarter report found")
    candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)
    year, rank, _, _, row = candidates[0]
    selected = dict(row)
    selected["title_norm"] = title_of(selected)
    selected["date_norm"] = date_of(selected)
    selected["fiscal_year"] = year
    selected["quarter_rank"] = rank
    selected["quarter_label"] = "第三季度报告" if rank == 3 else "第一季度报告"
    print("SELECTED_QUARTER", json.dumps(selected, ensure_ascii=False, indent=2), flush=True)
    return selected


def download_pdf(announcement_id: str, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    for prefix in ("H2", "H3", "H1"):
        url = f"https://pdf.dfcfw.com/pdf/{prefix}_{announcement_id}_1.pdf"
        temp = destination.with_suffix(destination.suffix + ".part")
        temp.unlink(missing_ok=True)
        try:
            response = request(
                "GET",
                url,
                timeout=(25, 600),
                stream=True,
                headers={"Referer": "https://data.eastmoney.com/"},
            )
            try:
                with temp.open("wb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            handle.write(chunk)
                final_url = str(response.url)
            finally:
                response.close()
            size = temp.stat().st_size if temp.exists() else 0
            head = temp.read_bytes()[:8] if temp.exists() else b""
            if size < 20_000 or not head.startswith(b"%PDF-"):
                raise RuntimeError(f"invalid PDF bytes={size}, head={head!r}")
            temp.replace(destination)
            print("DOWNLOADED", destination, destination.stat().st_size, final_url, flush=True)
            return final_url
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{url}: {exc!r}")
            print("PDF_CANDIDATE_FAILED", url, repr(exc), flush=True)
            temp.unlink(missing_ok=True)
    raise RuntimeError(
        f"Could not download PDF for {announcement_id}; failures={failures}"
    )


def render_page(path: Path, page_number: int, tag: str) -> None:
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
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
    valid = (
        process.returncode == 0
        and image.exists()
        and image.stat().st_size > 1000
        and image.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(
            f"render validation failed for {path.name} page {page_number}: "
            f"{process.stderr[-1500:]}"
        )
    image.unlink()


def extract_sample_text(reader: PdfReader, pages: int) -> str:
    indices = sorted(
        {
            *range(min(12, pages)),
            max(0, pages // 2),
            pages - 1,
        }
    )
    parts: list[str] = []
    for index in indices:
        try:
            parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_EXTRACT_WARNING", index + 1, repr(exc), flush=True)
    return "\n".join(parts)


def validate_pdf(path: Path, document: Document) -> None:
    check = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-2500:]}")

    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    minimum_pages = {
        "年度报告": 50,
        "招股说明书": 200,
        "季度报告": 8,
    }[document.document_type]
    if pages < minimum_pages:
        raise RuntimeError(
            f"unexpectedly short PDF {path.name}: {pages} pages < {minimum_pages}"
        )

    render_page(path, 1, "first")
    if pages > 1:
        render_page(path, pages, "last")

    sample = extract_sample_text(reader, pages)
    normalized = compact(sample)
    identity_ok = any(
        marker in normalized
        for marker in (COMPANY, FULL_COMPANY, STOCK_CODE)
    )
    if sample.strip() and not identity_ok:
        raise RuntimeError(f"issuer identity not found in sampled text for {path.name}")

    first_parts: list[str] = []
    for index in range(min(12, pages)):
        try:
            first_parts.append(reader.pages[index].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("FIRST_TEXT_WARNING", path.name, index + 1, repr(exc), flush=True)
    first_text = "\n".join(first_parts)
    first_normalized = compact(first_text)

    if document.document_type == "年度报告":
        if "年度报告摘要" in first_normalized and "年度报告" not in first_normalized.replace("年度报告摘要", ""):
            raise RuntimeError(f"annual report summary detected: {path.name}")
        if first_text.strip() and "年度报告" not in first_normalized:
            raise RuntimeError(f"annual-report marker missing: {path.name}")
        year = document.report_period
        if sample.strip() and year not in normalized:
            raise RuntimeError(f"fiscal year {year} not found in {path.name}")
    elif document.document_type == "招股说明书":
        if first_text.strip() and "招股说明书" not in first_normalized:
            raise RuntimeError(f"prospectus marker missing: {path.name}")
    else:
        if first_text.strip() and not any(
            marker in first_normalized
            for marker in ("季度报告", "一季度报告", "三季度报告")
        ):
            raise RuntimeError(f"quarterly-report marker missing: {path.name}")

    document.pages = pages
    document.bytes = path.stat().st_size
    document.sha256 = sha256_file(path)
    document.qpdf_return_code = check.returncode
    document.company_identity_verified_when_text_extractable = identity_ok
    document.first_last_page_rendered = True


def detail_url(announcement_id: str) -> str:
    return f"https://data.eastmoney.com/notices/detail/300458/{announcement_id}.html"


def build_documents(
    annuals: list[dict[str, Any]],
    prospectus: dict[str, Any],
    quarter: dict[str, Any],
) -> list[Document]:
    documents: list[Document] = []
    for row in annuals:
        year = int(row["fiscal_year"])
        revised = any(
            token in row["title_norm"]
            for token in ("修订", "更新", "更正")
        )
        suffix = "_修订版" if revised else ""
        documents.append(
            Document(
                document_type="年度报告",
                report_period=str(year),
                title=row["title_norm"],
                publication_date=row["date_norm"],
                announcement_id=str(row["art_code"]),
                source_pdf_url="",
                source_detail_url=detail_url(str(row["art_code"])),
                relative_path=(
                    f"01_年度报告/{year}_{COMPANY}_年度报告全文{suffix}.pdf"
                ),
            )
        )

    documents.append(
        Document(
            document_type="招股说明书",
            report_period="IPO",
            title=prospectus["title_norm"],
            publication_date=prospectus["date_norm"],
            announcement_id=str(prospectus["art_code"]),
            source_pdf_url="",
            source_detail_url=detail_url(str(prospectus["art_code"])),
            relative_path=(
                "02_招股说明书/全志科技_首次公开发行股票并在创业板上市招股说明书.pdf"
            ),
        )
    )

    quarter_year_value = int(quarter["fiscal_year"])
    quarter_rank_value = int(quarter["quarter_rank"])
    quarter_code = f"{quarter_year_value}_Q{quarter_rank_value}"
    documents.append(
        Document(
            document_type="季度报告",
            report_period=quarter_code,
            title=quarter["title_norm"],
            publication_date=quarter["date_norm"],
            announcement_id=str(quarter["art_code"]),
            source_pdf_url="",
            source_detail_url=detail_url(str(quarter["art_code"])),
            relative_path=(
                f"03_最新季报/{quarter_code}_{COMPANY}_{quarter['quarter_label']}.pdf"
            ),
        )
    )
    return documents


def write_metadata(
    documents: list[Document],
    annuals: list[dict[str, Any]],
    prospectus: dict[str, Any],
    quarter: dict[str, Any],
) -> None:
    annual_years = [int(document.report_period) for document in documents if document.document_type == "年度报告"]
    latest = next(document for document in documents if document.document_type == "季度报告")
    note = f"""{COMPANY}（{STOCK_CODE}）官方披露文件包

公司全称：{FULL_COMPANY}
收录范围：
1. 上市以来全部完整年度报告：{annual_years[0]}—{annual_years[-1]}年度，共{len(annual_years)}份。
2. 首次公开发行股票并在创业板上市的正式招股说明书，共1份。
3. 截至{AS_OF}的最新严格季度报告：《{latest.title}》，披露日期为{latest.publication_date}。
4. 半年度报告不属于季度报告，因此未用于替代最新季报。
5. 已排除年度报告摘要、招股说明书申报稿/签章页/提示公告、半年报、审计附件及重复版本。

来源：东方财富上市公司公告索引及公开披露PDF镜像。
校验：PDF文件头、qpdf结构、实际页数、发行人身份、首末页渲染、SHA-256及ZIP CRC。
生成日期：{AS_OF}
PDF数量：{len(documents)}份
"""
    (SOURCE_DIR / "00_文件清单与范围说明.txt").write_text(note, encoding="utf-8")

    with (SOURCE_DIR / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "类别",
                "报告期",
                "文件标题",
                "披露日期",
                "实际页数",
                "文件大小（字节）",
                "SHA-256",
                "本地路径",
                "公告编号",
                "公开PDF地址",
                "公告详情地址",
            ]
        )
        for document in documents:
            writer.writerow(
                [
                    document.document_type,
                    document.report_period,
                    document.title,
                    document.publication_date,
                    document.pages,
                    document.bytes,
                    document.sha256,
                    document.relative_path,
                    document.announcement_id,
                    document.source_pdf_url,
                    document.source_detail_url,
                ]
            )

    manifest = {
        "company": COMPANY,
        "company_full_name": FULL_COMPANY,
        "stock_code": STOCK_CODE,
        "as_of": AS_OF,
        "source": "东方财富上市公司公告索引及公开披露PDF镜像",
        "scope": "上市以来全部年报 + 正式招股说明书 + 截至整理日最新严格季度报告",
        "annual_report_years": annual_years,
        "prospectus": prospectus["title_norm"],
        "prospectus_publication_date": prospectus["date_norm"],
        "latest_quarterly_report": latest.title,
        "latest_quarterly_report_date": latest.publication_date,
        "documents": [asdict(document) for document in documents],
        "selected_announcement_records": {
            "annual_reports": annuals,
            "prospectus": prospectus,
            "latest_quarter": quarter,
        },
    }
    (SOURCE_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (SOURCE_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(
            f"{document.sha256}  {document.relative_path}"
            for document in documents
        )
        + "\n",
        encoding="utf-8",
    )


def create_zip() -> None:
    ZIP_PATH.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(ROOT.parent))
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")


def main() -> None:
    for path in (ROOT, WORK_DIR):
        if path.exists():
            shutil.rmtree(path)
    ZIP_PATH.unlink(missing_ok=True)
    SUMMARY_PATH.unlink(missing_ok=True)
    for directory in (
        ANNUAL_DIR,
        PROSPECTUS_DIR,
        QUARTER_DIR,
        SOURCE_DIR,
        RENDER_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    rows = fetch_notice_rows()
    annuals = [select_annual(rows, year) for year in ANNUAL_YEARS]
    prospectus = select_prospectus(rows)
    quarter = select_latest_quarter(rows)
    documents = build_documents(annuals, prospectus, quarter)

    for document in documents:
        destination = ROOT / document.relative_path
        document.source_pdf_url = download_pdf(document.announcement_id, destination)
        validate_pdf(destination, document)
        print(
            "VALIDATED",
            json.dumps(
                {
                    "type": document.document_type,
                    "period": document.report_period,
                    "title": document.title,
                    "publication_date": document.publication_date,
                    "pages": document.pages,
                    "bytes": document.bytes,
                    "sha256": document.sha256,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    write_metadata(documents, annuals, prospectus, quarter)
    create_zip()

    summary = {
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256_file(ZIP_PATH),
        "pdf_count": len(documents),
        "documents": [
            {
                "type": document.document_type,
                "period": document.report_period,
                "title": document.title,
                "publication_date": document.publication_date,
                "pages": document.pages,
                "bytes": document.bytes,
            }
            for document in documents
        ],
        "scope": "上市以来全部年报 + 正式招股说明书 + 最新严格季度报告",
        "latest_quarterly_report": next(
            document.title
            for document in documents
            if document.document_type == "季度报告"
        ),
    }
    SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("PACKAGE_SUMMARY=" + json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
