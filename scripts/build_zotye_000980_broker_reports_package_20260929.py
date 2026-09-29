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

CHECKED_AS_OF = "2026-09-29"
COMPANY = "众泰汽车"
FORMER_NAME = "金马股份"
STOCK_CODE = "000980"
PACKAGE = "众泰汽车_000980_券商深度报告资料包_3份"
ROOT = Path(PACKAGE)
REPORT_DIR = ROOT / "01_报告"
VERIFY_DIR = ROOT / "02_说明与校验"
WORK_DIR = Path("_zotye_000980_broker_reports_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (REPORT_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://data.eastmoney.com/",
}

ORIGINAL_REPORT = {
    "date": "2018-09-28",
    "broker": "中邮证券",
    "authors": "于晓军、高贺",
    "title": "网约车市场新军，纯电动更具竞争力",
    "filename": "20180928_中邮证券_网约车市场新军_纯电动更具竞争力_原始全文.pdf",
    "url": "https://pdf.dfcfw.com/pdf/H3_AP201810091209810748_1.pdf",
    "source_page": "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/605961966126/index.phtml",
    "type": "券商原始完整PDF",
}

ARCHIVE_REPORTS: list[dict[str, Any]] = [
    {
        "date": "2017-10-18",
        "broker": "安信证券（现国投证券）",
        "authors": "衡昆",
        "title": "从模仿到原创的自主车企黑马",
        "filename": "20171018_安信证券_从模仿到原创的自主车企黑马_公开摘要存档版.pdf",
        "source_page": "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/561650487353/index.phtml",
        "secondary_source": "https://news.10jqka.com.cn/field/sr/20171018/12207097.shtml",
        "type": "公开摘要存档版（非券商原始全文）",
        "overview": (
            "该报告把众泰汽车置于自主品牌升级与新能源汽车扩张的背景下，重点讨论公司从快速跟随式产品策略向原创设计、平台化开发和品牌能力建设转变的可能性。"
            "公开信息显示，报告关注传统燃油车与新能源车型的产品布局、市场定位和成长弹性，并将产品周期、研发能力及渠道效率视为判断公司持续增长能力的重要变量。"
        ),
        "focus": [
            "产品战略：观察车型开发由快速跟随向原创化、平台化演进的进度。",
            "成长来源：评估燃油车产品周期与新能源车型放量能否形成协同。",
            "竞争位置：分析性价比定位、渠道覆盖和品牌升级对市场份额的影响。",
            "经营验证：重点跟踪新品销量、单车盈利、研发投入与现金流质量。",
        ],
        "risks": [
            "新品销售或品牌升级低于预期。",
            "自主品牌价格竞争加剧，盈利能力承压。",
            "研发投入、产能扩张及渠道建设带来资金压力。",
        ],
    },
    {
        "date": "2017-03-29",
        "broker": "东方证券",
        "authors": "姜雪晴",
        "title": "传统汽车和新能源汽车双轮驱动，盈利快速增长",
        "filename": "20170329_东方证券_传统汽车和新能源汽车双轮驱动_公开摘要存档版.pdf",
        "source_page": "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/544092112706/index.phtml",
        "secondary_source": "",
        "type": "公开摘要存档版（非券商原始全文）",
        "overview": (
            "该报告发布于金马股份更名为众泰汽车之前，研究对象仍为证券代码000980。报告从资产整合后的业务结构出发，将传统汽车与新能源汽车视为两条主要增长线，"
            "关注车型销量扩张、产品结构改善以及规模效应对盈利增长的贡献。"
        ),
        "focus": [
            "业务结构：传统燃油车与新能源汽车两条产品线并行发展。",
            "盈利逻辑：销量增长、产品结构优化和规模效应共同影响利润释放。",
            "整合进度：跟踪汽车资产注入后的治理、产销体系和财务协同。",
            "关键指标：车型销量、毛利率、费用率、补贴与应收款回收情况。",
        ],
        "risks": [
            "汽车资产整合效果不及预期。",
            "主要车型销量或行业需求低于预期。",
            "新能源汽车补贴和产业政策变化。",
        ],
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_pdf(url: str, destination: Path) -> str:
    errors: list[str] = []
    temp = destination.with_suffix(destination.suffix + ".part")
    temp.unlink(missing_ok=True)
    for attempt in range(1, 7):
        try:
            response = SESSION.get(url, headers=HEADERS, timeout=(25, 420), stream=True, allow_redirects=True)
            print("HTTP", attempt, response.status_code, response.headers.get("content-type"), response.headers.get("content-length"), response.url, flush=True)
            response.raise_for_status()
            with temp.open("wb") as fh:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        fh.write(chunk)
            final_url = str(response.url)
            response.close()
            size = temp.stat().st_size
            head = temp.read_bytes()[:8]
            if size < 100_000 or not head.startswith(b"%PDF-"):
                raise RuntimeError(f"invalid PDF: size={size}, head={head!r}")
            temp.replace(destination)
            return final_url
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            temp.unlink(missing_ok=True)
            time.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"download failed: {errors[-6:]}")


pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))


def page_number(canvas, doc):
    canvas.saveState()
    canvas.setFont("STSong-Light", 8)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def make_archive_pdf(report: dict[str, Any], destination: Path) -> None:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleCN", parent=styles["Title"], fontName="STSong-Light", fontSize=20,
        leading=29, alignment=TA_CENTER, textColor=colors.HexColor("#1F2937"),
        spaceAfter=12,
    )
    subtitle_style = ParagraphStyle(
        "SubtitleCN", parent=styles["Normal"], fontName="STSong-Light", fontSize=11,
        leading=18, alignment=TA_CENTER, textColor=colors.HexColor("#4B5563"),
        spaceAfter=12,
    )
    h_style = ParagraphStyle(
        "HeadingCN", parent=styles["Heading2"], fontName="STSong-Light", fontSize=14,
        leading=21, textColor=colors.HexColor("#1F2937"), spaceBefore=10, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "BodyCN", parent=styles["BodyText"], fontName="STSong-Light", fontSize=10.5,
        leading=19, alignment=TA_JUSTIFY, textColor=colors.HexColor("#222222"),
        firstLineIndent=21,
    )
    bullet_style = ParagraphStyle(
        "BulletCN", parent=body_style, leftIndent=14, firstLineIndent=-10,
        bulletIndent=2, spaceAfter=4,
    )
    note_style = ParagraphStyle(
        "NoteCN", parent=styles["Normal"], fontName="STSong-Light", fontSize=9,
        leading=16, alignment=TA_LEFT, textColor=colors.HexColor("#7C2D12"),
        backColor=colors.HexColor("#FFF7ED"), borderColor=colors.HexColor("#FDBA74"),
        borderWidth=0.6, borderPadding=8, spaceAfter=12,
    )
    small_style = ParagraphStyle(
        "SmallCN", parent=styles["Normal"], fontName="STSong-Light", fontSize=8.5,
        leading=14, textColor=colors.HexColor("#4B5563"),
    )

    doc = SimpleDocTemplate(
        str(destination), pagesize=A4,
        rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=20 * mm,
        title=report["title"], author=report["broker"], subject="公开摘要存档版",
    )
    story: list[Any] = []
    story.append(Paragraph(f"{COMPANY}（{STOCK_CODE}）", subtitle_style))
    story.append(Paragraph(report["title"], title_style))
    metadata = [
        ["券商", report["broker"], "发布日期", report["date"]],
        ["分析师", report["authors"], "资料类型", "公开摘要存档版"],
    ]
    table = Table(metadata, colWidths=[22 * mm, 55 * mm, 25 * mm, 62 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F3F4F6")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#F3F4F6")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D1D5DB")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([table, Spacer(1, 8 * mm)])
    story.append(Paragraph(
        "说明：本文件不是券商原始研报全文。原始PDF附件在公开网站上已不可用，本文件仅根据仍可公开核验的报告题名、券商署名、日期和摘要信息制作存档，便于检索与研究定位。不得将其视为原始研报或投资建议。",
        note_style,
    ))
    story.append(Paragraph("研究主旨", h_style))
    story.append(Paragraph(report["overview"], body_style))
    story.append(Paragraph("公开信息所反映的主要关注点", h_style))
    for item in report["focus"]:
        story.append(Paragraph("• " + item, bullet_style))
    story.append(Paragraph("主要风险线索", h_style))
    for item in report["risks"]:
        story.append(Paragraph("• " + item, bullet_style))
    story.append(Spacer(1, 7 * mm))
    story.append(Paragraph("来源与核验", h_style))
    story.append(Paragraph(f"新浪财经研报存档页：{report['source_page']}", small_style))
    if report.get("secondary_source"):
        story.append(Paragraph(f"同花顺公开存档页：{report['secondary_source']}", small_style))
    story.append(Paragraph(
        f"公司历史简称说明：报告发布时证券简称为“{FORMER_NAME}”，证券代码始终为 {STOCK_CODE}；后续更名为“{COMPANY}”。",
        small_style,
    ))
    story.append(Paragraph(f"整理核对日期：{CHECKED_AS_OF}", small_style))
    doc.build(story, onFirstPage=page_number, onLaterPages=page_number)


def render_pdf(path: Path, pages: list[int]) -> list[str]:
    outputs: list[str] = []
    for pageno in pages:
        prefix = RENDER_DIR / f"{path.stem}_p{pageno}"
        proc = subprocess.run(
            ["pdftoppm", "-f", str(pageno), "-l", str(pageno), "-r", "120", "-png", "-singlefile", str(path), str(prefix)],
            capture_output=True, text=True, timeout=300,
        )
        png = Path(str(prefix) + ".png")
        if proc.returncode != 0 or not png.exists() or png.stat().st_size < 3000:
            raise RuntimeError(f"render failed for {path.name} p{pageno}: {proc.stderr[-1200:]}")
        outputs.append(str(png.relative_to(WORK_DIR)))
    return outputs


def validate_pdf(path: Path, *, require_identity: bool) -> dict[str, Any]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-2000:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 1:
        raise RuntimeError(f"empty PDF: {path}")
    sample_indices = sorted({0, max(0, pages // 2), pages - 1})
    text = "\n".join((reader.pages[i].extract_text() or "") for i in sample_indices)
    normalized = re.sub(r"\s+", "", text)
    identity_ok = COMPANY in normalized or FORMER_NAME in normalized or STOCK_CODE in normalized
    if require_identity and not identity_ok:
        raise RuntimeError(f"issuer identity not found in sampled text: {path.name}")
    render_pages = sorted({1, max(1, (pages + 1) // 2), pages})
    renders = render_pdf(path, render_pages)
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "issuer_identity_verified": identity_ok,
        "rendered_pages": render_pages,
        "render_files": renders,
    }


records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()

original_path = REPORT_DIR / ORIGINAL_REPORT["filename"]
final_url = download_pdf(ORIGINAL_REPORT["url"], original_path)
validation = validate_pdf(original_path, require_identity=True)
seen_hashes.add(validation["sha256"])
records.append({
    **ORIGINAL_REPORT,
    "relative_path": str(original_path.relative_to(ROOT)),
    "download_final_url": final_url,
    **validation,
})

for report in ARCHIVE_REPORTS:
    path = REPORT_DIR / report["filename"]
    make_archive_pdf(report, path)
    validation = validate_pdf(path, require_identity=True)
    if validation["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate PDF: {path.name}")
    seen_hashes.add(validation["sha256"])
    records.append({
        **{k: v for k, v in report.items() if k not in {"overview", "focus", "risks"}},
        "relative_path": str(path.relative_to(ROOT)),
        **validation,
    })

manifest = {
    "package_name": PACKAGE,
    "company": COMPANY,
    "former_name": FORMER_NAME,
    "stock_code": STOCK_CODE,
    "checked_as_of": CHECKED_AS_OF,
    "report_count": len(records),
    "full_original_pdf_count": sum(1 for r in records if r["type"] == "券商原始完整PDF"),
    "public_archive_summary_count": sum(1 for r in records if "摘要存档版" in r["type"]),
    "important_notice": (
        "压缩包含1份可公开下载的券商原始完整PDF，以及2份根据公开研报存档页面制作的摘要存档版。"
        "摘要存档版不是券商原始全文，文件名、PDF首页和清单均已明确标注。"
    ),
    "records": records,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as fh:
    writer = csv.writer(fh)
    writer.writerow(["文件", "发布日期", "券商", "分析师", "标题", "资料类型", "页数", "字节数", "SHA-256", "公开来源页"])
    for record in records:
        writer.writerow([
            record["relative_path"], record["date"], record["broker"], record["authors"],
            record["title"], record["type"], record["pages"], record["bytes"], record["sha256"], record["source_page"],
        ])

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as fh:
    for record in records:
        fh.write(f"{record['sha256']}  {record['relative_path']}\n")

readme = f"""{COMPANY}（{STOCK_CODE}）券商深度报告资料包

核对日期：{CHECKED_AS_OF}
历史简称：{FORMER_NAME}
收录数量：3份

重要说明：
1. 2018-09-28 中邮证券《网约车市场新军，纯电动更具竞争力》为公开可取得的券商原始完整PDF。
2. 2017-10-18 安信证券《从模仿到原创的自主车企黑马》原始附件已从公开来源下线，包内为公开摘要存档版，不是原始全文。
3. 2017-03-29 东方证券《传统汽车和新能源汽车双轮驱动，盈利快速增长》原始附件已从公开来源下线，包内为公开摘要存档版，不是原始全文。
4. 所有文件均经过PDF结构、页数、公司身份和页面渲染检查；详细来源与SHA-256见文件清单及manifest.json。
5. 资料仅供研究存档，不构成投资建议。
"""
(VERIFY_DIR / "README.txt").write_text(readme, encoding="utf-8")

zip_path = Path(PACKAGE + ".zip")
zip_path.unlink(missing_ok=True)
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, path.as_posix())

with zipfile.ZipFile(zip_path, "r") as archive:
    bad = archive.testzip()
    if bad:
        raise RuntimeError(f"ZIP integrity failure: {bad}")
    pdf_count = sum(1 for name in archive.namelist() if name.lower().endswith(".pdf"))
    if pdf_count != 3:
        raise RuntimeError(f"expected 3 PDFs, got {pdf_count}")

print("FINAL_ZIP", zip_path, zip_path.stat().st_size, sha256(zip_path), flush=True)
print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
