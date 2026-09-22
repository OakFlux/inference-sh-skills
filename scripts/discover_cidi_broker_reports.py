from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

OUT = Path("cidi_broker_discovery")
OUT.mkdir(exist_ok=True)

pages = {
    "guosen_detail": "https://www.fxbaogao.com/detail/5228577",
    "guosen_view": "https://www.fxbaogao.com/view?id=5228577",
    "guosheng_detail": "https://www.fxbaogao.com/detail/5466816",
    "guosheng_view": "https://www.fxbaogao.com/view?id=5466816",
    "zhongyou_detail": "https://www.fxbaogao.com/detail/5435964",
    "zhongyou_view": "https://www.fxbaogao.com/view?id=5435964",
    "dongwu_detail": "https://www.fxbaogao.com/detail/5238998",
    "dongwu_view": "https://www.fxbaogao.com/view?id=5238998",
}

headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

session = requests.Session()
session.trust_env = False
records = {}

for name, url in pages.items():
    try:
        r = session.get(url, headers=headers, timeout=(15, 90), allow_redirects=True)
        body = r.content
        ctype = r.headers.get("content-type", "")
        rec = {
            "requested_url": url,
            "final_url": r.url,
            "status": r.status_code,
            "content_type": ctype,
            "bytes": len(body),
            "headers": dict(r.headers),
        }
        ext = ".html" if "html" in ctype or body[:20].lower().startswith((b"<!doctype", b"<html")) else ".bin"
        path = OUT / f"{name}{ext}"
        path.write_bytes(body)
        rec["saved_as"] = str(path)
        text = body.decode(r.encoding or "utf-8", errors="replace")
        soup = BeautifulSoup(text, "html.parser")
        urls = []
        for tag in soup.find_all(True):
            for attr in ("href", "src", "data-src", "data-url", "data-original", "content"):
                val = tag.get(attr)
                if isinstance(val, str) and val.strip():
                    candidate = urljoin(r.url, val.strip())
                    if any(x in candidate.lower() for x in ("pdf", "image", "img", "view", "download", "file", "report", "api")):
                        urls.append(candidate)
        for match in re.findall(r'https?://[^\s"\'<>]+', text):
            if any(x in match.lower() for x in ("pdf", "image", "img", "download", "file", "report", "api")):
                urls.append(match)
        rec["interesting_urls"] = list(dict.fromkeys(urls))[:1000]
        rec["scripts"] = [urljoin(r.url, x.get("src")) for x in soup.find_all("script", src=True)]
        records[name] = rec
        print(name, r.status_code, len(body), r.url, flush=True)
    except Exception as exc:
        records[name] = {"requested_url": url, "error": repr(exc)}
        print(name, "ERROR", repr(exc), flush=True)

(OUT / "requests_discovery.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

# Browser pass: capture network URLs and fully rendered DOM.
try:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            user_agent=headers["User-Agent"],
            locale="zh-CN",
            viewport={"width": 1600, "height": 1200},
        )
        for name, url in pages.items():
            page = context.new_page()
            events = []
            def on_response(resp):
                u = resp.url
                ct = resp.headers.get("content-type", "")
                if any(x in (u + " " + ct).lower() for x in ("pdf", "image", "img", "download", "file", "report", "api", "json")):
                    events.append({"url": u, "status": resp.status, "content_type": ct})
            page.on("response", on_response)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(12000)
                page.mouse.wheel(0, 20000)
                page.wait_for_timeout(5000)
                (OUT / f"{name}_rendered.html").write_text(page.content(), encoding="utf-8")
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
                (OUT / f"{name}_network.json").write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
                print("BROWSER", name, page.url, len(events), flush=True)
            except Exception as exc:
                (OUT / f"{name}_browser_error.txt").write_text(repr(exc), encoding="utf-8")
                print("BROWSER ERROR", name, repr(exc), flush=True)
            finally:
                page.close()
        browser.close()
except Exception as exc:
    (OUT / "playwright_error.txt").write_text(repr(exc), encoding="utf-8")
    print("PLAYWRIGHT ERROR", repr(exc), flush=True)
