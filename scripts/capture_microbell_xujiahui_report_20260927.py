from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

OUT = Path("microbell_xujiahui_capture")
OUT.mkdir(exist_ok=True)
URL = "https://wp.microbell.com/docdetail_1654924.html"
MARKERS = ("microbell", "1654924", "pdf", "download", "doc", "file", "attach")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    context = browser.new_context(
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
        locale="zh-CN",
        viewport={"width": 1600, "height": 1200},
    )
    page = context.new_page()
    requests = []
    responses = []

    def on_request(req):
        low = req.url.lower()
        if any(m in low for m in MARKERS):
            item = {"method": req.method, "url": req.url, "post_data": req.post_data, "resource_type": req.resource_type}
            requests.append(item)
            print("REQUEST", json.dumps(item, ensure_ascii=False), flush=True)

    def on_response(resp):
        low = (resp.url + " " + resp.headers.get("content-type", "")).lower()
        if any(m in low for m in MARKERS):
            body = ""
            if "json" in resp.headers.get("content-type", "") or "text" in resp.headers.get("content-type", "") or "html" in resp.headers.get("content-type", ""):
                try:
                    body = resp.text()[:50000]
                except Exception:
                    body = ""
            item = {"status": resp.status, "url": resp.url, "content_type": resp.headers.get("content-type", ""), "body": body}
            responses.append(item)
            print("RESPONSE", json.dumps({k: v for k, v in item.items() if k != "body"}, ensure_ascii=False), flush=True)
            if body:
                print("BODY", body[:10000], flush=True)

    page.on("request", on_request)
    page.on("response", on_response)
    try:
        page.goto(URL, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(15000)
        body_text = page.locator("body").inner_text(timeout=30000)
        html = page.content()
        links = []
        for a in page.locator("a").all():
            try:
                href = a.get_attribute("href") or ""
                text = " ".join((a.inner_text() or "").split())
                if href:
                    links.append({"text": text, "href": urljoin(page.url, href)})
            except Exception:
                pass
        print("FINAL_URL", page.url, flush=True)
        print("BODY_TEXT", body_text[:20000], flush=True)
        print("LINKS", json.dumps(links, ensure_ascii=False), flush=True)
        (OUT / "page.html").write_text(html, encoding="utf-8")
        (OUT / "body.txt").write_text(body_text, encoding="utf-8")
        (OUT / "links.json").write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")
        page.screenshot(path=str(OUT / "page.png"), full_page=True)
    except Exception as exc:
        print("PAGE_ERROR", repr(exc), flush=True)
    (OUT / "requests.json").write_text(json.dumps(requests, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "responses.json").write_text(json.dumps(responses, ensure_ascii=False, indent=2), encoding="utf-8")
    browser.close()
