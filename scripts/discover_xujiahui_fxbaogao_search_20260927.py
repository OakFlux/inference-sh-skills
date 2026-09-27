from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

OUT = Path("xujiahui_fxbaogao_search")
OUT.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    context = browser.new_context(user_agent=UA, locale="zh-CN", viewport={"width":1600,"height":1200})
    page = context.new_page()
    events=[]
    def on_response(resp):
        u=resp.url; ct=resp.headers.get("content-type","")
        if any(x in (u+" "+ct).lower() for x in ("api","json","search","report","detail")):
            events.append({"url":u,"status":resp.status,"content_type":ct})
    page.on("response",on_response)
    page.goto("https://www.fxbaogao.com/", wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(8000)
    inputs=page.locator("input").all()
    print("INPUT_COUNT",len(inputs),flush=True)
    for i,el in enumerate(inputs):
        try:
            print("INPUT",i,el.get_attribute("placeholder"),el.get_attribute("type"),flush=True)
        except Exception: pass
    target=page.locator('input[placeholder*="搜索关键词"]').first
    if target.count()==0:
        target=page.locator("input").first
    target.fill("徐家汇 002561")
    page.wait_for_timeout(1000)
    # Prefer visible search button; otherwise press Enter.
    clicked=False
    for text in ["发现一下","搜索"]:
        loc=page.get_by_text(text,exact=True)
        if loc.count():
            try:
                loc.first.click(timeout=10000); clicked=True; break
            except Exception as exc:
                print("CLICK_FAIL",text,repr(exc),flush=True)
    if not clicked:
        target.press("Enter")
    page.wait_for_timeout(12000)
    for _ in range(10):
        page.mouse.wheel(0,5000); page.wait_for_timeout(800)
    print("FINAL_URL",page.url,flush=True)
    html=page.content()
    (OUT/"result.html").write_text(html,encoding="utf-8")
    (OUT/"network.json").write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding="utf-8")
    page.screenshot(path=str(OUT/"result.png"),full_page=True)
    anchors=page.locator("a").all()
    links=[]
    for a in anchors:
        try:
            href=a.get_attribute("href") or ""
            text=" ".join((a.inner_text() or "").split())
            if href:
                href=urljoin(page.url,href)
            if href and ("/detail/" in href or "徐家汇" in text or "002561" in text):
                links.append({"text":text,"href":href})
        except Exception: pass
    unique=[]; seen=set()
    for item in links:
        key=(item["text"],item["href"])
        if key not in seen:
            seen.add(key); unique.append(item)
    print("LINKS",json.dumps(unique,ensure_ascii=False),flush=True)
    body=page.locator("body").inner_text()
    print("BODY_HEAD",body[:8000],flush=True)
    (OUT/"links.json").write_text(json.dumps(unique,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"body.txt").write_text(body,encoding="utf-8")
    browser.close()
