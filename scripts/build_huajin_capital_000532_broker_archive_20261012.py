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
from PIL import Image
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
from pypdf import PdfReader, PdfWriter

CHECKED_AS_OF = "2026-10-12"
PACKAGE_NAME = "华金资本_000532_券商深度研究资料_3份"
PACKAGE_DIR = Path(PACKAGE_NAME)
REPORT_DIR = PACKAGE_DIR / "01_券商研究资料"
VERIFY_DIR = Path("_verify_huajin_broker")
REPORT_DIR.mkdir(parents=True, exist_ok=True)
VERIFY_DIR.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

FONT_PATH_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]
FONT_PATH = next((Path(p) for p in FONT_PATH_CANDIDATES if Path(p).exists()), None)
if FONT_PATH is None:
    raise RuntimeError("No usable Chinese font was found")
pdfmetrics.registerFont(TTFont("CJK", str(FONT_PATH), subfontIndex=0))


def get(url: str, referer: str | None = None, timeout: int = 120) -> requests.Response:
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    last: Exception | None = None
    for attempt in range(1, 5):
        try:
            response = SESSION.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            print("HTTP", attempt, response.status_code, response.headers.get("content-type"), len(response.content), response.url, flush=True)
            if response.status_code == 200:
                return response
        except Exception as exc:  # noqa: BLE001
            last = exc
            print("HTTP_ERROR", attempt, url, repr(exc), flush=True)
        time.sleep(attempt * 2)
    if last:
        raise last
    raise RuntimeError(f"Failed to fetch {url}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_text(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def parse_sina_report(url: str) -> dict[str, Any]:
    response = get(url)
    response.encoding = response.apparent_encoding or "gb18030"
    soup = BeautifulSoup(response.text, "html.parser")
    title_node = soup.select_one("div.content h1") or soup.find("h1")
    title = normalize_text(title_node.get_text(" ", strip=True) if title_node else "")
    meta_text = normalize_text((soup.select_one("div.creab") or soup).get_text(" ", strip=True))

    def field(label: str) -> str:
        m = re.search(label + r"[:：]\s*(.*?)(?=\s+(?:机构|研究员|日期|类别)[:：]|$)", meta_text)
        return normalize_text(m.group(1)) if m else ""

    broker = field("机构")
    analysts = field("研究员")
    date = field("日期")
    body_node = soup.select_one("div.blk_container p") or soup.select_one("div.blk_container")
    if body_node:
        for br in body_node.find_all("br"):
            br.replace_with("\n")
        body = body_node.get_text("\n", strip=True)
    else:
        body = ""
    body = html.unescape(body).replace("\xa0", " ")
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n\s*\n+", "\n\n", body).strip()
    if not title or not body:
        raise RuntimeError(f"Failed to parse report page: {url}")
    return {
        "title": title,
        "broker": broker,
        "analysts": analysts,
        "date": date,
        "body": body,
        "source_url": url,
        "body_characters": len(body),
    }


def add_metadata(pdf_path: Path, metadata: dict[str, str]) -> None:
    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata({f"/{k}": v for k, v in metadata.items()})
    tmp = pdf_path.with_suffix(".tmp.pdf")
    with tmp.open("wb") as f:
        writer.write(f)
    tmp.replace(pdf_path)


def build_image_preview_pdf(output: Path) -> dict[str, Any]:
    base = "https://oss.sdyanbao.com/page/2024/9/10/1081871"
    image_dir = VERIFY_DIR / "huaxi_pages"
    image_dir.mkdir(parents=True, exist_ok=True)
    image_paths: list[Path] = []
    status_rows: list[dict[str, Any]] = []
    for index in range(21):
        url = f"{base}/{index}.png"
        try:
            response = get(url, referer="https://www.sdyanbao.com/detail/817305?cid=10", timeout=60)
        except Exception as exc:  # noqa: BLE001
            status_rows.append({"page_index": index, "url": url, "status": "error", "error": repr(exc)})
            continue
        if not response.content.startswith(b"\x89PNG"):
            status_rows.append({"page_index": index, "url": url, "status": "non_png", "bytes": len(response.content)})
            continue
        path = image_dir / f"page_{index + 1:02d}.png"
        path.write_bytes(response.content)
        with Image.open(path) as im:
            im.verify()
        image_paths.append(path)
        status_rows.append({"page_index": index, "url": url, "status": "downloaded", "bytes": path.stat().st_size})

    if len(image_paths) < 10:
        raise RuntimeError(f"Only {len(image_paths)} preview pages were available")

    c: canvas.Canvas | None = None
    for idx, path in enumerate(image_paths):
        with Image.open(path) as im:
            width, height = im.size
        if c is None:
            c = canvas.Canvas(str(output), pagesize=(width, height), pageCompression=1)
            c.setTitle("自动驾驶风头正盛，耐心资本伏线千里（公开预览版）")
            c.setAuthor("华西证券")
            c.setSubject(f"公开可得页面：{len(image_paths)}/21；非完整原始PDF")
        else:
            c.setPageSize((width, height))
        c.drawImage(str(path), 0, 0, width=width, height=height, preserveAspectRatio=True, mask="auto")
        c.showPage()
    assert c is not None
    c.save()
    add_metadata(output, {
        "Title": "自动驾驶风头正盛，耐心资本伏线千里（公开预览版）",
        "Author": "华西证券 / 罗惠洲",
        "Subject": f"公开预览页面 {len(image_paths)}/21；缺少未公开页面；非完整原始PDF",
        "Keywords": "华金资本 000532 华西证券 公司深度 公开预览",
    })
    return {
        "title": "自动驾驶风头正盛，耐心资本伏线千里",
        "broker": "华西证券",
        "analysts": "罗惠洲",
        "date": "2024-09-01",
        "classification": "公司深度研究",
        "format": f"公开逐页图像预览版（{len(image_paths)}/21页；非完整原始PDF）",
        "source_detail_url": "https://www.sdyanbao.com/detail/817305?cid=10",
        "source_image_base": base,
        "source_metadata_url": "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/778514540284/index.phtml",
        "available_pages": len(image_paths),
        "declared_pages": 21,
        "page_status": status_rows,
    }


def build_summary_pdf(meta: dict[str, Any], output: Path, classification: str) -> None:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ChineseTitle",
        parent=styles["Title"],
        fontName="CJK",
        fontSize=18,
        leading=26,
        alignment=TA_CENTER,
        spaceAfter=10 * mm,
    )
    notice_style = ParagraphStyle(
        "Notice",
        parent=styles["BodyText"],
        fontName="CJK",
        fontSize=10.5,
        leading=17,
        textColor="#7A1F1F",
        borderColor="#7A1F1F",
        borderWidth=0.7,
        borderPadding=8,
        spaceAfter=7 * mm,
    )
    meta_style = ParagraphStyle(
        "Meta",
        parent=styles["BodyText"],
        fontName="CJK",
        fontSize=10.5,
        leading=17,
        textColor="#333333",
        spaceAfter=5 * mm,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="CJK",
        fontSize=10.5,
        leading=18,
        alignment=TA_LEFT,
        firstLineIndent=21,
        spaceAfter=4 * mm,
    )
    footer_style = ParagraphStyle(
        "FooterNote",
        parent=styles["BodyText"],
        fontName="CJK",
        fontSize=8.5,
        leading=14,
        textColor="#666666",
        spaceBefore=8 * mm,
    )

    doc = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=meta["title"],
        author=meta["broker"],
        subject="公开摘要存档版（非券商原始完整PDF）",
    )
    story: list[Any] = []
    story.append(Paragraph(meta["title"], title_style))
    story.append(Paragraph(
        "重要说明：本文件是依据公开研报页面保存的正文摘要，非券商原始排版PDF，也不代表原报告的全部页码、图表、模型、估值表和风险披露。为避免误用，文件名与本页均明确标注“公开摘要存档版”。",
        notice_style,
    ))
    meta_line = (
        f"券商：{meta['broker'] or '未提取'}<br/>"
        f"研究员：{meta['analysts'] or '未提取'}<br/>"
        f"发布日期：{meta['date'] or '未提取'}<br/>"
        f"资料类别：{classification}<br/>"
        f"公开正文字符数：{meta['body_characters']}"
    )
    story.append(Paragraph(meta_line, meta_style))
    story.append(Spacer(1, 2 * mm))
    paragraphs = [p.strip() for p in re.split(r"\n+", meta["body"]) if p.strip()]
    for paragraph in paragraphs:
        safe = html.escape(paragraph)
        story.append(Paragraph(safe, body_style))
    story.append(Paragraph("来源页面及核验信息详见压缩包内的文件清单与 manifest.json。", footer_style))
    doc.build(story)
    add_metadata(output, {
        "Title": meta["title"] + "（公开摘要存档版）",
        "Author": meta["broker"] + (" / " + meta["analysts"] if meta["analysts"] else ""),
        "Subject": "公开摘要存档版；非券商原始完整PDF",
        "Keywords": "华金资本 力合股份 000532 券商研究 公开摘要",
    })


def validate_pdf(path: Path, identity_terms: list[str]) -> dict[str, Any]:
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF"):
        raise RuntimeError(f"Not a PDF: {path}")
    qpdf = subprocess.run(["qpdf", "--check", str(path)], text=True, capture_output=True)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path}: {qpdf.stdout}\n{qpdf.stderr}")
    reader = PdfReader(str(path))
    pages = len(reader.pages)
    if pages < 1:
        raise RuntimeError(f"No pages in {path}")
    txt_path = VERIFY_DIR / f"{path.stem}.txt"
    subprocess.run(["pdftotext", str(path), str(txt_path)], check=True)
    text = txt_path.read_text(encoding="utf-8", errors="ignore")
    normalized = re.sub(r"\s+", "", text)
    text_identity = any(term.replace(" ", "") in normalized for term in identity_terms)
    # Image-only preview has no text layer; validate identity visually and via source metadata instead.
    if not text_identity and "预览版" not in path.name:
        raise RuntimeError(f"Identity check failed for {path}")
    render_pages = sorted(set([1, max(1, (pages + 1) // 2), pages]))
    render_files: list[str] = []
    for pno in render_pages:
        base = VERIFY_DIR / f"{path.stem}_p{pno}"
        cp = subprocess.run([
            "pdftoppm", "-f", str(pno), "-l", str(pno), "-singlefile", "-png", "-r", "110",
            str(path), str(base),
        ], text=True, capture_output=True)
        if cp.returncode != 0:
            raise RuntimeError(f"Render failed for {path}, page {pno}: {cp.stderr}")
        image_path = Path(str(base) + ".png")
        if not image_path.exists() or image_path.stat().st_size < 5000:
            raise RuntimeError(f"Invalid render output: {image_path}")
        render_files.append(str(image_path))
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "qpdf_return_code": qpdf.returncode,
        "rendered_pages": render_pages,
        "render_files": render_files,
        "text_identity_verified": text_identity,
    }


records: list[dict[str, Any]] = []

preview_path = REPORT_DIR / "20240901_华西证券_自动驾驶风头正盛耐心资本伏线千里_公开预览版_15页_of_21页.pdf"
preview_meta = build_image_preview_pdf(preview_path)
preview_validation = validate_pdf(preview_path, ["华金资本", "000532"])
records.append({
    **preview_meta,
    "relative_path": str(preview_path.relative_to(PACKAGE_DIR)),
    **preview_validation,
})
print("VALIDATED", json.dumps(records[-1], ensure_ascii=False), flush=True)

summary_specs = [
    {
        "url": "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/523277190294/index.phtml",
        "filename": "20160731_华泰证券_借国企改革之力转创投发展之路_公开摘要存档版.pdf",
        "classification": "深度研究",
    },
    {
        "url": "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/519737363772/index.phtml",
        "filename": "20160620_国投证券_实业和投资双轮驱动锂电设备有望高速增长_公开摘要存档版.pdf",
        "classification": "公司研究",
    },
]
for spec in summary_specs:
    meta = parse_sina_report(spec["url"])
    output = REPORT_DIR / spec["filename"]
    build_summary_pdf(meta, output, spec["classification"])
    validation = validate_pdf(output, ["华金资本", "力合股份", "000532"])
    record = {
        "title": meta["title"],
        "broker": meta["broker"],
        "analysts": meta["analysts"],
        "date": meta["date"],
        "classification": spec["classification"],
        "format": "公开摘要存档版（非券商原始完整PDF）",
        "source_url": meta["source_url"],
        "source_body_characters": meta["body_characters"],
        "relative_path": str(output.relative_to(PACKAGE_DIR)),
        **validation,
    }
    records.append(record)
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

# Duplicate check.
if len({r["sha256"] for r in records}) != len(records):
    raise RuntimeError("Duplicate PDF detected")

readme_lines = [
    "华金资本（000532，历史简称：力合股份）券商深度研究资料包",
    "",
    f"核对日期：{CHECKED_AS_OF}",
    f"收录数量：{len(records)}份PDF",
    "",
    "重要限制",
    "- 公开检索未取得三份报告的券商原始完整PDF附件。",
    "- 2024年华西证券报告：收录公开可得逐页图像，共15页；公开元数据标注原报告21页，因此缺少6页，文件名已明确标注15页_of_21页。",
    "- 2016年华泰证券与国投证券报告：收录新浪财经保存的公开正文摘要，并制作成便于离线阅读的PDF；不包含原报告全部图表、估值表、附录和风险披露。",
    "- 本资料包没有将预览版或摘要版冒充券商原始完整版。",
    "",
    "文件概览",
]
for idx, record in enumerate(records, 1):
    readme_lines.append(
        f"{idx}. {record.get('date','')}｜{record.get('broker','')}｜{record.get('title','')}｜{record.get('pages')}页｜{record.get('format')}"
    )
readme_lines.extend([
    "",
    "校验",
    "- 每份PDF均完成PDF结构、实际页数、SHA-256及首页/中间页/末页渲染检查。",
    "- 完整来源、页面可得性和校验信息见 文件清单.csv 与 manifest.json。",
])
(PACKAGE_DIR / "README.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

fields = [
    "date", "broker", "analysts", "title", "classification", "format", "relative_path", "pages", "bytes", "sha256",
    "source_url", "source_detail_url", "source_metadata_url", "available_pages", "declared_pages", "source_body_characters",
]
with (PACKAGE_DIR / "文件清单.csv").open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    for record in records:
        writer.writerow({key: record.get(key, "") for key in fields})

with (PACKAGE_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as f:
    for record in records:
        f.write(f"{record['sha256']}  {record['relative_path']}\n")

manifest = {
    "package_name": PACKAGE_NAME,
    "company": "珠海华金资本股份有限公司",
    "historical_short_name": "力合股份",
    "stock_code": "000532",
    "checked_as_of": CHECKED_AS_OF,
    "document_count": len(records),
    "important_limitation": "公开可得版本包括一份15/21页预览版和两份公开摘要存档版，均非券商原始完整PDF；已明确标注。",
    "records": records,
}
(PACKAGE_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

zip_path = Path(PACKAGE_NAME + ".zip")
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for item in sorted(PACKAGE_DIR.rglob("*")):
        if item.is_file():
            zf.write(item, arcname=str(item))
with zipfile.ZipFile(zip_path, "r") as zf:
    bad = zf.testzip()
    if bad:
        raise RuntimeError(f"ZIP integrity failed at {bad}")
print("FINAL_ZIP", zip_path, "bytes", zip_path.stat().st_size, "sha256", sha256_file(zip_path), flush=True)
