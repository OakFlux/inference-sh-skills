from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib import colors

COMPANY = "国货航"
STOCK_CODE = "001391.SZ"
PACKAGE_STEM = "国货航_001391_券商深度报告_2份"
ROOT = Path(PACKAGE_STEM)
REPORT_DIR = ROOT / "01_券商报告"
NOTES_DIR = ROOT / "02_资料说明"
PREVIEW_DIR = Path("_previews_air_china_cargo_broker_reports")
ZIP_PATH = Path(f"{PACKAGE_STEM}.zip")
RESULT_JSON = Path("air_china_cargo_broker_reports_result.json")

HUAJIN_URLS = [
    "https://pdf.dfcfw.com/pdf/H3_AP202412121641280501_1.pdf?1734029656000.pdf=",
    "https://pdf.dfcfw.com/pdf/H3_AP202412121641280501_1.pdf",
]
HUAJIN_FILE = REPORT_DIR / "01_华金证券_2024-12-12_新股覆盖研究_国货航.pdf"
ZHEJIANG_FILE = REPORT_DIR / "02_浙商证券_2025-12-31_国货航深度报告_公开资料整理版.pdf"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Referer": "https://data.eastmoney.com/report/info/AP202412121641280501.html",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def download_huajin() -> str:
    HUAJIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    session = requests.Session()
    session.headers.update(HEADERS)
    for url in HUAJIN_URLS:
        for attempt in range(1, 5):
            tmp = HUAJIN_FILE.with_suffix(".pdf.part")
            try:
                if tmp.exists():
                    tmp.unlink()
                with session.get(url, stream=True, timeout=(45, 180), allow_redirects=True) as response:
                    print("HUAJIN_RESPONSE", response.status_code, response.url, response.headers.get("content-type"), flush=True)
                    response.raise_for_status()
                    with tmp.open("wb") as f:
                        for chunk in response.iter_content(1024 * 1024):
                            if chunk:
                                f.write(chunk)
                if tmp.stat().st_size < 200_000:
                    raise RuntimeError(f"file too small: {tmp.stat().st_size}")
                if tmp.read_bytes()[:5] != b"%PDF-":
                    raise RuntimeError("not a PDF")
                tmp.replace(HUAJIN_FILE)
                print("HUAJIN_DOWNLOADED", HUAJIN_FILE.stat().st_size, url, flush=True)
                return url
            except Exception as exc:
                last_error = exc
                print("HUAJIN_RETRY", url, attempt, repr(exc), flush=True)
                time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to download Huajin report: {last_error!r}")


def footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("STSong-Light", 8)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawString(20 * mm, 12 * mm, "国货航券商研究资料 - 公开资料整理版")
    canvas.drawRightString(190 * mm, 12 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def build_zhejiang_archive() -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    ZHEJIANG_FILE.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(ZHEJIANG_FILE), pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm, bottomMargin=20 * mm,
        title="浙商证券国货航深度报告公开资料整理版",
        author="OpenAI compilation from publicly available report metadata and synopsis",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("TitleCN", parent=styles["Title"], fontName="STSong-Light", fontSize=18, leading=26, alignment=TA_CENTER, spaceAfter=10)
    subtitle = ParagraphStyle("SubtitleCN", parent=styles["Normal"], fontName="STSong-Light", fontSize=10, leading=16, alignment=TA_CENTER, textColor=colors.HexColor("#555555"), spaceAfter=18)
    heading = ParagraphStyle("HeadingCN", parent=styles["Heading2"], fontName="STSong-Light", fontSize=13, leading=20, textColor=colors.HexColor("#1F3A5F"), spaceBefore=10, spaceAfter=6)
    body = ParagraphStyle("BodyCN", parent=styles["BodyText"], fontName="STSong-Light", fontSize=10.5, leading=18, alignment=TA_LEFT, spaceAfter=8)
    note = ParagraphStyle("NoteCN", parent=body, fontSize=9.5, leading=16, textColor=colors.HexColor("#555555"), backColor=colors.HexColor("#F3F5F7"), borderPadding=8, spaceAfter=12)

    story: list[Any] = []
    story.append(Paragraph("跨境电商方兴未艾，航空货运龙头顺势而为", title))
    story.append(Paragraph("国货航（001391）深度报告 - 公开资料整理版", subtitle))

    meta = [
        ["研究机构", "浙商证券股份有限公司"],
        ["发布日期", "2025年12月31日"],
        ["分析师", "李丹、李逸"],
        ["评级", "增持（首次覆盖）"],
        ["原始报告信息", "27页，公开检索记录显示约3597KB"],
    ]
    table = Table(meta, colWidths=[34 * mm, 112 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("LEADING", (0, 0), (-1, -1), 16),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E9EEF5")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B8C2CC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(
        "说明：公开渠道可以确认该报告的题名、机构、作者、评级、页数和核心摘要，但未能取得无需登录或付费即可下载的券商原始排版PDF。为避免把付费页面或摘要冒充完整研报，本文件仅对公开披露的研究框架和结论作重新表述，不是原始27页报告，也不包含未公开图表。",
        note,
    ))

    sections = [
        ("一、公司定位与业务结构", "报告将国货航定位为国内领先的航空物流综合服务商，并强调其载旗货运航空公司的稀缺性。公开摘要把业务分为航空货运、综合物流解决方案和航空货站服务三部分。2024年，航空货运仍是收入和毛利的主要来源；综合物流业务受益于跨境电商及高端制造品物流需求；货站业务规模较稳定，盈利状况有所改善。"),
        ("二、航空货运行业判断", "研究框架从需求、供给、运价和竞争格局四个方面分析行业周期。需求端与发达经济体增长及跨境电商出口相关；供给端受到新飞机产能、全货机改装节奏和客机腹舱运力恢复的约束。报告判断，部分关税政策变化会扰动美国方向需求，但欧洲方向增长及供给刚性仍可能支撑运价中枢。"),
        ("三、盈利弹性", "公开摘要认为，全货机运输业务对公司利润弹性贡献较大。报告采用运价情景分析：相对于2024年平均运价，若全货机运输价格变化10%，公司归母净利润可能相应变化约6亿元。该敏感性说明运价周期是估值判断中的关键变量。"),
        ("四、盈利预测与估值", "报告预计2025至2027年营业收入约为229.5亿元、249.2亿元和268.9亿元；归母净利润约为25.6亿元、27.1亿元和29.0亿元。按报告发布时市值测算，对应市盈率约28倍、27倍和25倍。基于跨境电商需求、航空运力约束和公司业务结构，报告首次覆盖并给予“增持”评级。"),
        ("五、主要风险", "报告提示的主要风险包括全球政治经济环境变化、航空货运量或运价低于预期，以及航空燃油价格波动。实际投资判断还需结合关税政策、汇率、运力投放和全球贸易周期等因素。"),
    ]
    for h, p in sections:
        story.append(Paragraph(h, heading))
        story.append(Paragraph(p, body))

    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("公开来源记录", heading))
    story.append(Paragraph("1. 九方智投公开研报页面：披露研究机构、日期及核心投资要点。", body))
    story.append(Paragraph("2. 股票分析报告网公开目录页：披露报告页数、文件大小、作者及评级，并标注原始文件为加密报告。", body))
    story.append(Paragraph("本整理版仅用于研究资料归档，不构成投资建议。", note))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print("ZHEJIANG_ARCHIVE_CREATED", ZHEJIANG_FILE, ZHEJIANG_FILE.stat().st_size, flush=True)


def validate_pdf(path: Path, expected_pages_min: int, expected_markers: list[str]) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size < 30_000:
        raise RuntimeError(f"Missing or undersized PDF: {path}")
    if path.read_bytes()[:5] != b"%PDF-":
        raise RuntimeError(f"Invalid PDF header: {path}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < expected_pages_min:
        raise RuntimeError(f"Unexpected page count {pages}: {path}")
    text = "\n".join((p.extract_text() or "") for p in reader.pages[: min(pages, 12)])
    compact = "".join(text.split()).upper()
    for marker in expected_markers:
        marker_compact = "".join(marker.split()).upper()
        if marker_compact not in compact:
            raise RuntimeError(f"Marker {marker!r} not found in {path}")
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=180)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed: {path}: {check.stderr[-1000:]}")
    return {"pages": pages, "bytes": path.stat().st_size, "sha256": sha256(path), "qpdf_return_code": check.returncode}


def render_first_page(path: Path, stem: str) -> str:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out = PREVIEW_DIR / stem
    subprocess.run(["pdftoppm", "-f", "1", "-singlefile", "-png", "-r", "140", str(path), str(out)], check=True, timeout=180)
    png = out.with_suffix(".png")
    if not png.exists() or png.stat().st_size < 10_000:
        raise RuntimeError(f"Failed to render {path}")
    return str(png)


def package() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    if PREVIEW_DIR.exists():
        shutil.rmtree(PREVIEW_DIR)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)

    huajin_source = download_huajin()
    build_zhejiang_archive()

    huajin = validate_pdf(HUAJIN_FILE, 8, ["国货航", "华金证券"])
    zhejiang = validate_pdf(ZHEJIANG_FILE, 2, ["国货航", "浙商证券", "公开资料整理版"])
    huajin["filename"] = str(HUAJIN_FILE.relative_to(ROOT))
    huajin["document_type"] = "券商原始排版PDF"
    huajin["title"] = "新股覆盖研究：国货航"
    huajin["institution"] = "华金证券"
    huajin["date"] = "2024-12-12"
    huajin["source_url"] = huajin_source
    huajin["first_page_preview"] = render_first_page(HUAJIN_FILE, "huajin_first")

    zhejiang["filename"] = str(ZHEJIANG_FILE.relative_to(ROOT))
    zhejiang["document_type"] = "公开资料整理版（非券商原始排版PDF）"
    zhejiang["title"] = "跨境电商方兴未艾，航空货运龙头顺势而为"
    zhejiang["institution"] = "浙商证券"
    zhejiang["date"] = "2025-12-31"
    zhejiang["analysts"] = ["李丹", "李逸"]
    zhejiang["rating"] = "增持（首次）"
    zhejiang["original_report_pages"] = 27
    zhejiang["first_page_preview"] = render_first_page(ZHEJIANG_FILE, "zhejiang_archive_first")

    records = [huajin, zhejiang]
    manifest = {
        "company": COMPANY,
        "stock_code": STOCK_CODE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "report_count": 2,
        "records": records,
        "note": "华金证券文件为公开可下载的原始研报PDF；浙商证券原始27页PDF在公开目录中被标记为加密报告，压缩包收录的是基于公开元数据和摘要重新表述的整理版。",
    }
    (NOTES_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (NOTES_DIR / "SHA256SUMS.txt").write_text("\n".join(f"{r['sha256']}  {r['filename']}" for r in records) + "\n", encoding="utf-8")
    lines = [
        f"公司：{COMPANY}（{STOCK_CODE}）",
        "券商研究资料：2份",
        "",
        "1. 华金证券《新股覆盖研究：国货航》：公开可下载的券商原始排版PDF。",
        "2. 浙商证券《跨境电商方兴未艾，航空货运龙头顺势而为》：公开资料整理版。公开目录显示原始报告共27页、作者李丹和李逸、首次给予增持评级，但原始PDF被标记为加密报告，未将付费或加密文件冒充为公开完整版。",
        "",
        "所有PDF均已完成文件头、页数、qpdf结构检查和首页渲染检查。",
    ]
    (NOTES_DIR / "资料清单与来源说明.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(ROOT.rglob("*")):
            if p.is_file():
                z.write(p, p.as_posix())
    with zipfile.ZipFile(ZIP_PATH) as z:
        bad = z.testzip()
        if bad:
            raise RuntimeError(f"Corrupt ZIP member: {bad}")
    result = {
        "zip_filename": ZIP_PATH.name,
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256(ZIP_PATH),
        "report_count": 2,
        "records": records,
    }
    RESULT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PACKAGE_COMPLETE", json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    package()
