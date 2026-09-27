from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright
from pypdf import PdfReader

PACKAGE = "中国船舶租赁_03877_券商研究报告_3份"
ROOT = Path(PACKAGE)
REPORT_DIR = ROOT / "01_券商研究材料"
NOTE_DIR = ROOT / "02_资料说明"
PREVIEW_DIR = Path("_previews_cssc_shipping")
for folder in (REPORT_DIR, NOTE_DIR, PREVIEW_DIR):
    folder.mkdir(parents=True, exist_ok=True)

REPORTS = [
    {
        "index": 1,
        "institution": "浙商证券",
        "title": "船厂系船舶租赁商龙头，股息率具备吸引力——中国船舶租赁首次覆盖报告",
        "date": "2025-01-06",
        "url": "https://finance.sina.com.cn/roll/2025-01-06/doc-inecztfz5629046.shtml",
        "filename": "01_浙商证券_船厂系船舶租赁商龙头股息率具备吸引力_20250106.pdf",
        "form": "公开全文转载页面存档PDF",
        "scope": "首次覆盖公司深度研究，讨论船厂系背景、逆周期投资、经营模式、船队资产、盈利预测、估值与风险因素。",
        "minimum_chars": 2200,
        "minimum_pages": 3,
    },
    {
        "index": 2,
        "institution": "国泰君安证券",
        "title": "首次覆盖中国船舶租赁：受益油运景气上升，分红率或有望提升",
        "date": "2024-03-06",
        "url": "https://finance.sina.com.cn/tob/2024-03-06/doc-inamkitr0146131.shtml",
        "filename": "02_国泰君安证券_首次覆盖受益油运景气上升分红率或有望提升_20240306.pdf",
        "form": "公开券商研究摘要页面存档PDF",
        "scope": "首次覆盖研究摘要，讨论逆周期造船、长期成本优势、短租盈利弹性、油运景气及分红率提升空间。",
        "minimum_chars": 600,
        "minimum_pages": 1,
    },
    {
        "index": 3,
        "institution": "国金证券",
        "title": "首次覆盖中国船舶租赁：逆周期投资能力、运营能力与高分红属性",
        "date": "2026-02-09",
        "url": "https://finance.sina.com.cn/tob/2026-02-09/doc-inhmfcph5422941.shtml",
        "filename": "03_国金证券_首次覆盖逆周期投资运营能力与高分红属性_20260209.pdf",
        "form": "公开券商研究摘要页面存档PDF",
        "scope": "首次覆盖研究摘要，讨论多元业务结构、逆周期投资、船队运营、融资成本、盈利预测、估值及股息率。",
        "minimum_chars": 750,
        "minimum_pages": 1,
    },
]


def compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "").upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_article(page, report: dict) -> dict:
    page.wait_for_timeout(2200)
    for _ in range(7):
        page.mouse.wheel(0, 1400)
        page.wait_for_timeout(250)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(900)

    return page.evaluate(
        r"""
        ({minimumChars}) => {
          const norm = s => (s || '').replace(/\s+/g, ' ').trim();
          const selectors = [
            '#artibody',
            'div#artibody',
            '#articleContent',
            '#article-content',
            '.article-content',
            '.article_content',
            '.article-body',
            '.articleBody',
            '[data-sudaclick="content"]',
            'article'
          ];
          const removeSelectors = [
            'script','style','noscript','iframe','video','audio','canvas','form','button','input','textarea','select',
            'nav','footer','aside',
            '[class*="comment"]','[id*="comment"]','[class*="share"]','[id*="share"]',
            '[class*="advert"]','[id*="advert"]','[class*="recommend"]','[id*="recommend"]',
            '[class*="related"]','[id*="related"]','[class*="toolbar"]','[id*="toolbar"]',
            '[class*="breadcrumb"]','[class*="pagination"]','[class*="login"]','[class*="qrcode"]',
            '[class*="app-download"]','[class*="stock"]','[class*="finance_app"]'
          ];

          function cleaned(node, selector, priority) {
            const clone = node.cloneNode(true);
            for (const sel of removeSelectors) {
              for (const child of clone.querySelectorAll(sel)) child.remove();
            }
            for (const img of clone.querySelectorAll('img')) {
              const lazy = img.getAttribute('data-original') || img.getAttribute('data-src') || img.getAttribute('data-lazy-src') || img.getAttribute('data-url');
              if (lazy) img.setAttribute('src', lazy);
              const raw = img.getAttribute('src') || '';
              try { img.setAttribute('src', new URL(raw, location.href).href); } catch (e) {}
              img.removeAttribute('srcset');
              img.removeAttribute('loading');
              img.removeAttribute('width');
              img.removeAttribute('height');
            }
            for (const a of clone.querySelectorAll('a')) {
              const href = a.getAttribute('href') || '';
              try { a.setAttribute('href', new URL(href, location.href).href); } catch (e) {}
            }
            const text = norm(clone.innerText);
            return {node, clone, selector, priority, text, length: text.length};
          }

          const candidates = [];
          selectors.forEach((selector, priority) => {
            for (const node of document.querySelectorAll(selector)) {
              const item = cleaned(node, selector, priority);
              if (item.length >= 250 && item.length <= 50000 && (item.text.includes('中国船舶租赁') || item.text.includes('船舶租赁'))) {
                candidates.push(item);
              }
            }
          });

          if (!candidates.length) {
            const all = [...document.querySelectorAll('div,main,section')];
            for (const node of all) {
              const raw = norm(node.innerText);
              if (raw.length < minimumChars || raw.length > 30000) continue;
              if (!raw.includes('中国船舶租赁') && !raw.includes('船舶租赁')) continue;
              const item = cleaned(node, 'fallback', 100);
              candidates.push(item);
            }
          }

          if (!candidates.length) throw new Error('No article body candidate found');
          candidates.sort((a,b) => (a.priority - b.priority) || (a.length - b.length));
          let best = candidates.find(x => x.length >= minimumChars) || candidates[candidates.length - 1];
          const headline = document.querySelector('h1') ? norm(document.querySelector('h1').innerText) : '';
          return {
            html: best.clone.outerHTML,
            articleText: best.text,
            articleChars: best.length,
            pageTitle: document.title,
            finalUrl: location.href,
            selectedSelector: best.selector,
            selectedTag: best.node.tagName,
            selectedId: best.node.id || '',
            selectedClass: best.node.className || '',
            headline,
            candidateSummary: candidates.slice(0, 20).map(x => ({selector:x.selector, priority:x.priority, length:x.length, id:x.node.id || '', className:String(x.node.className || '').slice(0,120)})),
          };
        }
        """,
        {"minimumChars": report["minimum_chars"]},
    )


def archive_report(browser, report: dict) -> dict:
    errors: list[str] = []
    for attempt in range(1, 4):
        context = browser.new_context(
            locale="zh-CN",
            timezone_id="Asia/Hong_Kong",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
            viewport={"width": 1440, "height": 1200},
        )
        page = context.new_page()
        try:
            response = page.goto(report["url"], wait_until="domcontentloaded", timeout=90_000)
            status = response.status if response else None
            try:
                page.wait_for_load_state("networkidle", timeout=18_000)
            except Exception:
                pass
            extracted = extract_article(page, report)
            print("EXTRACTED", json.dumps({
                "index": report["index"], "attempt": attempt, "status": status,
                "page_title": extracted["pageTitle"], "headline": extracted["headline"],
                "article_chars": extracted["articleChars"], "selector": extracted["selectedSelector"],
                "selected_id": extracted["selectedId"], "selected_class": str(extracted["selectedClass"])[:200],
                "candidates": extracted["candidateSummary"],
            }, ensure_ascii=False), flush=True)
            if status is not None and status >= 400:
                raise RuntimeError(f"HTTP status {status}")
            if extracted["articleChars"] < report["minimum_chars"]:
                raise RuntimeError(f"article text too short: {extracted['articleChars']}")

            clean_html = f"""<!doctype html>
<html lang='zh-CN'><head><meta charset='utf-8'><base href='{html.escape(extracted['finalUrl'], quote=True)}'>
<style>
@page {{ size:A4; margin:15mm 14mm 18mm; }}
html,body {{ margin:0; padding:0; background:#fff; color:#111; }}
body {{ font-family:'Noto Sans CJK SC','Noto Sans CJK TC','Microsoft YaHei',sans-serif; font-size:10.3pt; line-height:1.72; }}
.archive-meta {{ border:1px solid #aaa; background:#f7f7f7; padding:12px 14px; margin-bottom:18px; page-break-inside:avoid; }}
.archive-meta h1 {{ font-size:17pt; line-height:1.42; margin:0 0 10px; }}
.archive-meta p {{ margin:4px 0; font-size:9pt; line-height:1.55; word-break:break-all; }}
.archive-meta .note {{ color:#555; margin-top:9px; }}
.article-archive h1 {{ font-size:16pt; line-height:1.42; }}
.article-archive h2 {{ font-size:14pt; line-height:1.45; margin:17px 0 8px; }}
.article-archive h3 {{ font-size:12.5pt; line-height:1.45; margin:14px 0 7px; }}
.article-archive p {{ margin:8px 0; text-align:justify; }}
.article-archive img {{ display:block; max-width:100% !important; height:auto !important; margin:10px auto; page-break-inside:avoid; }}
.article-archive table {{ width:100%; border-collapse:collapse; margin:10px 0; font-size:8.8pt; page-break-inside:avoid; }}
.article-archive td,.article-archive th {{ border:1px solid #999; padding:5px; vertical-align:top; }}
.article-archive a {{ color:inherit; text-decoration:none; }}
.article-archive ul,.article-archive ol {{ padding-left:1.7em; }}
</style></head><body>
<section class='archive-meta'>
<h1>{html.escape(report['title'])}</h1>
<p><strong>发布机构：</strong>{html.escape(report['institution'])}</p>
<p><strong>发布日期：</strong>{report['date']}</p>
<p><strong>资料形式：</strong>{html.escape(report['form'])}</p>
<p><strong>内容范围：</strong>{html.escape(report['scope'])}</p>
<p><strong>公开来源：</strong>{html.escape(extracted['finalUrl'])}</p>
<p class='note'>本文件为公开网页的PDF归档版本。原始内容版权归研究机构、作者及发布平台所有；本资料不构成投资建议。</p>
</section><main class='article-archive'>{extracted['html']}</main></body></html>"""
            page.set_content(clean_html, wait_until="domcontentloaded", timeout=90_000)
            try:
                page.wait_for_load_state("networkidle", timeout=20_000)
            except Exception:
                pass
            page.wait_for_timeout(2500)
            destination = REPORT_DIR / report["filename"]
            page.pdf(
                path=str(destination), format="A4", print_background=True, prefer_css_page_size=True,
                display_header_footer=True, header_template="<div></div>",
                footer_template="<div style='font-size:8px;width:100%;padding:0 14mm;font-family:Arial;color:#777;text-align:right'><span class='pageNumber'></span> / <span class='totalPages'></span></div>",
                margin={"top":"15mm","right":"14mm","bottom":"18mm","left":"14mm"},
            )
            context.close()
            return {
                "requested_url": report["url"], "source_url": extracted["finalUrl"],
                "http_status": status, "page_title": extracted["pageTitle"],
                "article_chars": extracted["articleChars"], "selected_selector": extracted["selectedSelector"],
                "output_path": str(destination),
            }
        except Exception as exc:
            errors.append(f"attempt {attempt}: {exc!r}")
            print("CAPTURE_ERROR", report["index"], attempt, repr(exc), flush=True)
            context.close()
            time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to archive report {report['index']}: " + " | ".join(errors))


def validate_pdf(path: Path, report: dict) -> dict:
    if not path.exists() or path.stat().st_size < 20_000:
        raise RuntimeError(f"PDF missing or too small: {path}")
    if path.read_bytes()[:5] != b"%PDF-":
        raise RuntimeError(f"PDF header missing: {path}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < report["minimum_pages"]:
        raise RuntimeError(f"Unexpected page count {pages}: {path}")
    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf validation failed: {qpdf.stderr[-1000:]}")
    parts: list[str] = []
    for page in reader.pages[: min(8, pages)]:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            pass
    sample = compact("\n".join(parts))
    if compact("中国船舶租赁") not in sample and compact("船舶租赁") not in sample:
        raise RuntimeError(f"Company marker missing in PDF text: {path}")
    institution_marker = compact(report["institution"].replace("证券", ""))
    if institution_marker not in sample:
        print("TEXT_WARNING institution marker not extractable", report["institution"], path, flush=True)

    rendered: list[str] = []
    for label, number in (("first", 1), ("last", pages)):
        prefix = PREVIEW_DIR / f"{report['index']:02d}_{label}"
        result = subprocess.run(
            ["pdftoppm", "-f", str(number), "-l", str(number), "-singlefile", "-png", "-r", "110", str(path), str(prefix)],
            capture_output=True, text=True, timeout=180,
        )
        png = Path(str(prefix) + ".png")
        if result.returncode != 0 or not png.exists() or png.stat().st_size < 2000:
            raise RuntimeError(f"PDF render failed: {path}: {result.stderr[-800:]}")
        rendered.append(str(png))
    return {"pages":pages, "bytes":path.stat().st_size, "sha256":sha256(path), "qpdf_return_code":qpdf.returncode, "rendered_previews":rendered}


manifest: list[dict] = []
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    for report in REPORTS:
        capture = archive_report(browser, report)
        path = Path(capture["output_path"])
        validation = validate_pdf(path, report)
        record = {
            "filename": path.name,
            "company": "中国船舶集团（香港）航运租赁有限公司",
            "stock_code": "03877.HK",
            "institution": report["institution"], "title": report["title"],
            "publication_date": report["date"], "document_form": report["form"],
            "scope": report["scope"], **capture, **validation,
        }
        manifest.append(record)
        print("VERIFIED", json.dumps(record, ensure_ascii=False), flush=True)
    browser.close()

if len(manifest) != 3 or len({x["sha256"] for x in manifest}) != 3:
    raise RuntimeError("Report count or duplicate validation failed")

lines = [
    "中国船舶租赁（03877.HK）券商研究资料包", "",
    "本资料包收录3份与中国船舶租赁直接相关的券商研究材料：",
    "1. 浙商证券，2025-01-06，首次覆盖公司深度研究公开全文转载页面存档。",
    "2. 国泰君安证券，2024-03-06，首次覆盖研究公开摘要页面存档。",
    "3. 国金证券，2026-02-09，首次覆盖研究公开摘要页面存档。", "",
    "重要说明：公开渠道未提供上述三份报告均可免登录下载的券商原始版式PDF。为避免将摘要冒充原始报告，第1份明确标为公开全文转载页面存档，第2、3份明确标为公开券商研究摘要页面存档。", "",
]
for item in manifest:
    lines += [
        f"- {item['filename']}", f"  发布机构：{item['institution']}",
        f"  标题：{item['title']}",
        f"  日期：{item['publication_date']}｜形式：{item['document_form']}",
        f"  页数：{item['pages']}｜大小：{item['bytes']} bytes",
        f"  公开来源：{item['source_url']}", f"  SHA-256：{item['sha256']}",
    ]
lines += [
    "", "核验项目：HTTP状态、正文长度与范围、公司标识、PDF文件头、页数、qpdf结构检查、首页与末页渲染、文件去重、SHA-256及ZIP CRC。",
    f"制作时间：{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
    "本资料仅用于研究资料归档，不构成投资建议。原始内容版权归研究机构、作者及发布平台所有。",
]
(NOTE_DIR / "资料范围与来源说明.txt").write_text("\n".join(lines), encoding="utf-8")
(NOTE_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
(NOTE_DIR / "SHA256SUMS.txt").write_text("".join(f"{x['sha256']}  {x['filename']}\n" for x in manifest), encoding="utf-8")

archive = Path(PACKAGE + ".zip")
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as bundle:
    for file in sorted(ROOT.rglob("*")):
        if file.is_file():
            bundle.write(file, arcname=f"{ROOT.name}/{file.relative_to(ROOT)}")
with zipfile.ZipFile(archive) as bundle:
    bad = bundle.testzip()
    if bad:
        raise RuntimeError(f"ZIP CRC failure: {bad}")
    if len([x for x in bundle.namelist() if x.lower().endswith('.pdf')]) != 3:
        raise RuntimeError("ZIP report count validation failed")
    print("ZIP_MEMBERS", json.dumps(bundle.namelist(), ensure_ascii=False, indent=2), flush=True)
print("FINAL_ZIP", archive.name, archive.stat().st_size, sha256(archive), flush=True)
