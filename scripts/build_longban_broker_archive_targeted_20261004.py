from __future__ import annotations

import hashlib
import html
import io
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

import img2pdf
import requests
from PIL import Image
from pypdf import PdfReader
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

CHECK_DATE = "2026-10-04"
COMPANY = "龙版传媒"
CODE = "605577"
PACKAGE_NAME = f"龙版传媒_{CODE}_券商研究报告_3份_公开资料存档版_{CHECK_DATE}"
ROOT = Path(PACKAGE_NAME)
REPORT_DIR = ROOT / "01_报告文件"
META_DIR = ROOT / "02_来源与校验"
WORK_DIR = Path("_longban_targeted_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (REPORT_DIR, META_DIR, WORK_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})

REPORTS = [
    {
        "kind": "company_summary",
        "title": "龙版传媒：深耕出版业务主业，业绩发展稳健",
        "institution": "东北证券",
        "report_date": "2023-12-05",
        "analysts": "王凤华、王璐",
        "rating": "买入",
        "original_pages": 4,
        "original_size": "705KB",
        "source_url": "https://www.nxny.com/report/view_5499041.html",
        "stock_index_url": "https://www.nxny.com/stock/stock_605577/",
        "output_name": "01_东北证券_龙版传媒_深耕出版业务主业业绩发展稳健_公开索引存档.pdf",
    },
    {
        "kind": "sdyanbao",
        "detail_id": 922418,
        "title": "传媒行业专题报告：关注央国企传媒标的的动态变化",
        "institution": "方正证券",
        "report_date": "2025-10-06",
        "analysts": "焦娟、冯静静",
        "source_url": "https://www.sdyanbao.com/detail/922418",
        "output_name": "02_方正证券_传媒行业专题_关注央国企传媒标的的动态变化.pdf",
    },
    {
        "kind": "sdyanbao",
        "detail_id": 969983,
        "title": "出版行业2025年报及2026年一季报业绩综述：出版板块业绩分化，高股息价值凸显",
        "institution": "浙商证券",
        "report_date": "2026-05-10",
        "analysts": "冯翠婷",
        "source_url": "https://www.sdyanbao.com/detail/969983",
        "output_name": "03_浙商证券_出版行业2025年报及2026年一季报业绩综述.pdf",
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request(method: str, url: str, *, timeout: tuple[int, int] = (20, 180), **kwargs: Any) -> requests.Response:
    errors: list[str] = []
    extra_headers = kwargs.pop("headers", {})
    headers = {**SESSION.headers, **extra_headers}
    for attempt in range(1, 7):
        try:
            response = SESSION.request(
                method,
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
                **kwargs,
            )
            print(
                "HTTP", method, url, "attempt", attempt, "status", response.status_code,
                "type", response.headers.get("content-type"), "length", response.headers.get("content-length"),
                "final", response.url,
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            time.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"request failed for {url}: {errors}")


def unescape_js(text: str) -> str:
    text = text.replace("\\u002F", "/").replace("\\/", "/")
    try:
        return bytes(text, "utf-8").decode("unicode_escape")
    except Exception:
        return text


def regex_first(patterns: list[str], text: str, default: str = "") -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I | re.S)
        if match:
            return html.unescape(unescape_js(match.group(1))).strip()
    return default


def fetch_text(url: str) -> tuple[str, str]:
    response = request("GET", url, headers={"Referer": "https://www.sdyanbao.com/"})
    try:
        return response.text, str(response.url)
    finally:
        response.close()


def parse_sdyanbao(report: dict[str, Any]) -> dict[str, Any]:
    text, final_url = fetch_text(report["source_url"])
    page_url = regex_first([
        r'page_url:\s*"([^"]+)"',
        r'"page_url"\s*:\s*"([^"]+)"',
    ], text)
    share_url = regex_first([
        r'share_url:\s*"([^"]+)"',
        r'"share_url"\s*:\s*"([^"]+)"',
    ], text)
    data_uuid = regex_first([
        r'data_source_uuid:\s*"([^"]+)"',
        r'"data_source_uuid"\s*:\s*"([^"]+)"',
    ], text)
    original_id = regex_first([
        r'original_id:\s*(\d+)',
        r'"original_id"\s*:\s*(\d+)',
    ], text)
    page_count_text = regex_first([
        r'page_count:\s*(\d+)',
        r'"page_count"\s*:\s*(\d+)',
    ], text)
    file_size_text = regex_first([
        r'file_size:\s*(\d+)',
        r'"file_size"\s*:\s*(\d+)',
    ], text)
    time_text = regex_first([
        r'time_text:\s*"([^"]+)"',
        r'"time_text"\s*:\s*"([^"]+)"',
    ], text, report["report_date"])
    if not page_url and share_url:
        page_url = share_url.rsplit("/", 1)[0]
    if not page_url:
        # Stable public path can be inferred when original_id is present.
        if original_id:
            parts = time_text.split("-")
            if len(parts) == 3:
                page_url = f"https://oss.sdyanbao.com/page/{int(parts[0])}/{int(parts[1])}/{int(parts[2])}/{original_id}"
    if not page_count_text:
        # Search-engine indexed copy may expose this phrase in HTML.
        page_count_text = regex_first([r"本报告共\s*(\d+)\s*页", r"pageCount[^\d]*(\d+)"], text)
    if not page_url:
        raise RuntimeError(f"Could not parse page_url for detail {report['detail_id']}")
    metadata = {
        "detail_url": final_url,
        "page_url": page_url,
        "share_url": share_url,
        "data_source_uuid": data_uuid,
        "original_id": original_id,
        "expected_pages": int(page_count_text) if page_count_text else None,
        "declared_file_size": int(file_size_text) if file_size_text else None,
        "time_text": time_text,
    }
    print("SDYANBAO_METADATA", json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)
    return metadata


def download_pdf_candidate(url: str, target: Path) -> bool:
    temp = target.with_suffix(target.suffix + ".part")
    temp.unlink(missing_ok=True)
    try:
        response = request("GET", url, timeout=(20, 300), stream=True, headers={"Referer": "https://data.eastmoney.com/"})
    except Exception as exc:  # noqa: BLE001
        print("PDF_CANDIDATE_ERROR", url, repr(exc), flush=True)
        return False
    try:
        with temp.open("wb") as handle:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    handle.write(chunk)
    finally:
        response.close()
    head = temp.read_bytes()[:8] if temp.exists() else b""
    if not temp.exists() or temp.stat().st_size < 20_000 or not head.startswith(b"%PDF-"):
        print("PDF_CANDIDATE_INVALID", url, temp.stat().st_size if temp.exists() else 0, head, flush=True)
        temp.unlink(missing_ok=True)
        return False
    temp.replace(target)
    print("PDF_CANDIDATE_OK", url, target.stat().st_size, flush=True)
    return True


def download_image(url: str, target: Path) -> dict[str, Any] | None:
    temp = target.with_suffix(target.suffix + ".part")
    temp.unlink(missing_ok=True)
    try:
        response = request("GET", url, timeout=(20, 180), stream=True, headers={"Referer": "https://www.sdyanbao.com/"})
    except Exception as exc:  # noqa: BLE001
        print("IMAGE_ERROR", url, repr(exc), flush=True)
        return None
    try:
        with temp.open("wb") as handle:
            for chunk in response.iter_content(512 * 1024):
                if chunk:
                    handle.write(chunk)
    finally:
        response.close()
    if not temp.exists() or temp.stat().st_size < 3000:
        temp.unlink(missing_ok=True)
        return None
    try:
        with Image.open(temp) as image:
            image.verify()
        with Image.open(temp) as image:
            width, height = image.size
            image_format = image.format or ""
        if width < 500 or height < 700:
            raise RuntimeError(f"unexpected dimensions {width}x{height}")
    except Exception as exc:  # noqa: BLE001
        print("IMAGE_INVALID", url, repr(exc), flush=True)
        temp.unlink(missing_ok=True)
        return None
    temp.replace(target)
    return {"url": url, "bytes": target.stat().st_size, "width": width, "height": height, "format": image_format}


def images_to_pdf(images: list[Path], output: Path) -> None:
    # img2pdf keeps raster pixels intact and avoids needless recompression.
    with output.open("wb") as handle:
        handle.write(img2pdf.convert([str(path) for path in images]))


def build_sdyanbao_pdf(report: dict[str, Any], output: Path) -> dict[str, Any]:
    metadata = parse_sdyanbao(report)
    expected_pages = metadata.get("expected_pages")
    data_uuid = metadata.get("data_source_uuid") or ""

    # Prefer a complete public original PDF when the upstream identifier is exposed.
    pdf_urls: list[str] = []
    if re.fullmatch(r"AP\d+", data_uuid, flags=re.I):
        pdf_urls.extend([
            f"https://pdf.dfcfw.com/pdf/H3_{data_uuid.upper()}_1.pdf",
            f"https://pdf.dfcfw.com/pdf/H2_{data_uuid.upper()}_1.pdf",
        ])
    for pdf_url in pdf_urls:
        if download_pdf_candidate(pdf_url, output):
            try:
                pages = len(PdfReader(str(output), strict=False).pages)
            except Exception:
                pages = 0
            if not expected_pages or pages == expected_pages:
                return {
                    **metadata,
                    "delivery_type": "公开原始PDF",
                    "source_pdf_url": pdf_url,
                    "archived_page_urls": [],
                }
            print("ORIGINAL_PDF_PAGE_MISMATCH", pdf_url, pages, expected_pages, flush=True)
            output.unlink(missing_ok=True)

    # Fallback: archive every publicly available page image in sequence.
    page_dir = WORK_DIR / f"detail_{report['detail_id']}"
    page_dir.mkdir(parents=True, exist_ok=True)
    image_paths: list[Path] = []
    image_records: list[dict[str, Any]] = []
    upper_bound = expected_pages if expected_pages else 80
    consecutive_misses = 0
    for index in range(upper_bound):
        path = page_dir / f"{index:03d}.png"
        url = f"{metadata['page_url'].rstrip('/')}/{index}.png"
        record = download_image(url, path)
        if record is None:
            consecutive_misses += 1
            if index == 0 or consecutive_misses >= 2:
                break
            continue
        consecutive_misses = 0
        image_paths.append(path)
        image_records.append({"page_index": index, **record})
    if not image_paths:
        raise RuntimeError(f"No public page images obtained for {report['detail_id']}")
    images_to_pdf(image_paths, output)
    full = bool(expected_pages and len(image_paths) == expected_pages)
    return {
        **metadata,
        "delivery_type": "公开逐页图片存档PDF" if full else "公开预览页存档PDF",
        "source_pdf_url": "",
        "archived_page_urls": image_records,
        "public_pages_archived": len(image_paths),
        "is_complete_against_declared_page_count": full,
    }


def clean_public_text(raw: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def build_company_index_pdf(report: dict[str, Any], output: Path) -> dict[str, Any]:
    source_snapshots: list[dict[str, Any]] = []
    public_text = ""
    for url in (report["source_url"], report["stock_index_url"]):
        try:
            raw, final_url = fetch_text(url)
            cleaned = clean_public_text(raw)
            source_snapshots.append({"requested_url": url, "final_url": final_url, "bytes": len(raw.encode('utf-8'))})
            if report["title"] in cleaned or ("龙版传媒" in cleaned and "东北证券" in cleaned):
                public_text = cleaned
        except Exception as exc:  # noqa: BLE001
            source_snapshots.append({"requested_url": url, "error": repr(exc)})

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ChineseTitle", parent=styles["Title"], fontName="STSong-Light", fontSize=18,
        leading=26, alignment=TA_CENTER, spaceAfter=10 * mm,
    )
    heading = ParagraphStyle(
        "ChineseHeading", parent=styles["Heading2"], fontName="STSong-Light", fontSize=12,
        leading=18, alignment=TA_LEFT, spaceBefore=4 * mm, spaceAfter=2 * mm,
    )
    body = ParagraphStyle(
        "ChineseBody", parent=styles["BodyText"], fontName="STSong-Light", fontSize=9.5,
        leading=15, alignment=TA_LEFT, spaceAfter=2.5 * mm,
    )
    small = ParagraphStyle(
        "ChineseSmall", parent=body, fontSize=8, leading=12,
    )
    doc = SimpleDocTemplate(
        str(output), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=report["title"], author=report["institution"],
    )
    story: list[Any] = [
        Paragraph(report["title"], title_style),
        Paragraph("公开研报索引存档版", heading),
        Paragraph(
            "本文件用于保存公开渠道能够核验的报告元数据和来源入口。公开渠道未提供无需登录即可取得的券商原始完整PDF，"
            "因此本文件不是东北证券原始研报，也未对受权限限制的正文进行重制。", body,
        ),
    ]
    rows = [
        ["项目", "公开可核验信息"],
        ["证券简称 / 代码", f"龙版传媒 / {CODE}.SH"],
        ["报告机构", report["institution"]],
        ["报告日期", report["report_date"]],
        ["分析师", report["analysts"]],
        ["评级", report["rating"]],
        ["原报告页数 / 大小", f"{report['original_pages']}页 / {report['original_size']}"],
        ["公开来源", report["source_url"]],
    ]
    table = Table(rows, colWidths=[43 * mm, 112 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEADING", (0, 0), (-1, -1), 13),
        ("GRID", (0, 0), (-1, -1), 0.4, (0.45, 0.45, 0.45)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), (0.92, 0.92, 0.92)),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([table, Spacer(1, 6 * mm)])
    story.append(Paragraph("检索结论", heading))
    story.append(Paragraph(
        "截至核对日，公开研报索引中可核验的龙版传媒公司专项正式研报数量较少；该报告为当前检索到的公司专项覆盖。"
        "为补足研究资料，本压缩包另收录两份正文明确讨论龙版传媒或其所在出版板块的行业专题报告。", body,
    ))
    story.append(Paragraph("使用说明", heading))
    story.append(Paragraph(
        "请将本索引文件与压缩包内的行业专题报告配合使用。涉及盈利预测、目标价、估值参数等内容，应以券商原始PDF为准；"
        "本索引文件不补写、不推断原报告正文，也不构成投资建议。", body,
    ))
    story.append(PageBreak())
    story.append(Paragraph("来源核验记录", heading))
    for item in source_snapshots:
        if item.get("error"):
            story.append(Paragraph(f"来源：{item['requested_url']}；访问结果：{item['error']}", small))
        else:
            story.append(Paragraph(
                f"来源：{item['requested_url']}；最终地址：{item['final_url']}；HTML字节数：{item['bytes']}", small,
            ))
    if public_text:
        # Only include a short factual index excerpt; do not reproduce a report body.
        match = re.search(r"(东北证券.{0,500}龙版传媒.{0,800})", public_text)
        excerpt = match.group(1) if match else public_text[:900]
        excerpt = excerpt[:900]
        story.extend([
            Spacer(1, 4 * mm),
            Paragraph("公开页面索引摘录（截断）", heading),
            Paragraph(excerpt, small),
        ])
    doc.build(story)
    return {
        "delivery_type": "公开研报索引存档PDF（非券商原始PDF）",
        "source_snapshots": source_snapshots,
        "original_report_pages": report["original_pages"],
        "original_report_size": report["original_size"],
    }


def render_page(path: Path, page_number: int, tag: str) -> None:
    prefix = RENDER_DIR / f"{hashlib.sha1(path.name.encode('utf-8')).hexdigest()}_{tag}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number), "-r", "90",
            "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True, text=True, timeout=300,
    )
    image = Path(str(prefix) + ".png")
    if process.returncode != 0 or not image.exists() or image.stat().st_size < 1000:
        raise RuntimeError(f"render check failed for {path.name} page {page_number}: {process.stderr[-1200:]}")
    image.unlink()


def validate_pdf(path: Path) -> dict[str, Any]:
    check = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=300)
    if check.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed for {path.name}: {check.stderr[-2000:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < 1:
        raise RuntimeError(f"zero-page PDF: {path}")
    render_page(path, 1, "first")
    if pages > 1:
        render_page(path, pages, "last")
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": check.returncode,
        "first_and_last_page_rendered": True,
    }


def main() -> None:
    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for report in REPORTS:
        output = REPORT_DIR / report["output_name"]
        output.unlink(missing_ok=True)
        if report["kind"] == "company_summary":
            delivery = build_company_index_pdf(report, output)
        else:
            delivery = build_sdyanbao_pdf(report, output)
        checks = validate_pdf(output)
        if checks["sha256"] in seen_hashes:
            raise RuntimeError(f"duplicate output PDF: {output.name}")
        seen_hashes.add(checks["sha256"])
        record = {
            "title": report["title"],
            "institution": report["institution"],
            "report_date": report["report_date"],
            "analysts": report.get("analysts"),
            "file": output.relative_to(ROOT).as_posix(),
            "source_url": report["source_url"],
            **delivery,
            **checks,
        }
        records.append(record)

    readme = [
        f"龙版传媒（{CODE}.SH）券商研究资料包",
        f"核对日期：{CHECK_DATE}",
        "",
        "收录说明：",
        "1. 公开数据库中可核验的龙版传媒公司专项券商报告只有1份，且原始完整PDF受登录或下载权限限制。",
        "2. 第一份文件因此为公开研报索引存档PDF，不是东北证券原始研报；未补写或仿制受限正文。",
        "3. 另外两份为出版/传媒行业专题报告，正文明确将龙版传媒纳入样本或讨论范围。系统优先保存公开原始PDF；若上游未开放原PDF，则保存公开逐页图片或预览页并在清单中标注。",
        "4. 所有文件仅供个人研究与资料核对，版权归原机构及作者所有，不构成投资建议。",
        "",
        "文件清单：",
    ]
    for index, record in enumerate(records, start=1):
        readme.extend([
            f"{index}. {record['institution']}《{record['title']}》",
            f"   日期：{record['report_date']}；分析师：{record.get('analysts') or '公开页面未列出'}",
            f"   交付类型：{record['delivery_type']}",
            f"   文件：{record['file']}",
            f"   实际页数：{record['pages']}；大小：{record['bytes']} bytes",
            f"   来源：{record['source_url']}",
            f"   SHA-256：{record['sha256']}",
            "",
        ])
    (META_DIR / "README_文件清单与口径说明.txt").write_text("\n".join(readme), encoding="utf-8")
    (META_DIR / "manifest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    (META_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{record['sha256']}  {record['file']}" for record in records) + "\n",
        encoding="utf-8",
    )

    final_zip = Path(PACKAGE_NAME + ".zip")
    final_zip.unlink(missing_ok=True)
    with zipfile.ZipFile(final_zip, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.as_posix())
    with zipfile.ZipFile(final_zip, "r") as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP integrity test failed at {bad}")
    print("FINAL_ZIP", final_zip, final_zip.stat().st_size, flush=True)
    print("FINAL_MANIFEST", json.dumps(records, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
