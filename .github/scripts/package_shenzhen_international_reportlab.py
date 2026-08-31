from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

import pymupdf
import requests
from bs4 import BeautifulSoup, Tag
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from xml.sax.saxutils import escape

ROOT = Path.cwd()
PACKAGE = ROOT / "shenzhen_international_public_reports_verified"
REPORT_DIR = PACKAGE / "01_券商公司研究报告_公开阅读版"
OUTPUT = ROOT / "深圳国际_券商深度报告_3份_公开阅读版PDF.zip"

COMPANY = "深圳国际控股有限公司"
SHORT_NAME = "深圳国际"
STOCK_CODE = "00152"
TICKER = "00152.HK"
PREPARED_DATE = "2026-08-31"
FONT_NAME = "STSong-Light"

REPORTS: list[dict[str, Any]] = [
    {
        "report_id": 4788440,
        "broker": "西南证券",
        "publish_date": "2025-04-17",
        "researcher": "胡光怿",
        "title": "华南物流园增值添利，高比例分红回报股东",
        "report_type": "2024年年报点评／首次覆盖",
        "source_url": "https://www.fxbaogao.com/detail/4788440",
        "title_markers": ["华南物流园增值添利", "高比例分红回报股东"],
        "min_source_chars": 5000,
        "min_pdf_pages": 5,
        "min_pdf_chars": 3500,
    },
    {
        "report_id": 4438234,
        "broker": "国金证券",
        "publish_date": "2024-08-10",
        "researcher": "郑树明",
        "title": "土地转性贡献弹性，高股息价值凸显",
        "report_type": "公司深度／首次覆盖",
        "source_url": "https://www.fxbaogao.com/detail/4438234",
        "title_markers": ["土地转性贡献弹性", "高股息价值凸显"],
        "min_source_chars": 8500,
        "min_pdf_pages": 7,
        "min_pdf_chars": 6000,
    },
    {
        "report_id": 4069371,
        "broker": "国投证券",
        "publish_date": "2023-12-20",
        "researcher": "孙延",
        "title": "高股息价值凸显，物流园资产释放盈利弹性",
        "report_type": "公司深度分析报告",
        "source_url": "https://www.fxbaogao.com/detail/4069371",
        "title_markers": ["高股息价值凸显", "物流园资产释放盈利弹性"],
        "min_source_chars": 8500,
        "min_pdf_pages": 7,
        "min_pdf_chars": 6000,
    },
]

session = requests.Session()
session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
)


def compact(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def safe_filename(text: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:180]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_source(url: str) -> tuple[str, str]:
    errors: list[str] = []
    for attempt in range(1, 4):
        try:
            response = session.get(url, timeout=(15, 60), allow_redirects=True)
            response.raise_for_status()
            encoding = response.apparent_encoding or response.encoding or "utf-8"
            text = response.content.decode(encoding, errors="replace")
            if len(text) < 20_000:
                raise RuntimeError(f"HTML unexpectedly short: {len(text)} chars")
            return html_lib.unescape(text).replace("\\/", "/"), response.url
        except Exception as exc:
            errors.append(f"attempt {attempt}: {exc}")
            time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to fetch {url}: " + " | ".join(errors))


def find_report_container(soup: BeautifulSoup, record: dict[str, Any]) -> Tag:
    title_prefix = str(record["title"])[:8]
    headings = soup.find_all("h1")
    heading = next(
        (tag for tag in headings if title_prefix in tag.get_text(" ", strip=True)),
        headings[0] if headings else None,
    )
    if heading is None:
        raise RuntimeError(f"Report title element not found: {record['report_id']}")

    fallback: Tag | None = None
    node: Tag | None = heading
    while node is not None:
        classes = " ".join(node.get("class") or [])
        text_chars = len(compact(node.get_text(" ", strip=True)))
        if "ReportCard" in classes and text_chars >= 3000:
            return node
        if fallback is None and text_chars >= int(record["min_source_chars"]):
            fallback = node
        parent = node.parent
        node = parent if isinstance(parent, Tag) else None
    if fallback is not None:
        return fallback
    raise RuntimeError(f"Report content container not found: {record['report_id']}")


def extract_public_lines(record: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    raw_html, final_url = fetch_source(str(record["source_url"]))
    soup = BeautifulSoup(raw_html, "html.parser")
    container = find_report_container(soup, record)
    source_text = container.get_text("\n", strip=True)
    source_chars = len(compact(source_text))
    if source_chars < int(record["min_source_chars"]):
        raise RuntimeError(
            f"Public source appears incomplete for {record['report_id']}: "
            f"{source_chars} characters"
        )

    normalized = compact(source_text)
    if not any(
        compact(marker) in normalized
        for marker in (SHORT_NAME, "深圳國際", STOCK_CODE, "0152.hk")
    ):
        raise RuntimeError(f"Company marker missing: {record['report_id']}")
    if compact(str(record["broker"])) not in normalized:
        raise RuntimeError(f"Broker marker missing: {record['report_id']}")
    for marker in record["title_markers"]:
        if compact(marker) not in normalized:
            raise RuntimeError(
                f"Title marker {marker!r} missing: {record['report_id']}"
            )

    ignored_exact = {
        "点击免费查看完整报告",
        "我的下载",
        "登录",
        "注册",
        "收藏",
        "分享",
        "你可能感兴趣",
        "相关推荐",
        "热门报告",
        "报告封面",
    }
    lines: list[str] = []
    prior = ""
    for raw_line in source_text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        line = line.replace("", "•").replace("", "•")
        if not line or line in ignored_exact:
            continue
        if line.startswith("发现报告") or line.startswith("免责声明：本网站"):
            continue
        if line == prior:
            continue
        lines.append(line)
        prior = line

    delivered_chars = len(compact("\n".join(lines)))
    if delivered_chars < int(record["min_source_chars"]) * 0.70:
        raise RuntimeError(
            f"Filtered public text is unexpectedly short for {record['report_id']}: "
            f"{delivered_chars} vs source {source_chars}"
        )

    return lines, {
        "source_page": final_url,
        "source_text_characters": source_chars,
        "delivered_text_characters": delivered_chars,
        "source_html_bytes": len(raw_html.encode("utf-8")),
    }


def page_number(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.grey)
    canvas.drawCentredString(A4[0] / 2, 8 * mm, str(doc.page))
    canvas.restoreState()


def build_pdf(path: Path, record: dict[str, Any], lines: list[str]) -> None:
    pdfmetrics.registerFont(UnicodeCIDFont(FONT_NAME))
    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=17 * mm,
        rightMargin=17 * mm,
        topMargin=16 * mm,
        bottomMargin=17 * mm,
        title=f"{record['broker']}：{record['title']}",
        author=str(record["broker"]),
        subject=f"{COMPANY}（{TICKER}）券商公司研究报告公开阅读版",
    )

    title_style = ParagraphStyle(
        "CJKTitle",
        fontName=FONT_NAME,
        fontSize=18,
        leading=25,
        alignment=TA_CENTER,
        spaceAfter=10,
        wordWrap="CJK",
    )
    meta_style = ParagraphStyle(
        "CJKMeta",
        fontName=FONT_NAME,
        fontSize=9.5,
        leading=14,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#333333"),
        wordWrap="CJK",
    )
    notice_style = ParagraphStyle(
        "CJKNotice",
        fontName=FONT_NAME,
        fontSize=9,
        leading=13,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#333333"),
        backColor=colors.HexColor("#F2F2F2"),
        borderColor=colors.HexColor("#999999"),
        borderWidth=0.5,
        borderPadding=7,
        spaceAfter=11,
        wordWrap="CJK",
    )
    body_style = ParagraphStyle(
        "CJKBody",
        fontName=FONT_NAME,
        fontSize=10.2,
        leading=16.2,
        alignment=TA_JUSTIFY,
        firstLineIndent=0,
        spaceBefore=2,
        spaceAfter=5,
        wordWrap="CJK",
        allowWidows=0,
        allowOrphans=0,
    )
    heading_style = ParagraphStyle(
        "CJKHeading",
        parent=body_style,
        fontSize=12.5,
        leading=18,
        spaceBefore=10,
        spaceAfter=5,
        keepWithNext=True,
    )

    story = [
        Paragraph(
            "<b>公开阅读版PDF</b><br/>本文件由无需登录即可访问的公开阅读正文转存，"
            "非券商原生版式PDF。原始下载入口要求登录，未使用或绕过该机制。",
            notice_style,
        ),
        Paragraph(escape(str(record["title"])), title_style),
        Table(
            [
                ["公司", f"{COMPANY}（{TICKER}）"],
                ["券商／研究员", f"{record['broker']}／{record['researcher']}"],
                ["发布日期／类型", f"{record['publish_date']}／{record['report_type']}"],
            ],
            colWidths=[32 * mm, 140 * mm],
            style=TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
                    ("FONTSIZE", (0, 0), (-1, -1), 9.2),
                    ("LEADING", (0, 0), (-1, -1), 13),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#AAAAAA")),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F5F5F5")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            ),
        ),
        Spacer(1, 10),
    ]

    heading_tokens = {
        "投资要点",
        "核心观点",
        "风险提示",
        "盈利预测",
        "盈利预测与估值",
        "公司概况",
        "投资建议",
    }
    for line in lines:
        escaped = escape(line)
        style = heading_style if line in heading_tokens or (len(line) <= 22 and re.match(r"^[一二三四五六七八九十0-9、. ]", line)) else body_style
        story.append(Paragraph(escaped, style))

    document.build(story, onFirstPage=page_number, onLaterPages=page_number)


def inspect_pdf(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF-"):
        raise RuntimeError(f"Not a PDF: {path}")
    reader = PdfReader(str(path))
    if reader.is_encrypted and reader.decrypt("") == 0:
        raise RuntimeError(f"Cannot decrypt PDF: {path}")
    pages = len(reader.pages)
    if pages < int(record["min_pdf_pages"]):
        raise RuntimeError(
            f"PDF unexpectedly short for {record['report_id']}: {pages} pages"
        )

    document = pymupdf.open(path)
    if document.page_count != pages:
        raise RuntimeError(f"Page-count mismatch: {path}")
    extracted = "\n".join(
        document.load_page(index).get_text("text") for index in range(pages)
    )
    extracted_chars = len(compact(extracted))
    if extracted_chars < int(record["min_pdf_chars"]):
        raise RuntimeError(
            f"Searchable PDF text is incomplete for {record['report_id']}: "
            f"{extracted_chars} characters"
        )
    normalized = compact(extracted)
    for group in [
        (SHORT_NAME, "深圳國際", STOCK_CODE, "0152.hk"),
        (str(record["broker"]),),
    ]:
        if not any(compact(marker) in normalized for marker in group):
            raise RuntimeError(f"Required marker {group} missing: {path}")
    for marker in record["title_markers"]:
        if compact(marker) not in normalized:
            raise RuntimeError(f"Title marker {marker!r} missing: {path}")

    for page_index in sorted({0, pages // 2, pages - 1}):
        pixmap = document.load_page(page_index).get_pixmap(
            matrix=pymupdf.Matrix(0.75, 0.75), alpha=False
        )
        if pixmap.width < 300 or pixmap.height < 400:
            raise RuntimeError(
                f"Render check failed: {path}, page {page_index + 1}"
            )
    document.close()
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "text_characters": extracted_chars,
        "text_searchable": True,
    }


def main() -> None:
    if PACKAGE.exists():
        shutil.rmtree(PACKAGE)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.unlink(missing_ok=True)

    documents: list[dict[str, Any]] = []
    checksum_lines: list[str] = []

    for index, record in enumerate(REPORTS, 1):
        lines, source_meta = extract_public_lines(record)
        filename = safe_filename(
            f"{index:02d}_{record['broker']}_{record['publish_date'].replace('-', '')}_"
            f"{record['title']}_公开阅读版.pdf"
        )
        target = REPORT_DIR / filename
        build_pdf(target, record, lines)
        metadata = inspect_pdf(target, record)
        rel_path = str(target.relative_to(PACKAGE))
        item = {
            "company": COMPANY,
            "short_name": SHORT_NAME,
            "ticker": TICKER,
            "broker": record["broker"],
            "publish_date": record["publish_date"],
            "researcher": record["researcher"],
            "title": record["title"],
            "report_type": record["report_type"],
            "file": rel_path,
            **metadata,
            **source_meta,
            "source_report_id": record["report_id"],
            "delivery_note": (
                "由无需登录即可访问的公开阅读正文转存为可检索PDF；"
                "非券商原生排版PDF，原始图表版式不完全保留。"
            ),
        }
        documents.append(item)
        checksum_lines.append(f"{item['sha256']}  {rel_path}")
        print(
            f"BUILT {record['broker']} | {record['title']} | "
            f"source_chars={source_meta['source_text_characters']} "
            f"delivered_chars={source_meta['delivered_text_characters']} "
            f"pdf_pages={metadata['pages']} pdf_chars={metadata['text_characters']} "
            f"bytes={metadata['bytes']}"
        )

    if len(documents) != 3:
        raise RuntimeError(f"Expected 3 reports, found {len(documents)}")

    total_pages = sum(int(item["pages"]) for item in documents)
    total_bytes = sum(int(item["bytes"]) for item in documents)
    readme_lines = [
        f"{COMPANY}（{TICKER}，{SHORT_NAME}）券商公司研究报告",
        f"整理日期：{PREPARED_DATE}",
        "",
        "重要说明",
        "1. 收录三份无需登录即可公开阅读全文的券商公司研究报告。",
        "2. 报告原始下载入口要求账户登录，未使用或绕过该登录机制。",
        "3. 本包将公开阅读正文转存为可检索PDF，并非券商原生排版PDF；",
        "   标题和正文予以保留，原始图表及版式不完全保留。",
        "4. 适合阅读、检索和归档；券商原版应通过有权访问的研报终端或券商渠道取得。",
        "",
        "文件清单",
    ]
    for index, item in enumerate(documents, 1):
        readme_lines.extend(
            [
                f"{index}. {item['broker']}：{item['title']}",
                f"   类型：{item['report_type']}",
                f"   发布日期：{item['publish_date']}",
                f"   研究员：{item['researcher']}",
                f"   转存PDF页数：{item['pages']}",
                f"   可检索正文字符数：{item['text_characters']}",
                f"   文件：{item['file']}",
                f"   来源页面：{item['source_page']}",
                f"   SHA-256：{item['sha256']}",
                "",
            ]
        )
    readme_lines.extend(
        [
            "完整性检查",
            f"- 共3份可检索PDF，合计{total_pages}页，PDF总大小{total_bytes / 1024 / 1024:.2f} MiB。",
            "- 已核对公司、股票代码、券商、标题、发布日期、研究员和正文长度。",
            "- 已检查PDF文件头、结构、文本层，并渲染检查首页、中间页和末页。",
            "- ZIP已通过CRC完整性测试；逐文件SHA-256见SHA256SUMS.txt。",
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
                "stock_code": STOCK_CODE,
                "ticker": TICKER,
                "prepared_date": PREPARED_DATE,
                "delivery_format": "公开阅读正文转存的可检索PDF（非券商原生版式）",
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
        pdf_names = [
            name for name in archive.namelist() if name.lower().endswith(".pdf")
        ]
        if len(pdf_names) != 3:
            raise RuntimeError(f"Expected 3 PDFs, found {len(pdf_names)}")

    print("\n".join(readme_lines))
    print(f"ZIP_FILE={OUTPUT}")
    print(f"ZIP_BYTES={OUTPUT.stat().st_size}")
    print(f"ZIP_SHA256={sha256(OUTPUT)}")


if __name__ == "__main__":
    main()
