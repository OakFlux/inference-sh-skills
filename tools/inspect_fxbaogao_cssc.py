from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

URLS = [
    "https://www.fxbaogao.com/detail/5637601",
    "https://www.fhyanbao.com/rpview/1530167",
]
OUT = Path("_inspect_cssc")
OUT.mkdir(exist_ok=True)

for idx, target in enumerate(URLS, 1):
    records: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(
            locale="zh-CN",
            timezone_id="Asia/Hong_Kong",
            viewport={"width": 1440, "height": 1000},
            record_har_path=str(OUT / f"{idx:02d}.har"),
        )
        page = context.new_page()

        def on_response(response):
            try:
                ct = response.headers.get("content-type", "")
                url = response.url
                if any(k in url.lower() for k in ("pdf", "api", "detail", "report", "download", "file", "image", "img", "oss", "cos", "cdn")) or any(k in ct.lower() for k in ("pdf", "json", "image")):
                    records.append({
                        "url": url,
                        "status": response.status,
                        "content_type": ct,
                        "request_method": response.request.method,
                        "resource_type": response.request.resource_type,
                    })
            except Exception as exc:
                records.append({"response_error": repr(exc)})

        page.on("response", on_response)
        try:
            response = page.goto(target, wait_until="domcontentloaded", timeout=120_000)
            page.wait_for_timeout(12_000)
            try:
                page.wait_for_load_state("networkidle", timeout=30_000)
            except Exception:
                pass
            page.wait_for_timeout(3_000)
            html = page.content()
            (OUT / f"{idx:02d}.html").write_text(html, encoding="utf-8")
            page.screenshot(path=str(OUT / f"{idx:02d}.png"), full_page=True)
            details = page.evaluate(
                """
                () => ({
                  title: document.title,
                  url: location.href,
                  bodyText: document.body ? document.body.innerText : '',
                  links: [...document.querySelectorAll('a')].map(a => ({text:(a.innerText||'').trim(), href:a.href})),
                  images: [...document.images].map(i => ({alt:i.alt||'', src:i.currentSrc||i.src||'', dataSrc:i.getAttribute('data-src')||i.getAttribute('data-original')||''})),
                  scripts: [...document.scripts].map(s => s.src).filter(Boolean),
                  localStorage: Object.fromEntries(Object.entries(localStorage)),
                  sessionStorage: Object.fromEntries(Object.entries(sessionStorage)),
                })
                """
            )
            details["http_status"] = response.status if response else None
            details["responses"] = records
            (OUT / f"{idx:02d}.json").write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")
            print("INSPECTED", idx, target, details["http_status"], details["title"], len(details["bodyText"]), flush=True)
            for row in records:
                print("NETWORK", json.dumps(row, ensure_ascii=False), flush=True)
            for link in details["links"]:
                href = link.get("href", "")
                text = link.get("text", "")
                if any(k in (href + " " + text).lower() for k in ("pdf", "download", "下载", "阅读", "查看", "report")):
                    print("LINK", json.dumps(link, ensure_ascii=False), flush=True)
            for image in details["images"]:
                combined = " ".join(image.values()).lower()
                if any(k in combined for k in ("report", "pdf", "page", "detail", "img", "image")):
                    print("IMAGE", json.dumps(image, ensure_ascii=False), flush=True)
        finally:
            context.close()
            browser.close()
