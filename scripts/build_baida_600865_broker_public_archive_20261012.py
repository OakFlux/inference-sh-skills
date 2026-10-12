from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

CHECK_DATE = "2026-10-12"
COMPANY = "百大集团"
STOCK_CODE = "600865"
PACKAGE = f"百大集团_{STOCK_CODE}_券商深度报告_3份_公开索引存档版_{CHECK_DATE}"
ROOT = Path(PACKAGE)
REPORT_DIR = ROOT / "01_报告索引存档"
SOURCE_DIR = ROOT / "02_来源入口"
VERIFY_DIR = ROOT / "03_说明与校验"
WORK_DIR = Path("_baida_600865_broker_archive_work")
RENDER_DIR = WORK_DIR / "renders"
ZIP_PATH = Path(PACKAGE + ".zip")
for directory in (REPORT_DIR, SOURCE_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

REPORTS: list[dict[str, Any]] = [
    {
        "order": 1,
        "doc_id": 1694746,
        "institution": "安信证券",
        "title": "筹建医疗中心转型大健康产业，多元化布局抒写发展新篇章",
        "date": "2015-10-26",
        "analysts": "刘章明",
        "category": "公司调研",
        "rating": "",
        "summary": "报告围绕公司与浙江省肿瘤医院合作筹建医疗中心展开，评估医疗服务转型及多元业务布局的推进空间。",
        "output_name": "01_安信证券_百大集团_筹建医疗中心转型大健康产业_公开索引存档.pdf",
    },
    {
        "order": 2,
        "doc_id": 1718411,
        "institution": "民生证券",
        "title": "调研报告：打造高端肿瘤医院，零售+医疗双轮驱动",
        "date": "2015-11-29",
        "analysts": "马科",
        "category": "公司调研",
        "rating": "",
        "summary": "报告考察公司医疗中心规划及与浙江省肿瘤医院的合作，讨论传统零售与医疗服务协同发展的可能性。",
        "output_name": "02_民生证券_百大集团_打造高端肿瘤医院_零售医疗双轮驱动_公开索引存档.pdf",
    },
    {
        "order": 3,
        "doc_id": 1794762,
        "institution": "西南证券",
        "title": "主业稳健经营，医疗健康持续推进",
        "date": "2016-03-31",
        "analysts": "朱国广、施跃",
        "category": "公司调研",
        "rating": "增持",
        "summary": "报告结合2015年度经营数据，分析零售主业的稳定性以及医疗健康项目的后续推进节奏。",
        "output_name": "03_西南证券_百大集团_主业稳健经营医疗健康持续推进_公开索引存档.pdf",
    },
]

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request(method: str, url: str, **kwargs: Any) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 10):
        try:
            response = SESSION.request(
                method,
                url,
                timeout=(20, 120),
                allow_redirects=True,
                **kwargs,
            )
            print(
                "HTTP", method, url, "attempt", attempt, "status", response.status_code,
                "type", response.headers.get("content-type"), "bytes", len(response.content),
                "final", response.url,
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            time.sleep(min(2 * attempt, 12))
    raise RuntimeError(f"request failed for {method} {url}: {errors[-9:]}")


def variable(text: str, name: str) -> str:
    match = re.search(rf"var\s+{re.escape(name)}\s*=\s*'((?:\\'|[^'])*)'", text, flags=re.S)
    if not match:
        return ""
    return html.unescape(match.group(1).replace("\\'", "'")).strip()


def visible_text(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def regex_first(patterns: list[str], text: str, fallback: str = "") -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I | re.S)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return fallback


def fetch_public_metadata(report: dict[str, Any]) -> dict[str, Any]:
    source_url = f"https://www.hibor.com.cn/docdetail_{report['doc_id']}.html"
    page = request("GET", source_url)
    try:
        landing_html = page.text
        final_url = str(page.url)
    finally:
        page.close()
    ncid = regex_first([r"var\s+ncid\s*=\s*'([^']+)'"], landing_html)
    if not ncid:
        raise RuntimeError(f"ncid not found for Hibor document {report['doc_id']}")

    content_html = ""
    endpoint = "https://www.hibor.com.cn/hiborweb/DocDetail/NewContent"
    for attempt in range(1, 13):
        response = request(
            "POST",
            endpoint,
            data={"ncid": ncid},
            headers={"Referer": final_url, "X-Requested-With": "XMLHttpRequest"},
        )
        try:
            candidate = response.text
        finally:
            response.close()
        if len(candidate.encode("utf-8")) > 10_000 and ("metaTitle" in candidate or COMPANY in candidate):
            content_html = candidate
            break
        print("EMPTY_CONTENT_RETRY", report["doc_id"], attempt, len(candidate), flush=True)
        time.sleep(min(attempt, 5))
    if not content_html:
        raise RuntimeError(f"public Hibor metadata page unavailable for document {report['doc_id']}")

    text = visible_text(content_html)
    meta_title = variable(content_html, "metaTitle")
    meta_keywords = variable(content_html, "metaKeywords")
    meta_description = variable(content_html, "metaDescription")

    date_value = regex_first([
        r"日期[：:]\s*([0-9]{4}-[0-9]{2}-[0-9]{2}(?:\s+[0-9:]+)?)",
    ], text, report["date"])
    institution = regex_first([r"研报出处[：:]\s*([^\s]+)"], text, report["institution"])
    stock_name = regex_first([r"股票名称[：:]\s*([^\s]+)"], text, COMPANY)
    stock_code = regex_first([r"股票代码[：:]\s*([0-9]{6})"], text, STOCK_CODE)
    category = regex_first([r"研报栏目[：:]\s*([^\s]+)"], text, report["category"])
    pdf_pages = regex_first([r"\(PDF\)\s*([0-9]+)\s*页"], text)
    pdf_size = regex_first([r"\(PDF\)\s*[0-9]+\s*页\s*([0-9.]+\s*(?:KB|MB))"], text)
    rating = regex_first([r"推荐评级[：:]\s*([^\s]+)"], text, report["rating"])

    keyword_parts = [part.strip() for part in meta_keywords.split(",") if part.strip()]
    analysts = report["analysts"]
    if len(keyword_parts) > 3:
        analysts = "、".join(keyword_parts[3:])

    title = report["title"]
    if meta_title:
        cleaned_title = meta_title
        for prefix in (f"{institution}-{COMPANY}-{STOCK_CODE}-", f"{report['institution']}-{COMPANY}-{STOCK_CODE}-"):
            if cleaned_title.startswith(prefix):
                cleaned_title = cleaned_title[len(prefix):]
        cleaned_title = re.sub(r"-(?:公司调研|公司研究|公司点评|慧博投研资讯).*$", "", cleaned_title)
        cleaned_title = cleaned_title.strip(" -") or title
        title = cleaned_title

    return {
        "source_url": source_url,
        "landing_final_url": final_url,
        "ncid": ncid,
        "meta_title": meta_title,
        "meta_keywords": meta_keywords,
        "meta_description": meta_description,
        "institution": institution,
        "title": title,
        "date": date_value,
        "stock_name": stock_name,
        "stock_code": stock_code,
        "category": category,
        "analysts": analysts,
        "rating": rating,
        "original_pdf_pages_declared": int(pdf_pages) if pdf_pages else None,
        "original_pdf_size_declared": pdf_size,
        "public_page_bytes": len(content_html.encode("utf-8")),
        "delivery_status": "公开索引存档版；未取得券商原始PDF全文",
    }


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=False)


def build_pdf(report: dict[str, Any], metadata: dict[str, Any], destination: Path) -> None:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleCN",
        parent=styles["Title"],
        fontName="STSong-Light",
        fontSize=18,
        leading=26,
        alignment=TA_CENTER,
        spaceAfter=10 * mm,
    )
    subtitle_style = ParagraphStyle(
        "SubtitleCN",
        parent=styles["Heading2"],
        fontName="STSong-Light",
        fontSize=12,
        leading=18,
        alignment=TA_CENTER,
        spaceAfter=6 * mm,
    )
    body_style = ParagraphStyle(
        "BodyCN",
        parent=styles["BodyText"],
        fontName="STSong-Light",
        fontSize=10.5,
        leading=17,
        alignment=TA_LEFT,
        spaceAfter=4 * mm,
        wordWrap="CJK",
    )
    small_style = ParagraphStyle(
        "SmallCN",
        parent=body_style,
        fontSize=8.5,
        leading=13,
    )
    heading_style = ParagraphStyle(
        "HeadingCN",
        parent=styles["Heading2"],
        fontName="STSong-Light",
        fontSize=13,
        leading=20,
        spaceBefore=5 * mm,
        spaceAfter=3 * mm,
    )

    doc = SimpleDocTemplate(
        str(destination),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=metadata["title"],
        author="公开信息存档整理",
        subject=f"{COMPANY}（{STOCK_CODE}）券商研报公开索引",
    )

    story: list[Any] = []
    story.append(Paragraph(esc(metadata["institution"]), subtitle_style))
    story.append(Paragraph(esc(metadata["title"]), title_style))
    story.append(Paragraph(f"{COMPANY}（{STOCK_CODE}）券商研究资料公开索引存档", subtitle_style))

    rows = [
        ["项目", "公开页面信息"],
        ["研究机构", metadata["institution"]],
        ["报告日期", metadata["date"]],
        ["分析师", metadata["analysts"] or "公开页面未识别"],
        ["报告类别", metadata["category"]],
        ["推荐评级", metadata["rating"] or "公开页面未识别"],
        ["原报告页数", str(metadata["original_pdf_pages_declared"] or "公开页面未识别")],
        ["原报告文件大小", metadata["original_pdf_size_declared"] or "公开页面未识别"],
        ["交付状态", metadata["delivery_status"]],
    ]
    table_data = [[Paragraph(esc(cell), body_style) for cell in row] for row in rows]
    table = Table(table_data, colWidths=[42 * mm, 112 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("LEADING", (0, 0), (-1, -1), 14),
        ("GRID", (0, 0), (-1, -1), 0.5, None),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), None),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)

    story.append(Paragraph("公开信息概述", heading_style))
    story.append(Paragraph(esc(report["summary"]), body_style))

    story.append(Paragraph("公开页面描述", heading_style))
    description = metadata["meta_description"].strip()
    if description:
        # Store only a short excerpt; the file is an index record rather than a substitute for the report.
        excerpt = description[:120].rstrip("，。；; ") + ("……" if len(description) > 120 else "")
        story.append(Paragraph(esc(excerpt), body_style))
    else:
        story.append(Paragraph("公开页面未返回可用的内容描述。", body_style))

    story.append(PageBreak())
    story.append(Paragraph("来源与使用说明", heading_style))
    source_lines = [
        f"公开索引页面：{metadata['source_url']}",
        f"页面跳转地址：{metadata['landing_final_url']}",
        f"页面记录编号：{report['doc_id']}",
        f"存档核对日期：{CHECK_DATE}",
    ]
    for line in source_lines:
        story.append(Paragraph(esc(line), small_style))

    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(
        "本PDF只保存公开可核验的报告题名、机构、日期、作者、页数、评级及极短内容概述。"
        "原始券商PDF在公开访问环境中需要登录或相应下载权限，故未收入本压缩包。"
        "本文件不是券商原版报告，也不替代原报告；报告著作权及其他权利归相应权利人。",
        body_style,
    ))
    story.append(Paragraph(
        "选择这些报告的理由：三份资料均以百大集团为研究对象，集中讨论公司在2015—2016年由传统零售向医疗健康服务延伸的战略阶段，"
        "其中两份为调研性质资料，一份结合年度经营表现跟踪医疗项目进展。",
        body_style,
    ))
    doc.build(story)


def render_page(path: Path, page_number: int, tag: str) -> None:
    prefix = RENDER_DIR / f"{hashlib.sha1(str(path).encode()).hexdigest()}_{tag}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
            "-r", "96", "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    png = Path(str(prefix) + ".png")
    valid = (
        process.returncode == 0
        and png.exists()
        and png.stat().st_size > 1500
        and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(f"render failed for {path.name} page {page_number}: {process.stderr[-1500:]}")
    png.unlink()


def validate_pdf(path: Path) -> dict[str, Any]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf validation failed for {path.name}: {check.stderr[-2000:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 2:
        raise RuntimeError(f"unexpectedly short archive PDF: {path.name}, pages={pages}")
    render_page(path, 1, "first")
    render_page(path, pages, "last")
    sample = "\n".join((reader.pages[index].extract_text() or "") for index in range(min(pages, 3)))
    normalized = re.sub(r"\s+", "", sample)
    if COMPANY not in normalized or STOCK_CODE not in normalized:
        raise RuntimeError(f"company identity not found in {path.name}")
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "render_verified_first_and_last_page": True,
    }


def write_shortcuts(report: dict[str, Any], metadata: dict[str, Any]) -> list[str]:
    base = f"{report['order']:02d}_{metadata['institution']}_{report['doc_id']}"
    url_file = SOURCE_DIR / f"{base}.url"
    url_file.write_text(f"[InternetShortcut]\nURL={metadata['source_url']}\n", encoding="utf-8")
    webloc = SOURCE_DIR / f"{base}.webloc"
    webloc.write_text(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
        "<plist version=\"1.0\"><dict><key>URL</key><string>"
        + html.escape(metadata["source_url"])
        + "</string></dict></plist>\n",
        encoding="utf-8",
    )
    return [str(url_file.relative_to(ROOT)), str(webloc.relative_to(ROOT))]


def main() -> None:
    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for report in REPORTS:
        metadata = fetch_public_metadata(report)
        destination = REPORT_DIR / report["output_name"]
        build_pdf(report, metadata, destination)
        validation = validate_pdf(destination)
        if validation["sha256"] in seen_hashes:
            raise RuntimeError(f"duplicate PDF detected: {destination.name}")
        seen_hashes.add(validation["sha256"])
        shortcuts = write_shortcuts(report, metadata)
        record = {
            "order": report["order"],
            "document_id": report["doc_id"],
            "institution": metadata["institution"],
            "title": metadata["title"],
            "report_date": metadata["date"],
            "analysts": metadata["analysts"],
            "category": metadata["category"],
            "rating": metadata["rating"],
            "declared_original_pages": metadata["original_pdf_pages_declared"],
            "declared_original_size": metadata["original_pdf_size_declared"],
            "delivery_status": metadata["delivery_status"],
            "source_url": metadata["source_url"],
            "landing_final_url": metadata["landing_final_url"],
            "relative_path": str(destination.relative_to(ROOT)),
            "shortcut_files": shortcuts,
            **validation,
        }
        records.append(record)
        print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

    readme_lines = [
        f"{COMPANY}（{STOCK_CODE}）券商研究资料包",
        "",
        f"核对日期：{CHECK_DATE}",
        "",
        "交付说明：",
        "本包收录3份以百大集团为研究对象的券商报告公开索引存档PDF。",
        "由于公开页面的原始券商PDF下载需要登录或相应访问权限，本包未将索引页面冒充原始报告。",
        "每份PDF均明确标注为“公开索引存档版”，保存可核验元数据、极短公开描述、来源入口及访问状态。",
        "",
        "报告清单：",
    ]
    for record in records:
        readme_lines.extend([
            f"{record['order']}. {record['institution']}《{record['title']}》",
            f"   日期：{record['report_date']}；分析师：{record['analysts'] or '未识别'}；评级：{record['rating'] or '未识别'}",
            f"   原报告公开标注：{record['declared_original_pages'] or '未识别'}页，{record['declared_original_size'] or '大小未识别'}",
            f"   文件：{record['relative_path']}",
            f"   来源：{record['source_url']}",
            "",
        ])
    readme_lines.extend([
        "校验说明：",
        "三份存档PDF已完成qpdf结构检查及首末页渲染检查；ZIP已执行完整性测试。",
        "逐文件SHA-256见SHA256SUMS.txt，结构化元数据见manifest.json和manifest.csv。",
    ])
    (VERIFY_DIR / "README_交付说明.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")
    (VERIFY_DIR / "manifest.json").write_text(
        json.dumps({
            "company": COMPANY,
            "stock_code": STOCK_CODE,
            "checked_as_of": CHECK_DATE,
            "delivery_type": "券商研报公开索引存档版",
            "original_pdf_access": "公开页面需要登录或相应下载权限，未取得原始券商PDF全文",
            "report_count": len(records),
            "reports": records,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    csv_fields = [
        "order", "document_id", "institution", "title", "report_date", "analysts",
        "category", "rating", "declared_original_pages", "declared_original_size",
        "delivery_status", "source_url", "landing_final_url", "relative_path",
        "pages", "bytes", "sha256", "qpdf_return_code", "render_verified_first_and_last_page",
    ]
    with (VERIFY_DIR / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    (VERIFY_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{record['sha256']}  {record['relative_path']}" for record in records) + "\n",
        encoding="utf-8",
    )

    index_html = [
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>百大集团券商报告来源入口</title></head><body>",
        "<h1>百大集团（600865）券商报告来源入口</h1>",
        "<p>以下链接为公开索引页面；原始券商PDF可能要求登录或下载权限。</p><ol>",
    ]
    for record in records:
        index_html.append(
            f"<li><a href='{html.escape(record['source_url'])}' target='_blank'>"
            f"{html.escape(record['institution'])}《{html.escape(record['title'])}》</a></li>"
        )
    index_html.append("</ol></body></html>")
    (SOURCE_DIR / "报告来源入口.html").write_text("\n".join(index_html), encoding="utf-8")

    ZIP_PATH.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(path))
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP integrity failure at {bad}")
    print("FINAL_ZIP", ZIP_PATH, ZIP_PATH.stat().st_size, flush=True)
    print("REPORT_COUNT", len(records), flush=True)


if __name__ == "__main__":
    main()
