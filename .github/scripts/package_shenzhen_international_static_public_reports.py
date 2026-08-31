from __future__ import annotations

import asyncio
import base64
import hashlib
import html as html_lib
import json
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import pymupdf
import requests
from bs4 import BeautifulSoup, Tag
from playwright.async_api import async_playwright
from pypdf import PdfReader

ROOT = Path.cwd()
PACKAGE = ROOT / "shenzhen_international_public_reports_verified"
REPORT_DIR = PACKAGE / "01_券商公司研究报告_公开阅读版"
OUTPUT = ROOT / "深圳国际_券商深度报告_3份_公开阅读版PDF.zip"

COMPANY = "深圳国际控股有限公司"
SHORT_NAME = "深圳国际"
STOCK_CODE = "00152"
TICKER = "00152.HK"
PREPARED_DATE = "2026-08-31"

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
        "min_text_chars": 5000,
        "min_pdf_pages": 5,
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
        "min_text_chars": 8500,
        "min_pdf_pages": 7,
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
        "min_text_chars": 8500,
        "min_pdf_pages": 7,
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


def fetch_html(url: str) -> tuple[str, str]:
    errors: list[str] = []
    for attempt in range(1, 5):
        try:
            response = session.get(url, timeout=(25, 180), allow_redirects=True)
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
    h1_candidates = soup.find_all("h1")
    h1 = next(
        (tag for tag in h1_candidates if title_prefix in tag.get_text(" ", strip=True)),
        h1_candidates[0] if h1_candidates else None,
    )
    if h1 is None:
        raise RuntimeError(f"Report title element not found: {record['report_id']}")

    fallback: Tag | None = None
    node: Tag | None = h1
    while node is not None:
        classes = " ".join(node.get("class") or [])
        text_len = len(compact(node.get_text(" ", strip=True)))
        if "ReportCard" in classes and text_len >= 3000:
            return node
        if fallback is None and text_len >= int(record["min_text_chars"]):
            fallback = node
        parent = node.parent
        node = parent if isinstance(parent, Tag) else None

    if fallback is not None:
        return fallback
    raise RuntimeError(f"Report content container not found: {record['report_id']}")


def clean_container(container: Tag, source_url: str) -> tuple[str, str, list[dict[str, Any]]]:
    source_text = container.get_text("\n", strip=True)
    soup = BeautifulSoup(str(container), "html.parser")
    root = soup.find()
    if root is None:
        raise RuntimeError("Unable to clone report container")

    for selector in ("script", "style", "svg", "button", "input", "textarea", "select", "noscript"):
        for tag in root.select(selector):
            tag.decompose()

    for tag in list(root.find_all(True)):
        text = tag.get_text(" ", strip=True)
        classes = " ".join(tag.get("class") or [])
        if any(
            marker in text
            for marker in (
                "点击免费查看完整报告",
                "你可能感兴趣",
                "我的下载",
                "登录后可查看",
            )
        ) and len(text) < 100:
            tag.decompose()
            continue
        if any(marker in classes.lower() for marker in ("footer", "like", "recommend")) and len(text) < 500:
            tag.decompose()
            continue
        tag.attrs = {
            key: value
            for key, value in tag.attrs.items()
            if key in {"src", "alt", "colspan", "rowspan"}
        }

    for anchor in list(root.find_all("a")):
        anchor.unwrap()

    embedded_images: list[dict[str, Any]] = []
    for image in list(root.find_all("img")):
        src = image.get("src") or ""
        if not src:
            image.decompose()
            continue
        absolute = urljoin(source_url, src)
        try:
            response = session.get(
                absolute,
                headers={"Referer": source_url, "Accept": "image/*,*/*;q=0.8"},
                timeout=(20, 120),
                allow_redirects=True,
            )
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "image/png").split(";", 1)[0]
            if not content_type.startswith("image/") or len(response.content) < 10_000:
                raise RuntimeError(
                    f"not a usable image: {content_type}, {len(response.content)} bytes"
                )
            encoded = base64.b64encode(response.content).decode("ascii")
            image["src"] = f"data:{content_type};base64,{encoded}"
            image["alt"] = image.get("alt") or "报告公开展示图片"
            embedded_images.append(
                {
                    "source": absolute,
                    "content_type": content_type,
                    "bytes": len(response.content),
                }
            )
        except Exception as exc:
            print(f"IMAGE OMIT {absolute}: {exc}")
            image.decompose()

    return str(root), source_text, embedded_images


def build_html(record: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    raw_html, final_url = fetch_html(str(record["source_url"]))
    soup = BeautifulSoup(raw_html, "html.parser")
    container = find_report_container(soup, record)
    cleaned_html, source_text, embedded_images = clean_container(container, final_url)
    source_chars = len(compact(source_text))
    if source_chars < int(record["min_text_chars"]):
        raise RuntimeError(
            f"Public source text appears incomplete for {record['report_id']}: "
            f"{source_chars} chars"
        )
    source_norm = compact(source_text)
    if not any(
        compact(marker) in source_norm
        for marker in (SHORT_NAME, "深圳國際", STOCK_CODE, "0152.hk")
    ):
        raise RuntimeError(f"Company marker missing: {record['report_id']}")
    for marker in record["title_markers"]:
        if compact(marker) not in source_norm:
            raise RuntimeError(
                f"Title marker {marker!r} missing: {record['report_id']}"
            )

    document_html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{record['broker']}：{record['title']}</title>
<style>
  @page {{ size: A4; margin: 15mm 14mm 16mm 14mm; }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{
    font-family: "Noto Sans CJK SC", "Noto Sans SC", "Microsoft YaHei", sans-serif;
    font-size: 10.5pt; line-height: 1.62; color: #222; background: white;
  }}
  .notice {{ padding: 10px 12px; margin: 0 0 15px; border: 1px solid #aaa;
    background: #f5f5f5; font-size: 9.2pt; line-height: 1.45; }}
  .meta {{ margin: 0 0 16px; padding-bottom: 10px; border-bottom: 1px solid #bbb; }}
  .meta h1 {{ margin: 0 0 7px; font-size: 19pt; line-height: 1.35; }}
  .meta p {{ margin: 2px 0; color: #444; }}
  h1 {{ font-size: 19pt; line-height: 1.35; margin: 0 0 10px; }}
  h2 {{ font-size: 15.5pt; margin: 21px 0 8px; page-break-after: avoid; }}
  h3 {{ font-size: 13.2pt; margin: 17px 0 7px; page-break-after: avoid; }}
  h4,h5,h6 {{ font-size: 11.5pt; margin: 13px 0 6px; page-break-after: avoid; }}
  p {{ margin: 7px 0; text-align: justify; orphans: 3; widows: 3; }}
  img {{ display: block; max-width: 100%; height: auto; margin: 10px auto;
    page-break-inside: avoid; }}
  table {{ width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 9pt; }}
  th, td {{ border: 1px solid #aaa; padding: 4px 6px; vertical-align: top; }}
  ul, ol {{ padding-left: 22px; }}
  li {{ margin: 3px 0; }}
  div {{ max-height: none !important; overflow: visible !important; }}
</style>
</head>
<body>
<div class="notice"><strong>公开阅读版PDF</strong><br>
本文件由无需登录即可访问的公开阅读正文转存，非券商原生版式PDF；保留公开正文、标题及公开展示图片。原始下载入口要求登录，未使用或绕过该机制。</div>
<div class="meta">
<h1>{record['title']}</h1>
<p>公司：{COMPANY}（{TICKER}）</p>
<p>券商：{record['broker']}　研究员：{record['researcher']}　发布日期：{record['publish_date']}</p>
<p>类型：{record['report_type']}</p>
</div>
{cleaned_html}
</body></html>"""
    return document_html, {
        "source_page": final_url,
        "source_text_characters": source_chars,
        "source_html_bytes": len(raw_html.encode("utf-8")),
        "embedded_images": embedded_images,
    }


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
            f"Generated PDF is unexpectedly short: {path} ({pages} pages)"
        )

    document = pymupdf.open(path)
    if document.page_count != pages:
        raise RuntimeError(f"Page-count mismatch: {path}")
    text = "\n".join(document.load_page(i).get_text("text") for i in range(pages))
    normalized = compact(text)
    required_any = [
        (SHORT_NAME, "深圳國際", STOCK_CODE, "0152.hk"),
        (str(record["broker"]),),
        ("风险提示", "風險提示", "风险因素", "風險因素"),
    ]
    for group in required_any:
        if not any(compact(marker) in normalized for marker in group):
            raise RuntimeError(f"Required marker {group} missing from PDF: {path}")
    for marker in record["title_markers"]:
        if compact(marker) not in normalized:
            raise RuntimeError(f"Title marker {marker!r} missing from PDF: {path}")
    text_chars = len(normalized)
    if text_chars < int(record["min_text_chars"]):
        raise RuntimeError(
            f"Generated PDF text incomplete: {path}; chars={text_chars}"
        )

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
        "text_characters": text_chars,
        "text_searchable": True,
    }


async def main() -> None:
    if PACKAGE.exists():
        shutil.rmtree(PACKAGE)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.unlink(missing_ok=True)

    documents: list[dict[str, Any]] = []
    checksum_lines: list[str] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        for index, record in enumerate(REPORTS, 1):
            html_doc, source_meta = build_html(record)
            await page.set_content(html_doc, wait_until="load", timeout=60_000)
            await page.wait_for_timeout(800)
            filename = safe_filename(
                f"{index:02d}_{record['broker']}_{record['publish_date'].replace('-', '')}_"
                f"{record['title']}_公开阅读版.pdf"
            )
            target = REPORT_DIR / filename
            await page.pdf(
                path=str(target),
                format="A4",
                print_background=True,
                margin={"top": "8mm", "right": "8mm", "bottom": "10mm", "left": "8mm"},
                prefer_css_page_size=True,
                display_header_footer=False,
            )
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
                    "非券商原生排版PDF，部分图表版式可能不同。"
                ),
            }
            documents.append(item)
            checksum_lines.append(f"{item['sha256']}  {rel_path}")
            print(
                f"BUILT {record['broker']} | {record['title']} | "
                f"source_chars={source_meta['source_text_characters']} "
                f"pdf_pages={metadata['pages']} pdf_chars={metadata['text_characters']} "
                f"images={len(source_meta['embedded_images'])} bytes={metadata['bytes']}"
            )
        await browser.close()

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
        "   标题、正文和公开展示图片予以保留，但部分原始图表版式可能不同。",
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
    asyncio.run(main())
