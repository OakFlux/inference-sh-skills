from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pymupdf
from playwright.async_api import Page, async_playwright
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
        "min_text_chars": 6500,
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
        "min_text_chars": 12000,
        "min_pdf_pages": 8,
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
        "min_text_chars": 12000,
        "min_pdf_pages": 8,
    },
]


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


async def prepare_public_reading_page(page: Page, record: dict[str, Any]) -> dict[str, Any]:
    response = await page.goto(
        record["source_url"], wait_until="domcontentloaded", timeout=120_000
    )
    if response is None or response.status >= 400:
        raise RuntimeError(
            f"Unable to open source page {record['source_url']}: "
            f"status={response.status if response else None}"
        )
    await page.wait_for_timeout(3000)
    await page.wait_for_function(
        "() => document.querySelector('h1') && document.body.innerText.length > 5000",
        timeout=60_000,
    )

    source_data = await page.evaluate(
        """
        (expectedTitle) => {
          const h1s = Array.from(document.querySelectorAll('h1'));
          const h1 = h1s.find(el => (el.innerText || '').includes(expectedTitle.slice(0, 8))) || h1s[0];
          if (!h1) throw new Error('Report title element not found');

          let chosen = null;
          let node = h1;
          while (node && node !== document.body) {
            const text = (node.innerText || '').trim();
            if (text.length >= 5000) {
              chosen = node;
              break;
            }
            node = node.parentElement;
          }
          if (!chosen) throw new Error('Report content container not found');

          const sourceText = (chosen.innerText || '').trim();
          const sourceHtmlLength = chosen.outerHTML.length;
          const originalImages = Array.from(chosen.querySelectorAll('img')).map(img => ({
            src: img.currentSrc || img.src,
            alt: img.alt || '',
            width: img.naturalWidth || 0,
            height: img.naturalHeight || 0,
          }));

          const clone = chosen.cloneNode(true);
          clone.querySelectorAll('script,style,svg,button,input,textarea,select').forEach(el => el.remove());
          clone.querySelectorAll('*').forEach(el => {
            el.removeAttribute('class');
            el.removeAttribute('style');
            el.removeAttribute('onclick');
            el.removeAttribute('target');
          });

          // Remove site actions and recommendations while preserving the report body.
          clone.querySelectorAll('a').forEach(a => {
            const text = (a.innerText || '').trim();
            const href = a.getAttribute('href') || '';
            if (/点击免费查看完整报告|我的下载|登录|注册|收藏|分享/.test(text) || /\/view\?id=/.test(href)) {
              a.remove();
            } else {
              const span = document.createElement('span');
              span.innerHTML = a.innerHTML;
              a.replaceWith(span);
            }
          });
          Array.from(clone.querySelectorAll('h2,h3,div')).forEach(el => {
            const text = (el.innerText || '').trim();
            if (/^你可能感兴趣$|^相关推荐$|^热门报告$/.test(text)) el.remove();
          });

          const banner = document.createElement('div');
          banner.id = 'public-reading-note';
          banner.innerHTML = '<strong>公开阅读版PDF</strong><br>本文件由无需登录即可访问的公开阅读正文转存，非券商原生版式PDF；保留公开正文、标题及公开展示图片。';

          document.body.innerHTML = '';
          document.body.appendChild(banner);
          document.body.appendChild(clone);
          document.documentElement.setAttribute('lang', 'zh-CN');

          const css = document.createElement('style');
          css.textContent = `
            @page { size: A4; margin: 15mm 14mm 16mm 14mm; }
            * { box-sizing: border-box; }
            html, body { margin: 0; padding: 0; }
            body {
              font-family: "Noto Sans CJK SC", "Noto Sans SC", "Microsoft YaHei", sans-serif;
              font-size: 10.5pt; line-height: 1.62; color: #222; background: #fff;
              overflow: visible !important;
            }
            #public-reading-note {
              padding: 10px 12px; margin: 0 0 16px 0; border: 1px solid #aaa;
              background: #f5f5f5; font-size: 9.5pt; line-height: 1.45;
            }
            h1 { font-size: 20pt; line-height: 1.35; margin: 0 0 10px; }
            h2 { font-size: 16pt; margin: 22px 0 8px; page-break-after: avoid; }
            h3 { font-size: 13.5pt; margin: 18px 0 7px; page-break-after: avoid; }
            h4,h5,h6 { font-size: 11.5pt; margin: 14px 0 6px; page-break-after: avoid; }
            p { margin: 7px 0; text-align: justify; orphans: 3; widows: 3; }
            img { display: block; max-width: 100%; height: auto; margin: 10px auto; page-break-inside: avoid; }
            table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 9pt; page-break-inside: avoid; }
            th,td { border: 1px solid #aaa; padding: 4px 6px; vertical-align: top; }
            ul,ol { padding-left: 22px; }
            li { margin: 3px 0; }
            div { max-height: none !important; overflow: visible !important; }
          `;
          document.head.appendChild(css);

          return {
            sourceText,
            sourceHtmlLength,
            originalImages,
            title: document.title,
          };
        }
        """,
        record["title"],
    )
    await page.wait_for_timeout(1200)
    return source_data


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
            f"Generated public-reading PDF is unexpectedly short: {path} ({pages} pages)"
        )

    document = pymupdf.open(path)
    if document.page_count != pages:
        raise RuntimeError(f"Page count mismatch: {path}")
    text = "\n".join(document.load_page(i).get_text("text") for i in range(pages))
    normalized = compact(text)
    required_groups = [
        (SHORT_NAME, "深圳國際", STOCK_CODE, "0152.hk"),
        (str(record["broker"]),),
        tuple(record["title_markers"]),
        ("风险提示", "風險提示", "风险因素", "風險因素"),
    ]
    for group in required_groups:
        if group is required_groups[2]:
            # All title markers must be present.
            if any(compact(marker) not in normalized for marker in group):
                raise RuntimeError(f"Title marker missing from generated PDF: {path}")
        elif not any(compact(marker) in normalized for marker in group):
            raise RuntimeError(f"Required marker {group} missing from generated PDF: {path}")

    if len(compact(text)) < int(record["min_text_chars"]):
        raise RuntimeError(
            f"Generated PDF text is incomplete: {path}; chars={len(compact(text))}"
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
        "text_characters": len(compact(text)),
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
        context = await browser.new_context(
            viewport={"width": 1280, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36"
            ),
            locale="zh-CN",
        )
        for index, record in enumerate(REPORTS, 1):
            page = await context.new_page()
            try:
                source_data = await prepare_public_reading_page(page, record)
                source_text_chars = len(compact(source_data["sourceText"]))
                if source_text_chars < int(record["min_text_chars"]):
                    raise RuntimeError(
                        f"Public source text appears incomplete for {record['report_id']}: "
                        f"{source_text_chars} chars"
                    )
                source_norm = compact(source_data["sourceText"])
                if not any(
                    compact(marker) in source_norm
                    for marker in (SHORT_NAME, "深圳國際", STOCK_CODE, "0152.hk")
                ):
                    raise RuntimeError(
                        f"Company marker missing from public source: {record['report_id']}"
                    )
                for marker in record["title_markers"]:
                    if compact(marker) not in source_norm:
                        raise RuntimeError(
                            f"Title marker {marker!r} missing from public source: "
                            f"{record['report_id']}"
                        )

                filename = safe_filename(
                    f"{index:02d}_{record['broker']}_{record['publish_date'].replace('-', '')}_"
                    f"{record['title']}_公开阅读版.pdf"
                )
                target = REPORT_DIR / filename
                await page.pdf(
                    path=str(target),
                    format="A4",
                    print_background=True,
                    margin={"top": "10mm", "right": "10mm", "bottom": "12mm", "left": "10mm"},
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
                    "source_page": record["source_url"],
                    "source_report_id": record["report_id"],
                    "source_text_characters": source_text_chars,
                    "source_html_length": source_data["sourceHtmlLength"],
                    "public_images_detected": source_data["originalImages"],
                    "delivery_note": (
                        "由无需登录即可访问的公开阅读正文转存为可检索PDF；"
                        "并非券商原生排版PDF，部分图表仅在来源页面公开展示时才会保留。"
                    ),
                }
                documents.append(item)
                checksum_lines.append(f"{item['sha256']}  {rel_path}")
                print(
                    f"BUILT {record['broker']} {record['title']} | "
                    f"source_chars={source_text_chars} pdf_pages={metadata['pages']} "
                    f"pdf_chars={metadata['text_characters']} bytes={metadata['bytes']}"
                )
            finally:
                await page.close()
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
        "2. 报告下载入口要求账户登录，未使用或绕过该登录机制。",
        "3. 本包将公开阅读正文转存为可检索PDF，不是券商原生排版PDF；",
        "   标题、正文、公开展示图片和来源信息予以保留，但个别原始图表版式可能不同。",
        "4. 适合阅读、检索和归档；如需券商原版，请通过有权访问的研报终端或券商渠道取得。",
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
