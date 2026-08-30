from __future__ import annotations

import hashlib
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import requests
from pypdf import PdfReader

ROOT = Path.cwd()
PACKAGE = ROOT / "biyi_broker_reports_verified"
REPORT_DIR = PACKAGE / "01_券商深度报告"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT = ROOT / "必易微_券商深度报告_3份_完整PDF.zip"
STOCK_CODE = "688045"
COMPANY = "深圳市必易微电子股份有限公司"
SHORT_NAME = "必易微"
PREPARED_DATE = "2026-08-30"

session = requests.Session()
session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://data.eastmoney.com/",
    }
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def safe_filename(text: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:150]


def parse_jsonp(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(stripped)
    match = re.search(r"^[^(]*\((.*)\)\s*;?\s*$", stripped, flags=re.S)
    if not match:
        raise RuntimeError(f"Unable to parse JSONP response: {stripped[:300]}")
    return json.loads(match.group(1))


def fetch_report_records() -> list[dict[str, Any]]:
    url = "https://reportapi.eastmoney.com/report/list"
    params = {
        "cb": "datatable",
        "pageSize": 100,
        "industryCode": "*",
        "pageNo": 1,
        "fields": "",
        "qType": 0,
        "orgCode": "",
        "code": STOCK_CODE,
        "rcode": "",
        "p": 1,
        "pageNum": 1,
        "pageNumber": 1,
        "_": str(int(time.time() * 1000)),
    }
    response = session.get(url, params=params, timeout=(30, 180))
    response.raise_for_status()
    payload = parse_jsonp(response.text)

    candidates: list[Any] = []
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        for key in ("data", "result", "items", "list"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates = value
                break
            if isinstance(value, dict):
                for nested_key in ("data", "items", "list"):
                    nested = value.get(nested_key)
                    if isinstance(nested, list):
                        candidates = nested
                        break
            if candidates:
                break

    if not candidates:
        raise RuntimeError(
            "Eastmoney report API returned no list; keys="
            + (str(list(payload.keys())) if isinstance(payload, dict) else type(payload).__name__)
        )

    records: list[dict[str, Any]] = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        info_code = str(
            raw.get("infoCode")
            or raw.get("infocode")
            or raw.get("INFOCODE")
            or raw.get("artCode")
            or raw.get("articleCode")
            or ""
        ).strip()
        title = str(raw.get("title") or raw.get("TITLE") or "").strip()
        if not info_code.startswith("AP") or not title:
            continue
        org = str(
            raw.get("orgSName")
            or raw.get("orgName")
            or raw.get("ORG_SNAME")
            or raw.get("ORG_NAME")
            or "未知券商"
        ).strip()
        publish_date = str(
            raw.get("publishDate")
            or raw.get("publishDateStr")
            or raw.get("PUBLISH_DATE")
            or raw.get("date")
            or ""
        ).strip()
        researcher = str(
            raw.get("researcher")
            or raw.get("researcherName")
            or raw.get("RESEARCHER")
            or ""
        ).strip()
        records.append(
            {
                "info_code": info_code,
                "title": title,
                "broker": org,
                "publish_date": publish_date[:10],
                "researcher": researcher,
                "metadata": raw,
            }
        )

    unique: dict[str, dict[str, Any]] = {record["info_code"]: record for record in records}
    result = list(unique.values())
    print(f"Eastmoney API records: {len(result)}")
    for record in result:
        print(
            f"{record['info_code']} | {record['publish_date']} | "
            f"{record['broker']} | {record['title']}"
        )
    return result


def pdf_urls(info_code: str) -> list[str]:
    base = f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"
    return [
        base,
        f"{base}?{int(time.time() * 1000)}.pdf=",
        f"http://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
    ]


def download_pdf(record: dict[str, Any], target: Path) -> str:
    errors: list[str] = []
    for url in pdf_urls(record["info_code"]):
        for attempt in range(1, 4):
            part = target.with_suffix(target.suffix + ".part")
            part.unlink(missing_ok=True)
            try:
                with session.get(
                    url,
                    headers={
                        "Referer": f"https://data.eastmoney.com/report/info/{record['info_code']}.html",
                        "Accept": "application/pdf,*/*;q=0.8",
                    },
                    stream=True,
                    timeout=(30, 300),
                    allow_redirects=True,
                ) as response:
                    response.raise_for_status()
                    with part.open("wb") as handle:
                        for chunk in response.iter_content(1024 * 1024):
                            if chunk:
                                handle.write(chunk)
                if part.stat().st_size < 150_000:
                    raise RuntimeError(f"file too small: {part.stat().st_size}")
                with part.open("rb") as handle:
                    if handle.read(5) != b"%PDF-":
                        raise RuntimeError("response is not a PDF")
                part.replace(target)
                return url
            except Exception as exc:
                part.unlink(missing_ok=True)
                errors.append(f"{url} attempt {attempt}: {exc}")
                time.sleep(attempt)
    raise RuntimeError(
        f"Unable to download {record['info_code']} {record['title']}: "
        + " | ".join(errors)
    )


def inspect_pdf(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    reader = PdfReader(str(path))
    if reader.is_encrypted and reader.decrypt("") == 0:
        raise RuntimeError(f"Encrypted PDF cannot be opened: {path}")
    pages = len(reader.pages)
    if pages < 3:
        raise RuntimeError(f"Unexpectedly short report: {path} ({pages} pages)")

    document = fitz.open(path)
    if document.page_count != pages:
        raise RuntimeError(f"Page-count mismatch: {path}")
    sample_text = "\n".join(
        document.load_page(index).get_text("text")
        for index in sorted(set(range(min(20, pages))) | {pages // 2, pages - 1})
    )
    compact = normalize(sample_text)
    if not any(marker in compact for marker in ("必易微", STOCK_CODE, COMPANY)):
        raise RuntimeError(f"Company marker missing: {path}")
    if not any(marker in compact for marker in ("证券研究报告", "公司研究", "深度报告", "首次覆盖", "新股专题")):
        raise RuntimeError(f"Broker-research marker missing: {path}")

    for index in sorted({0, pages // 2, pages - 1}):
        pixmap = document.load_page(index).get_pixmap(
            matrix=fitz.Matrix(0.5, 0.5), alpha=False
        )
        if pixmap.width < 150 or pixmap.height < 150:
            raise RuntimeError(f"Render check failed: {path}, page {index + 1}")
    document.close()

    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def quality_score(record: dict[str, Any], pages: int) -> float:
    title = normalize(record["title"])
    score = float(pages)
    if "深度" in title:
        score += 120
    if "首次覆盖" in title or "专题覆盖" in title or "新股专题" in title:
        score += 70
    if any(keyword in title for keyword in (
        "ac-dc为基",
        "bmsafe",
        "高景气赛道",
        "全品类模拟平台",
        "共同推进公司成长",
    )):
        score += 50
    if any(keyword in title for keyword in (
        "点评", "一季报", "半年报", "三季报", "年报点评", "快报", "股权激励", "调研"
    )):
        score -= 100
    # Prefer genuinely substantial reports.
    if pages >= 25:
        score += 40
    elif pages >= 15:
        score += 20
    return score


def main() -> None:
    records = fetch_report_records()

    # Ensure several historically substantive reports remain discoverable even if the API
    # changes ordering or pagination. Metadata is completed from the API when available.
    fallback_records = [
        {
            "info_code": "AP202303081584118467",
            "title": "景气复苏+DCDC/BMSAFE等新品放量，共同推进公司成长",
            "broker": "华安证券",
            "publish_date": "2023-03-08",
            "researcher": "胡杨",
            "metadata": {},
        },
        {
            "info_code": "AP202205091564579151",
            "title": "新股专题覆盖：必易微（2022年第44期）",
            "broker": "华金证券",
            "publish_date": "2022-05-09",
            "researcher": "李蕙",
            "metadata": {},
        },
    ]
    by_code = {record["info_code"]: record for record in records}
    for fallback in fallback_records:
        by_code.setdefault(fallback["info_code"], fallback)

    # Download all plausible substantial reports, then rank by verified page count.
    plausible: list[dict[str, Any]] = []
    for record in by_code.values():
        title = normalize(record["title"])
        if any(keyword in title for keyword in (
            "深度", "首次覆盖", "专题覆盖", "新股专题", "高景气赛道",
            "全品类模拟平台", "共同推进公司成长", "ac-dc为基", "bmsafe"
        )):
            plausible.append(record)

    if len(plausible) < 3:
        # Add older company reports, but exclude obvious short event comments.
        for record in by_code.values():
            title = normalize(record["title"])
            if record in plausible:
                continue
            if any(keyword in title for keyword in (
                "点评", "一季报", "半年报", "三季报", "快报", "股权激励", "调研"
            )):
                continue
            plausible.append(record)

    inspected: list[dict[str, Any]] = []
    temp_dir = ROOT / "_biyi_candidate_reports"
    temp_dir.mkdir(exist_ok=True)

    for record in plausible:
        target = temp_dir / f"{record['info_code']}.pdf"
        try:
            source_url = download_pdf(record, target)
            metadata = inspect_pdf(target, record)
            if metadata["pages"] < 10:
                print(f"Skip short report ({metadata['pages']} pages): {record['title']}")
                continue
            inspected.append(
                {
                    **record,
                    **metadata,
                    "source_url": source_url,
                    "temp_path": target,
                    "score": quality_score(record, metadata["pages"]),
                }
            )
            print(
                f"Candidate: {metadata['pages']} pages | score={inspected[-1]['score']:.1f} | "
                f"{record['broker']} | {record['title']}"
            )
        except Exception as exc:
            print(f"Candidate failed: {record['info_code']} {record['title']} | {exc}")

    inspected.sort(
        key=lambda item: (item["score"], item["pages"], item["publish_date"]),
        reverse=True,
    )

    selected: list[dict[str, Any]] = []
    used_brokers: set[str] = set()
    for item in inspected:
        broker_key = normalize(item["broker"])
        if broker_key in used_brokers:
            continue
        selected.append(item)
        used_brokers.add(broker_key)
        if len(selected) == 3:
            break

    if len(selected) < 2:
        raise RuntimeError(
            f"Only {len(selected)} substantive reports were verified; candidates={[(x['title'], x['pages']) for x in inspected]}"
        )

    documents: list[dict[str, Any]] = []
    for index, item in enumerate(selected, 1):
        date_text = item["publish_date"].replace("-", "") or "日期未知"
        filename = safe_filename(
            f"{index:02d}_{item['broker']}_{date_text}_{item['title']}.pdf"
        )
        target = REPORT_DIR / filename
        target.write_bytes(Path(item["temp_path"]).read_bytes())
        documents.append(
            {
                "company": SHORT_NAME,
                "stock_code": STOCK_CODE,
                "broker": item["broker"],
                "title": item["title"],
                "publish_date": item["publish_date"],
                "researcher": item["researcher"],
                "file": str(target.relative_to(PACKAGE)),
                "pages": item["pages"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
                "source_page": f"https://data.eastmoney.com/report/info/{item['info_code']}.html",
                "source_pdf": item["source_url"],
                "info_code": item["info_code"],
            }
        )

    total_pages = sum(item["pages"] for item in documents)
    total_bytes = sum(item["bytes"] for item in documents)

    readme_lines = [
        f"{COMPANY}（{STOCK_CODE}.SH，{SHORT_NAME}）券商深度/专题研究报告",
        f"整理日期：{PREPARED_DATE}",
        "",
        "筛选口径",
        "1. 优先选择公开可下载、篇幅较完整的公司深度、首次覆盖或专题覆盖报告。",
        "2. 排除仅数页的普通业绩点评、季报点评和资讯摘要。",
        "3. 尽量选择不同券商，便于交叉比较研究框架与盈利预测。",
        "",
        "文件清单",
    ]
    checksum_lines: list[str] = []
    for index, item in enumerate(documents, 1):
        readme_lines.extend(
            [
                f"{index}. {item['broker']}：{item['title']}",
                f"   发布日期：{item['publish_date']}",
                f"   研究员：{item['researcher'] or '未记录'}",
                f"   页数：{item['pages']}",
                f"   文件：{item['file']}",
                f"   来源页面：{item['source_page']}",
                f"   SHA-256：{item['sha256']}",
                "",
            ]
        )
        checksum_lines.append(f"{item['sha256']}  {item['file']}")

    readme_lines.extend(
        [
            "完整性检查",
            f"- 共{len(documents)}份PDF，合计{total_pages}页，未压缩总大小{total_bytes / 1024 / 1024:.2f} MiB。",
            "- 每份PDF均检查文件头、结构、页数、公司名称及证券研究报告标识。",
            "- 已渲染抽查每份PDF的首页、中间页和末页。",
            "- ZIP已通过CRC完整性测试，逐文件哈希见SHA256SUMS.txt。",
        ]
    )

    (PACKAGE / "README_来源与校验.txt").write_text(
        "\n".join(readme_lines), encoding="utf-8"
    )
    (PACKAGE / "SHA256SUMS.txt").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8"
    )
    (PACKAGE / "manifest.json").write_text(
        json.dumps(
            {
                "company": COMPANY,
                "short_name": SHORT_NAME,
                "ticker": f"{STOCK_CODE}.SH",
                "prepared_date": PREPARED_DATE,
                "documents": documents,
                "total_pages": total_pages,
                "total_bytes": total_bytes,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    with zipfile.ZipFile(
        OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in sorted(PACKAGE.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(path.relative_to(PACKAGE)))

    with zipfile.ZipFile(OUTPUT, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")
        pdfs = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
        if len(pdfs) != len(documents):
            raise RuntimeError(f"Expected {len(documents)} PDFs, found {len(pdfs)}")

    print("\n".join(readme_lines))
    print(f"ZIP_FILE={OUTPUT}")
    print(f"ZIP_BYTES={OUTPUT.stat().st_size}")
    print(f"ZIP_SHA256={sha256(OUTPUT)}")


if __name__ == "__main__":
    main()
