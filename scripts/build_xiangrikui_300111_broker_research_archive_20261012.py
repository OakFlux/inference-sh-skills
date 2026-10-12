from __future__ import annotations

import csv
import hashlib
import html as html_lib
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
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)

CHECKED_AS_OF = "2026-10-12"
COMPANY = "向日葵"
FULL_COMPANY = "浙江向日葵大健康科技股份有限公司"
HISTORICAL_COMPANY = "浙江向日葵光能科技股份有限公司"
STOCK_CODE = "300111"
PACKAGE = "向日葵_300111_券商深度研究资料_3份"
ROOT = Path(PACKAGE)
REPORT_DIR = ROOT / "01_券商研究报告"
VERIFY_DIR = ROOT / "02_说明与校验"
WORK_DIR = Path("_xiangrikui_300111_broker_archive_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (REPORT_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# These three items are the most systematic company-level research entries that remain
# publicly accessible in Sina Finance's historical report archive. The original broker-
# formatted PDF attachments are no longer exposed by the archive; therefore this script
# creates clearly labelled archival PDFs from the public full-text pages.
REPORTS: list[dict[str, Any]] = [
    {
        "rid": "514455565748",
        "expected_title_keywords": ["深度研究", "分布式光伏电站", "完善产业布局"],
        "classification": "明确标注深度研究",
        "filename_date": "20160420",
        "filename_stub": "华泰证券_重点分布式光伏电站运营_完善产业布局_公开全文存档版.pdf",
    },
    {
        "rid": "365112661987",
        "expected_title_keywords": ["调研简报", "行业东风", "垂直布局"],
        "classification": "系统性公司调研简报",
        "filename_date": "20110727",
        "filename_stub": "民生证券_行业东风助量利齐增_垂直布局_公开全文存档版.pdf",
    },
    {
        "rid": "334830239109",
        "expected_title_keywords": ["新股研究", "晶硅电池片", "光伏厂商"],
        "classification": "上市初期系统性新股研究",
        "filename_date": "201008",
        "filename_stub": "新股研究_专注晶硅电池片及组件的光伏厂商_公开全文存档版.pdf",
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def safe_filename(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", "", value).strip("._")
    return value[:180] or "report"


def get_page(url: str) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 7):
        try:
            response = SESSION.get(url, headers=HEADERS, timeout=(20, 120), allow_redirects=True)
            print(
                "HTTP", attempt, response.status_code,
                response.headers.get("content-type"), len(response.content), response.url,
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            time.sleep(min(attempt * 2, 10))
    raise RuntimeError(f"request failed for {url}: {errors[-3:]}")


def split_body_into_paragraphs(container: Any) -> list[str]:
    # Preserve paragraph and line-break structure without retaining scripts or navigation.
    for tag in container.find_all(["script", "style", "iframe", "noscript"]):
        tag.decompose()
    for br in container.find_all("br"):
        br.replace_with("\n")
    text = html_lib.unescape(container.get_text("\n"))
    chunks: list[str] = []
    for raw in re.split(r"\n+", text):
        item = re.sub(r"[\u00a0\t\r ]+", " ", raw).strip()
        if item:
            chunks.append(item)
    return chunks


def parse_report(report: dict[str, Any]) -> dict[str, Any]:
    rid = report["rid"]
    url = f"https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/{rid}/index.phtml"
    response = get_page(url)
    response.encoding = response.apparent_encoding or "gb18030"
    soup = BeautifulSoup(response.text, "html.parser")

    content = soup.select_one("div.blk_02 div.content") or soup.select_one("div.content")
    if content is None:
        raise RuntimeError(f"content block missing for report {rid}")
    title_node = content.find("h1")
    if title_node is None:
        raise RuntimeError(f"title missing for report {rid}")
    title = re.sub(r"\s+", " ", title_node.get_text(" ", strip=True))

    meta_text = " | ".join(
        re.sub(r"\s+", " ", span.get_text(" ", strip=True))
        for span in content.select("div.creab span")
    )
    broker_match = re.search(r"机构[:：]\s*([^|]+)", meta_text)
    analysts_match = re.search(r"研究员[:：]\s*([^|]+)", meta_text)
    date_match = re.search(r"日期[:：]\s*(\d{4}-\d{2}-\d{2})", meta_text)
    category_match = re.search(r"类别[:：]\s*([^|]+)", meta_text)
    broker = broker_match.group(1).strip() if broker_match else "未识别"
    analysts = analysts_match.group(1).strip() if analysts_match else "未识别"
    publish_date = date_match.group(1) if date_match else "未识别"
    source_category = category_match.group(1).strip() if category_match else "未识别"

    body = content.select_one("div.blk_container")
    if body is None:
        raise RuntimeError(f"body missing for report {rid}")
    paragraphs = split_body_into_paragraphs(body)
    body_text = "\n".join(paragraphs)

    title_normalized = normalize(title)
    missing_keywords = [k for k in report["expected_title_keywords"] if normalize(k) not in title_normalized]
    if missing_keywords:
        raise RuntimeError(f"title keyword mismatch for {rid}: {missing_keywords}; title={title}")
    if len(body_text) < 500:
        raise RuntimeError(f"public report text is unexpectedly short for {rid}: {len(body_text)} chars")
    if COMPANY not in title and STOCK_CODE not in title:
        raise RuntimeError(f"company identity missing from title for {rid}")

    return {
        **report,
        "source_url": str(response.url),
        "title": title,
        "broker": broker,
        "analysts": analysts,
        "publish_date": publish_date,
        "source_category": source_category,
        "paragraphs": paragraphs,
        "body_characters": len(body_text),
    }


pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
FONT = "STSong-Light"
PAGE_W, PAGE_H = A4

styles = getSampleStyleSheet()
TITLE_STYLE = ParagraphStyle(
    "ChineseTitle",
    parent=styles["Title"],
    fontName=FONT,
    fontSize=18,
    leading=27,
    alignment=TA_CENTER,
    textColor=colors.HexColor("#1f2937"),
    spaceAfter=10 * mm,
)
SUBTITLE_STYLE = ParagraphStyle(
    "ChineseSubtitle",
    parent=styles["Normal"],
    fontName=FONT,
    fontSize=10.5,
    leading=16,
    alignment=TA_LEFT,
    textColor=colors.HexColor("#374151"),
)
NOTE_STYLE = ParagraphStyle(
    "ArchiveNote",
    parent=styles["Normal"],
    fontName=FONT,
    fontSize=10,
    leading=16,
    textColor=colors.HexColor("#7c2d12"),
)
BODY_STYLE = ParagraphStyle(
    "ChineseBody",
    parent=styles["BodyText"],
    fontName=FONT,
    fontSize=10.5,
    leading=18,
    firstLineIndent=21,
    alignment=TA_LEFT,
    textColor=colors.HexColor("#111827"),
    spaceAfter=3.2 * mm,
    wordWrap="CJK",
)
HEADING_STYLE = ParagraphStyle(
    "ChineseHeading",
    parent=styles["Heading2"],
    fontName=FONT,
    fontSize=13,
    leading=20,
    textColor=colors.HexColor("#1f2937"),
    spaceBefore=3 * mm,
    spaceAfter=3 * mm,
)
FOOTER_STYLE = ParagraphStyle(
    "Footer",
    parent=styles["Normal"],
    fontName=FONT,
    fontSize=8,
    leading=10,
    alignment=TA_CENTER,
    textColor=colors.HexColor("#6b7280"),
)


def escape_para(text: str) -> str:
    return html_lib.escape(text).replace("\n", "<br/>")


def page_decorator(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#d1d5db"))
    canvas.setLineWidth(0.4)
    canvas.line(18 * mm, 16 * mm, PAGE_W - 18 * mm, 16 * mm)
    footer = Paragraph(
        f"{COMPANY}（{STOCK_CODE}）券商公开全文存档版 | 第 {doc.page} 页",
        FOOTER_STYLE,
    )
    w, h = footer.wrap(PAGE_W - 36 * mm, 10 * mm)
    footer.drawOn(canvas, 18 * mm, 6 * mm)
    canvas.restoreState()


def make_pdf(record: dict[str, Any], destination: Path) -> None:
    frame = Frame(
        18 * mm,
        20 * mm,
        PAGE_W - 36 * mm,
        PAGE_H - 38 * mm,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    template = PageTemplate(id="main", frames=[frame], onPage=page_decorator)
    doc = BaseDocTemplate(
        str(destination),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        title=record["title"],
        author=record["broker"],
        subject=f"{COMPANY}（{STOCK_CODE}）券商研究公开全文存档版",
        creator="Public source archival packaging",
    )
    doc.addPageTemplates([template])

    story: list[Any] = []
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(escape_para(record["title"]), TITLE_STYLE))

    meta_data = [
        ["券商机构", record["broker"]],
        ["研究员", record["analysts"]],
        ["发布日期", record["publish_date"]],
        ["新浪分类", record["source_category"]],
        ["资料属性", record["classification"]],
        ["来源页面", record["source_url"]],
    ]
    table = Table(meta_data, colWidths=[28 * mm, PAGE_W - 36 * mm - 28 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("LEADING", (0, 0), (-1, -1), 14),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#374151")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    story.append(Spacer(1, 6 * mm))

    note = (
        "重要说明：本文件由新浪财经历史研报公开全文页面归档生成。"
        "本次检索未取得仍可直接下载的券商原始排版PDF，因此本文件不是券商原始版式；"
        "标题、券商、研究员、日期及正文均取自所列公开来源页面。"
    )
    note_table = Table([[Paragraph(escape_para(note), NOTE_STYLE)]], colWidths=[PAGE_W - 36 * mm])
    note_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff7ed")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#fb923c")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(note_table)
    story.append(PageBreak())
    story.append(Paragraph("公开正文", HEADING_STYLE))

    for item in record["paragraphs"]:
        # Short lines ending with a Chinese colon or lacking sentence punctuation are
        # presented as section headings; all other material is body text.
        stripped = item.strip()
        is_heading = (
            len(stripped) <= 32
            and (
                stripped.endswith(("：", ":"))
                or not re.search(r"[。！？；]$", stripped)
            )
        )
        style = HEADING_STYLE if is_heading else BODY_STYLE
        story.append(Paragraph(escape_para(stripped), style))

    doc.build(story)


def render_page(path: Path, page_number: int, suffix: str) -> str:
    prefix = RENDER_DIR / f"{path.stem}_{suffix}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
            "-r", "130", "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    png = Path(str(prefix) + ".png")
    valid = (
        process.returncode == 0 and png.exists() and png.stat().st_size > 5000
        and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    )
    if not valid:
        raise RuntimeError(
            f"render failed for {path.name} page {page_number}: "
            f"return={process.returncode}, stderr={process.stderr[-1500:]}"
        )
    return str(png.relative_to(WORK_DIR))


def validate_pdf(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {check.stderr[-2000:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 2:
        raise RuntimeError(f"archive PDF unexpectedly short: {path.name}, pages={pages}")
    text_parts: list[str] = []
    for index in sorted({0, min(1, pages - 1), pages // 2, pages - 1}):
        text_parts.append(reader.pages[index].extract_text() or "")
    text = normalize("\n".join(text_parts))
    company_ok = COMPANY in text or STOCK_CODE in text
    broker_ok = normalize(record["broker"]) in text
    if not company_ok:
        raise RuntimeError(f"company identity missing from generated PDF: {path.name}")
    if not broker_ok:
        raise RuntimeError(f"broker identity missing from generated PDF: {path.name}")
    render_pages = sorted({1, max(1, (pages + 1) // 2), pages})
    renders = [render_page(path, page, f"p{page}") for page in render_pages]
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "rendered_pages": render_pages,
        "render_files": renders,
        "company_identity_verified": company_ok,
        "broker_identity_verified": broker_ok,
    }


records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()
for report in REPORTS:
    parsed = parse_report(report)
    filename = f"{parsed['filename_date']}_{parsed['filename_stub']}"
    # If the source metadata identifies a broker different from the expected filename
    # stub, keep the parsed broker in the manifest and the filename remains descriptive.
    destination = REPORT_DIR / safe_filename(filename)
    if destination.suffix.lower() != ".pdf":
        destination = destination.with_suffix(".pdf")
    make_pdf(parsed, destination)
    validation = validate_pdf(destination, parsed)
    if validation["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate archive PDF: {destination.name}")
    seen_hashes.add(validation["sha256"])
    record = {
        "date": parsed["publish_date"],
        "broker": parsed["broker"],
        "analysts": parsed["analysts"],
        "title": parsed["title"],
        "classification": parsed["classification"],
        "format": "新浪财经公开全文页面存档版PDF（非券商原始排版PDF）",
        "source_url": parsed["source_url"],
        "source_rptid": parsed["rid"],
        "source_body_characters": parsed["body_characters"],
        "relative_path": str(destination.relative_to(ROOT)),
        **validation,
    }
    records.append(record)
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

manifest = {
    "package_name": PACKAGE,
    "company": FULL_COMPANY,
    "historical_company_name": HISTORICAL_COMPANY,
    "short_name": COMPANY,
    "stock_code": STOCK_CODE,
    "checked_as_of": CHECKED_AS_OF,
    "document_count": len(records),
    "important_limitation": (
        "公开检索未取得这三份历史研报仍可直接下载的券商原始排版PDF。"
        "包内文件由新浪财经历史研报公开全文页面归档生成，均在文件名及首页明确标注，"
        "没有冒充券商原始版式。"
    ),
    "selection_note": (
        "收录一份明确标注深度研究的报告、一份系统性公司调研简报和一份上市初期新股研究；"
        "排除季度、年度业绩点评和普通新闻。"
    ),
    "records": records,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as handle:
    writer = csv.writer(handle)
    writer.writerow([
        "文件", "发布日期", "券商", "研究员", "标题", "资料属性", "文件格式说明",
        "页数", "字节数", "SHA-256", "来源页面",
    ])
    for record in records:
        writer.writerow([
            record["relative_path"], record["date"], record["broker"], record["analysts"],
            record["title"], record["classification"], record["format"], record["pages"],
            record["bytes"], record["sha256"], record["source_url"],
        ])

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as handle:
    for record in records:
        handle.write(f"{record['sha256']}  {record['relative_path']}\n")

readme = [
    f"{COMPANY}（{STOCK_CODE}）券商深度研究资料包",
    "",
    f"核对日期：{CHECKED_AS_OF}",
    "收录数量：3份券商公司研究公开全文存档版PDF",
    "",
    "重要说明：",
    "公开检索未取得这些历史报告仍可直接下载的券商原始排版PDF。",
    "包内PDF由新浪财经历史研报公开全文页面归档生成，文件名和首页均已明确标注“公开全文存档版”。",
    "其中仅华泰证券报告的原标题明确标注“深度研究”；另外两份分别为系统性公司调研简报和上市初期新股研究。",
    "没有使用自媒体文章、AI研报、新闻稿或普通财报点评凑数。",
    "",
    "收录报告：",
]
for index, record in enumerate(records, 1):
    readme.append(
        f"{index}. {record['date']} | {record['broker']} | {record['title']} | {record['pages']}页 | {record['format']}"
    )
readme.extend([
    "",
    "校验项目：",
    "- 来源页面标题、券商、研究员和发布日期解析；",
    "- 正文长度及公司名称/股票代码核验；",
    "- 生成PDF的qpdf结构检查、文本抽取检查和SHA-256去重；",
    "- 每份PDF首页、中间页和末页实际渲染；",
    "- ZIP压缩包完整性测试。",
    "",
    "详细来源、页数和哈希值见文件清单.csv、SHA256SUMS.txt及manifest.json。",
])
(VERIFY_DIR / "README.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")

zip_path = Path(PACKAGE + ".zip")
zip_path.unlink(missing_ok=True)
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, path.as_posix())

with zipfile.ZipFile(zip_path, "r") as archive:
    bad_member = archive.testzip()
    if bad_member:
        raise RuntimeError(f"ZIP integrity failure at {bad_member}")
    pdf_count = sum(1 for name in archive.namelist() if name.lower().endswith(".pdf"))
    if pdf_count != 3:
        raise RuntimeError(f"ZIP PDF count mismatch: expected 3, got {pdf_count}")

print(
    "FINAL_ZIP", zip_path,
    "bytes", zip_path.stat().st_size,
    "sha256", sha256(zip_path),
    flush=True,
)
print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
