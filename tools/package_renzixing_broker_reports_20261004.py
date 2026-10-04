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
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import requests
from bs4 import BeautifulSoup
from PIL import Image
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

COMPANY = "任子行"
CODE = "300311"
ROOT = Path("任子行_300311_券商深度报告_3份")
REPORT_DIR = ROOT / "01_券商报告"
NOTES_DIR = ROOT / "02_资料说明"
TMP_DIR = Path("_tmp_renzixing_broker_reports")
PREVIEW_DIR = Path("_previews_renzixing_broker_reports")
ZIP_PATH = Path("任子行_300311_券商深度报告_3份.zip")
RESULT_JSON = Path("renzixing_broker_reports_result.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}

REPORTS = [
    {
        "order": 1,
        "kind": "sina_text_archive",
        "rptid": "617160447124",
        "date": "2016-08-17",
        "institution": "华金证券",
        "authors": "谭志勇",
        "rating": "买入-A",
        "title": "快速成长的网络审计专家：2016年H1归母净利润增长超200%",
        "filename": "01_华金证券_2016-08-17_快速成长的网络审计专家_公开网页全文存档版.pdf",
        "source_url": "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/617160447124/index.phtml",
    },
    {
        "order": 2,
        "kind": "fxbaogao_page_images",
        "doc_id": 71024,
        "date": "2016-04-21",
        "date_path": "2016/04/21",
        "institution": "太平洋证券",
        "authors": "张学、徐中华",
        "rating": "买入（首次）",
        "title": "行业景气外延助力，持续高成长可期",
        "filename": "02_太平洋证券_2016-04-21_行业景气外延助力_持续高成长可期_公开逐页图像重建版.pdf",
        "source_url": "https://www.fxbaogao.com/detail/71024",
    },
    {
        "order": 3,
        "kind": "sina_text_archive",
        "rptid": "507309959252",
        "date": "2016-01-28",
        "institution": "平安证券",
        "authors": "张冰",
        "rating": "推荐（首次覆盖）",
        "title": "互联网内容和行为审计迎来新增市场空间",
        "filename": "03_平安证券_2016-01-28_互联网内容和行为审计迎来新增市场空间_公开网页全文存档版.pdf",
        "source_url": "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/507309959252/index.phtml",
    },
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def reset() -> None:
    for path in (ROOT, TMP_DIR, PREVIEW_DIR):
        if path.exists():
            shutil.rmtree(path)
    for path in (ZIP_PATH, RESULT_JSON):
        if path.exists():
            path.unlink()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)


def decode_sina(content: bytes, expected: str) -> str:
    candidates = []
    for enc in ("gb18030", "gbk", "utf-8"):
        try:
            text = content.decode(enc, errors="replace")
        except Exception:
            continue
        score = text.count("�") * 100 + text.count("?")
        if expected in text:
            score -= 1000
        if "任子行" in text:
            score -= 500
        candidates.append((score, enc, text))
    if not candidates:
        raise RuntimeError("无法解码新浪研报页面")
    candidates.sort(key=lambda x: x[0])
    score, enc, text = candidates[0]
    print("SINA_ENCODING", expected, enc, score, flush=True)
    return text


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = value.replace("\u3000", " ").replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def fetch_sina_visible_text(session: requests.Session, report: dict[str, Any]) -> str:
    response = session.get(report["source_url"], headers=HEADERS, timeout=120, allow_redirects=True)
    print("SINA_RESPONSE", report["rptid"], response.status_code, len(response.content), response.url, flush=True)
    response.raise_for_status()
    decoded = decode_sina(response.content, report["title"].split("：", 1)[0])
    soup = BeautifulSoup(decoded, "html.parser")
    node = soup.select_one(".content")
    if node is None:
        raise RuntimeError(f"新浪页面未找到正文：{report['rptid']}")
    visible = clean_text(node.get_text(" ", strip=True))
    if COMPANY not in visible or len(visible) < 700:
        raise RuntimeError(f"新浪正文异常：{report['rptid']} chars={len(visible)}")
    # Remove page title and metadata prefix, retaining the public research text.
    date_marker = f"日期：{report['date']}"
    if date_marker in visible:
        visible = visible.split(date_marker, 1)[1].strip()
    return visible


def split_research_text(text: str) -> list[str]:
    markers = [
        "【事件】", "事件：", "事项:", "事项：", "平安观点:", "平安观点：",
        "多方因素驱动", "紧抓发展机遇", "未来公司", "投资建议：", "风险提示：",
        "网络内容与行为", "坚持创新", "外延助力", "“网络应用审计专家”", "\"网络应用审计专家\"",
        "中国网络内容", "未来网络行为", "移动互联网", "移动云联网", "首次覆盖",
    ]
    for marker in markers:
        text = text.replace(marker, "\n" + marker)
    text = re.sub(r"\s*\n\s*", "\n", text)
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    # Split overly long blocks at sentence boundaries while keeping coherent paragraphs.
    output: list[str] = []
    for part in parts:
        if len(part) <= 650:
            output.append(part)
            continue
        sentences = re.split(r"(?<=[。；！？])", part)
        buf = ""
        for sentence in sentences:
            if len(buf) + len(sentence) > 550 and buf:
                output.append(buf.strip())
                buf = sentence
            else:
                buf += sentence
        if buf.strip():
            output.append(buf.strip())
    return output


def pdf_footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("STSong-Light", 8)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawString(18 * mm, 11 * mm, "任子行券商研究资料 - 公开网页存档")
    canvas.drawRightString(192 * mm, 11 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def build_text_archive_pdf(report: dict[str, Any], visible_text: str, output: Path) -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleCN", parent=styles["Title"], fontName="STSong-Light", fontSize=17,
        leading=25, alignment=TA_CENTER, spaceAfter=10,
    )
    subtitle_style = ParagraphStyle(
        "SubCN", parent=styles["Normal"], fontName="STSong-Light", fontSize=10,
        leading=16, alignment=TA_CENTER, textColor=colors.HexColor("#555555"), spaceAfter=14,
    )
    body_style = ParagraphStyle(
        "BodyCN", parent=styles["BodyText"], fontName="STSong-Light", fontSize=10.5,
        leading=18, alignment=TA_JUSTIFY, firstLineIndent=21, spaceAfter=7,
    )
    heading_style = ParagraphStyle(
        "HeadingCN", parent=body_style, fontSize=11.5, leading=19, firstLineIndent=0,
        textColor=colors.HexColor("#1F3A5F"), spaceBefore=7, spaceAfter=5,
    )
    note_style = ParagraphStyle(
        "NoteCN", parent=body_style, fontSize=9.2, leading=15, firstLineIndent=0,
        textColor=colors.HexColor("#555555"), backColor=colors.HexColor("#F2F4F7"),
        borderPadding=8, spaceAfter=12,
    )
    doc = SimpleDocTemplate(
        str(output), pagesize=A4, leftMargin=21 * mm, rightMargin=21 * mm,
        topMargin=19 * mm, bottomMargin=19 * mm,
        title=report["title"], author=report["institution"],
    )
    story: list[Any] = []
    story.append(Paragraph(escape(report["title"]), title_style))
    story.append(Paragraph(f"{report['institution']} | {report['date']} | 分析师：{report['authors']} | 评级：{report['rating']}", subtitle_style))
    story.append(Paragraph(
        "存档说明：本文件依据新浪财经公开展示的券商研报正文制作，用于离线阅读和资料归档。它保留公开页面可见文字，但不是券商原始排版PDF，不包含原报告中未在网页展示的图表或附录。",
        note_style,
    ))
    for para in split_research_text(visible_text):
        escaped = escape(para)
        is_heading = any(para.startswith(prefix) for prefix in (
            "【事件】", "事件：", "事项", "平安观点", "多方因素", "紧抓发展机遇", "未来公司",
            "投资建议", "风险提示", "网络内容与行为", "坚持创新", "外延助力", "“网络应用",
            "中国网络内容", "未来网络行为", "移动互联网", "移动云联网", "首次覆盖",
        ))
        story.append(Paragraph(escaped, heading_style if is_heading and len(para) < 100 else body_style))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"公开来源：{escape(report['source_url'])}", note_style))
    doc.build(story, onFirstPage=pdf_footer, onLaterPages=pdf_footer)


def download_fxbaogao_pages(session: requests.Session, report: dict[str, Any], output: Path) -> tuple[list[dict[str, Any]], int]:
    images: list[Image.Image] = []
    page_records: list[dict[str, Any]] = []
    misses = 0
    try:
        for page in range(1, 31):
            url = f"https://public.fxbaogao.com/report-image/{report['date_path']}/{report['doc_id']}-{page}.png"
            response = session.get(
                url,
                headers={**HEADERS, "Referer": f"https://www.fxbaogao.com/view?id={report['doc_id']}"},
                timeout=90,
            )
            rec: dict[str, Any] = {
                "page": page, "url": url, "status": response.status_code,
                "bytes": len(response.content), "content_type": response.headers.get("content-type"),
            }
            if response.status_code == 200 and len(response.content) > 10000:
                image = Image.open(BytesIO(response.content))
                image.load()
                if image.width < 600 or image.height < 800:
                    raise RuntimeError(f"报告图像尺寸异常：page={page} size={image.size}")
                if "A" in image.getbands():
                    bg = Image.new("RGB", image.size, "white")
                    bg.paste(image, mask=image.getchannel("A"))
                    rgb = bg
                else:
                    rgb = image.convert("RGB")
                images.append(rgb)
                rec.update({"format": image.format, "width": image.width, "height": image.height, "mode": image.mode})
                misses = 0
                print("FX_PAGE_OK", json.dumps(rec, ensure_ascii=False), flush=True)
            else:
                misses += 1
                print("FX_PAGE_MISS", json.dumps(rec, ensure_ascii=False), flush=True)
                if misses >= 3:
                    break
            page_records.append(rec)
        if len(images) < 3:
            raise RuntimeError(f"公开逐页图像仅取得{len(images)}页")
        images[0].save(output, "PDF", resolution=150, save_all=True, append_images=images[1:], quality=95, optimize=False)
        return page_records, len(images)
    finally:
        for image in images:
            try:
                image.close()
            except Exception:
                pass


def validate_pdf(path: Path, min_pages: int, expected_text: str | None = None) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size < 30000:
        raise RuntimeError(f"PDF缺失或过小：{path}")
    if path.read_bytes()[:5] != b"%PDF-":
        raise RuntimeError(f"PDF文件头异常：{path}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"PDF页数不足：{path.name} pages={pages}")
    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=180)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf校验失败：{path.name}: {qpdf.stderr[-1000:]}")
    identity_match = None
    if expected_text:
        extracted = "".join((page.extract_text() or "") for page in reader.pages[: min(pages, 5)])
        identity_match = expected_text in re.sub(r"\s+", "", extracted)
        if not identity_match:
            raise RuntimeError(f"PDF未识别到预期文本：{expected_text}: {path.name}")
    first_base = PREVIEW_DIR / f"{path.stem}_page1"
    subprocess.run(["pdftoppm", "-f", "1", "-singlefile", "-png", "-r", "130", str(path), str(first_base)], check=True, timeout=180, capture_output=True)
    first_png = first_base.with_suffix(".png")
    last_base = PREVIEW_DIR / f"{path.stem}_last"
    subprocess.run(["pdftoppm", "-f", str(pages), "-l", str(pages), "-singlefile", "-png", "-r", "100", str(path), str(last_base)], check=True, timeout=180, capture_output=True)
    last_png = last_base.with_suffix(".png")
    for png in (first_png, last_png):
        if not png.exists() or png.stat().st_size < 7000:
            raise RuntimeError(f"PDF渲染检查失败：{path.name}")
    return {
        "pages": pages, "bytes": path.stat().st_size, "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode, "identity_text_match": identity_match,
        "first_page_preview": str(first_png), "last_page_preview": str(last_png),
    }


def build_package() -> None:
    reset()
    session = requests.Session()
    session.headers.update(HEADERS)
    records: list[dict[str, Any]] = []

    for report in REPORTS:
        output = REPORT_DIR / report["filename"]
        if report["kind"] == "sina_text_archive":
            text = fetch_sina_visible_text(session, report)
            build_text_archive_pdf(report, text, output)
            validation = validate_pdf(output, 2, COMPANY)
            rec = {
                **report, **validation,
                "filename": str(output.relative_to(ROOT)),
                "document_type": "公开网页研报正文存档版（非券商原始排版PDF）",
                "visible_text_characters": len(text),
            }
        else:
            page_records, page_count = download_fxbaogao_pages(session, report, output)
            validation = validate_pdf(output, 3, None)
            rec = {
                **report, **validation,
                "filename": str(output.relative_to(ROOT)),
                "document_type": "公开逐页报告图像重建PDF（保留原页面，非原始PDF容器）",
                "page_image_count": page_count,
                "page_image_records": page_records,
            }
        records.append(rec)
        print("REPORT_COMPLETE", json.dumps({k: rec[k] for k in ("order", "institution", "title", "filename", "pages", "bytes", "document_type")}, ensure_ascii=False), flush=True)

    records.sort(key=lambda x: x["order"])
    manifest = {
        "company": COMPANY,
        "stock_code": CODE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "report_count": len(records),
        "reports": records,
        "scope_note": "公开渠道可稳定取得的任子行券商原始PDF有限。本包收录1份保留券商原页面的逐页图像重建PDF，以及2份新浪财经公开研报正文存档版。文件名和清单已明确标注文件类型。",
        "validation": "所有PDF均完成文件头、页数、qpdf结构以及首末页渲染检查；文本存档版另完成公司名称匹配。",
    }
    (NOTES_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (NOTES_DIR / "SHA256SUMS.txt").write_text("\n".join(f"{r['sha256']}  {r['filename']}" for r in records) + "\n", encoding="utf-8")

    lines = [
        f"公司：{COMPANY}（{CODE}.SZ）",
        f"券商研究资料：{len(records)}份",
        "",
    ]
    for i, r in enumerate(records, 1):
        lines.extend([
            f"{i}. {r['institution']}｜{r['date']}｜{r['title']}",
            f"   分析师：{r['authors']}｜评级：{r['rating']}｜页数：{r['pages']}",
            f"   文件类型：{r['document_type']}",
            f"   文件：{r['filename']}",
            f"   公开来源：{r['source_url']}",
            "",
        ])
    lines.extend([
        "重要说明：",
        "- 太平洋证券报告由公开平台逐页报告图像按原顺序重建，页面内容保持原样。",
        "- 华金证券和平安证券文件依据新浪财经公开展示的研报正文制作，便于离线归档；不是券商原始版式PDF，可能不含原报告未公开展示的图表与附录。",
        "- 所有PDF及ZIP均已完成结构与完整性检查，SHA-256见SHA256SUMS.txt。",
    ])
    (NOTES_DIR / "资料清单与来源说明.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.as_posix())
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC校验失败：{bad}")
    result = {
        "zip_filename": ZIP_PATH.name,
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256(ZIP_PATH),
        "report_count": len(records),
        "reports": records,
    }
    RESULT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PACKAGE_COMPLETE", json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    build_package()
