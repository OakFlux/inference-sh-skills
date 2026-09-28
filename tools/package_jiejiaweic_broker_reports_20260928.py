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

import requests
from pypdf import PdfReader

COMPANY = "捷佳伟创"
CODE = "300724"
ROOT = Path("捷佳伟创_300724_券商深度报告_3份")
REPORT_DIR = ROOT / "01_券商深度报告"
NOTES_DIR = ROOT / "02_资料说明"
TMP_DIR = Path("_tmp_jiejiaweic_broker_reports")
PREVIEW_DIR = Path("_previews_jiejiaweic_broker_reports")
ZIP_PATH = Path("捷佳伟创_300724_券商深度报告_3份.zip")
RESULT_JSON = Path("jiejiaweic_broker_reports_result.json")

REPORTS = [
    {
        "priority": 1,
        "info_code": "AP202311011607622138",
        "institution": "国金证券",
        "date": "2023-11-01",
        "title": "乘技术变革之风，筑造光伏电池设备平台",
        "authors": "姚遥",
        "rating": "买入",
        "filename": "01_国金证券_2023-11-01_乘技术变革之风_筑造光伏电池设备平台.pdf",
        "min_pages": 15,
    },
    {
        "priority": 2,
        "info_code": "AP202110291525773077",
        "institution": "东莞证券",
        "date": "2021-10-29",
        "title": "深度报告：高效电池汹涌而至，设备龙头顺势腾飞",
        "authors": "黄秀瑜、刘兴文",
        "rating": "买入",
        "filename": "02_东莞证券_2021-10-29_高效电池汹涌而至_设备龙头顺势腾飞.pdf",
        "min_pages": 15,
    },
    {
        "priority": 3,
        "info_code": "AP202007061389843374",
        "institution": "世纪证券",
        "date": "2020-07-06",
        "title": "深度研究报告：电池片设备龙头，持续受益光伏产业发展",
        "authors": "赵晓闯",
        "rating": "增持",
        "filename": "03_世纪证券_2020-07-06_电池片设备龙头_持续受益光伏产业发展.pdf",
        "min_pages": 12,
    },
    {
        "priority": 4,
        "info_code": "AP202004271378714457",
        "institution": "信达证券",
        "date": "2020-04-27",
        "title": "深度报告：受益光伏产业大趋势，新工艺多点开花",
        "authors": "罗政",
        "rating": "增持",
        "filename": "04_信达证券_2020-04-27_受益光伏产业大趋势_新工艺多点开花.pdf",
        "min_pages": 12,
    },
    {
        "priority": 5,
        "info_code": "AP202002121375026583",
        "institution": "申港证券",
        "date": "2020-02-12",
        "title": "光伏‘平价上网’核心设备供应商",
        "authors": "夏纾雨",
        "rating": "买入",
        "filename": "05_申港证券_2020-02-12_光伏平价上网核心设备供应商.pdf",
        "min_pages": 12,
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_url(value: str) -> str:
    value = html.unescape(value).replace("\\/", "/")
    value = value.strip().strip('"\'')
    return value.rstrip("\\,;)]}")


def discover_pdf_urls(session: requests.Session, report: dict[str, Any]) -> list[str]:
    code = report["info_code"]
    page_url = f"https://data.eastmoney.com/report/info/{code}.html"
    urls: list[str] = []
    try:
        response = session.get(
            page_url,
            headers={**HEADERS, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
            timeout=120,
        )
        print("REPORT_PAGE", code, response.status_code, response.url, len(response.content), flush=True)
        response.raise_for_status()
        text = html.unescape(response.text).replace("\\/", "/")
        patterns = [
            r"https?://pdf\.dfcfw\.com/pdf/[^\s\"'<>]+",
            r"//pdf\.dfcfw\.com/pdf/[^\s\"'<>]+",
            rf"https?://[^\s\"'<>]*{re.escape(code)}[^\s\"'<>]*\.pdf[^\s\"'<>]*",
        ]
        for pattern in patterns:
            for match in re.findall(pattern, text, flags=re.I):
                url = clean_url(match)
                if url.startswith("//"):
                    url = "https:" + url
                elif url.startswith("/"):
                    url = urljoin(str(response.url), url)
                if code in url and url not in urls:
                    urls.append(url)
    except Exception as exc:
        print("REPORT_PAGE_WARNING", code, repr(exc), flush=True)

    stamp = int(time.time() * 1000)
    constructed = [
        f"https://pdf.dfcfw.com/pdf/H3_{code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{code}_1.pdf?{stamp}.pdf=",
        f"https://pdf.dfcfw.com/pdf/H3_{code}_1.pdf?{stamp}",
        f"https://pdf.dfcfw.com/pdf/H3_{code}_1.pdf?{code}.pdf=",
    ]
    for url in constructed:
        if url not in urls:
            urls.append(url)
    print("PDF_CANDIDATES", code, json.dumps(urls, ensure_ascii=False), flush=True)
    return urls


def download_pdf(session: requests.Session, report: dict[str, Any], destination: Path) -> str:
    page_url = f"https://data.eastmoney.com/report/info/{report['info_code']}.html"
    last_error: Exception | None = None
    for url in discover_pdf_urls(session, report):
        for attempt in range(1, 4):
            part = destination.with_suffix(destination.suffix + ".part")
            try:
                if part.exists():
                    part.unlink()
                headers = {
                    **HEADERS,
                    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
                    "Referer": page_url,
                }
                with session.get(url, headers=headers, stream=True, timeout=(45, 240), allow_redirects=True) as response:
                    print(
                        "PDF_RESPONSE",
                        report["info_code"],
                        attempt,
                        response.status_code,
                        response.url,
                        response.headers.get("content-type"),
                        response.headers.get("content-length"),
                        flush=True,
                    )
                    response.raise_for_status()
                    with part.open("wb") as stream:
                        for chunk in response.iter_content(1024 * 1024):
                            if chunk:
                                stream.write(chunk)
                size = part.stat().st_size
                if size < 150_000:
                    raise RuntimeError(f"PDF文件过小：{size}")
                with part.open("rb") as stream:
                    if stream.read(5) != b"%PDF-":
                        raise RuntimeError("下载内容不是PDF")
                part.replace(destination)
                print("PDF_DOWNLOADED", destination, size, url, flush=True)
                return url
            except Exception as exc:
                last_error = exc
                print("PDF_RETRY", report["info_code"], attempt, url, repr(exc), flush=True)
                time.sleep(attempt * 2)
    raise RuntimeError(f"无法下载{report['title']}：{last_error!r}")


def validate_pdf(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < int(report["min_pages"]):
        raise RuntimeError(f"{path.name}页数仅{pages}，不符合深度报告特征")

    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=240,
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf校验失败：{path.name}: {qpdf.stderr[-1000:]}")

    text_parts: list[str] = []
    for page in reader.pages[: min(pages, 12)]:
        try:
            text_parts.append(page.extract_text() or "")
        except Exception as exc:
            print("TEXT_EXTRACT_WARNING", path.name, repr(exc), flush=True)
    compact_text = re.sub(r"\s+", "", "".join(text_parts))
    identity_match = COMPANY in compact_text or CODE in compact_text
    institution_match = report["institution"] in compact_text
    if len(compact_text) > 500 and not identity_match:
        raise RuntimeError(f"报告文本未识别到{COMPANY}或{CODE}：{path.name}")

    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    preview_base = PREVIEW_DIR / path.stem
    subprocess.run(
        ["pdftoppm", "-f", "1", "-singlefile", "-png", "-r", "140", str(path), str(preview_base)],
        check=True,
        timeout=240,
        capture_output=True,
    )
    preview = preview_base.with_suffix(".png")
    if not preview.exists() or preview.stat().st_size < 8_000:
        raise RuntimeError(f"首页渲染失败：{path.name}")

    result = {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "identity_text_match": identity_match,
        "institution_text_match": institution_match,
        "first_page_preview": str(preview),
    }
    print("PDF_VALIDATED", path.name, json.dumps(result, ensure_ascii=False), flush=True)
    return result


def reset_outputs() -> None:
    for path in (ROOT, TMP_DIR, PREVIEW_DIR):
        if path.exists():
            shutil.rmtree(path)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    if RESULT_JSON.exists():
        RESULT_JSON.unlink()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)


def build_package() -> None:
    reset_outputs()
    session = requests.Session()
    session.headers.update(HEADERS)

    selected: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for report in REPORTS:
        if len(selected) >= 3:
            break
        temp_path = TMP_DIR / report["filename"]
        try:
            source_pdf_url = download_pdf(session, report, temp_path)
            validation = validate_pdf(temp_path, report)
            final_number = len(selected) + 1
            final_name = re.sub(r"^\d{2}_", f"{final_number:02d}_", report["filename"])
            final_path = REPORT_DIR / final_name
            shutil.move(str(temp_path), str(final_path))
            record = {
                **report,
                **validation,
                "filename": str(final_path.relative_to(ROOT)),
                "report_page_url": f"https://data.eastmoney.com/report/info/{report['info_code']}.html",
                "source_pdf_url": source_pdf_url,
                "document_type": "券商原始排版PDF",
            }
            selected.append(record)
        except Exception as exc:
            errors.append({"info_code": report["info_code"], "title": report["title"], "error": repr(exc)})
            print("REPORT_FAILED", report["info_code"], repr(exc), flush=True)

    if len(selected) < 3:
        raise RuntimeError(f"仅成功取得{len(selected)}份报告；错误：{errors}")

    manifest = {
        "company": COMPANY,
        "stock_code": CODE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "report_count": len(selected),
        "reports": selected,
        "fallback_errors": errors,
        "validation": "PDF文件头、页数、qpdf结构、文本身份匹配（可提取时）及首页渲染均已检查。",
    }
    (NOTES_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (NOTES_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{item['sha256']}  {item['filename']}" for item in selected) + "\n",
        encoding="utf-8",
    )

    lines = [
        f"公司：{COMPANY}（{CODE}.SZ）",
        f"券商深度报告：{len(selected)}份",
        "",
    ]
    for index, item in enumerate(selected, start=1):
        size_mb = item["bytes"] / 1024 / 1024
        lines.extend(
            [
                f"{index}. {item['institution']}《{item['title']}》",
                f"   日期：{item['date']}；作者：{item['authors']}；评级：{item['rating']}",
                f"   页数：{item['pages']}页；文件大小：{size_mb:.2f} MB",
                f"   东方财富研报编号：{item['info_code']}",
                f"   文件：{item['filename']}",
                "",
            ]
        )
    lines.extend(
        [
            "文件说明：",
            "- 压缩包仅收录券商原始排版PDF，不以网页摘要或自制整理版替代。",
            "- 各PDF均完成文件头、页数、结构和首页渲染检查。",
            "- 来源页和原始PDF地址记录在manifest.json中。",
        ]
    )
    (NOTES_DIR / "资料清单与来源说明.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.as_posix())
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise RuntimeError(f"ZIP成员损坏：{bad_member}")

    result = {
        "zip_filename": ZIP_PATH.name,
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256(ZIP_PATH),
        "report_count": len(selected),
        "reports": selected,
        "fallback_errors": errors,
    }
    RESULT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PACKAGE_COMPLETE", json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    build_package()
