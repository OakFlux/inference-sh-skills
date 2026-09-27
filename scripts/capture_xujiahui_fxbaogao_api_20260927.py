from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

OUT = Path("xujiahui_fxbaogao_api_capture")
OUT.mkdir(exist_ok=True)
TARGETS = [
    "徐家汇",
    "优质商圈 高盈利能力 高分红",
    "主业经营稳健 持续深化全渠道布局",
    "经营稳健 加速推进全渠道融合",
]
API_MARKERS = (
    "api.fxbaogao.com/business/report/",
    "api.fxbaogao.com/business/reportStock/",
)

all_records: list[dict] = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    context = browser.new_context(
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
        locale="zh-CN",
        viewport={"width": 1600, "height": 1200},
    )

    for index, keyword in enumerate(TARGETS, 1):
        page = context.new_page()
        records: list[dict] = []

        def on_request(req):
            if any(marker in req.url for marker in API_MARKERS):
                item = {
                    "kind": "request",
                    "keyword": keyword,
                    "method": req.method,
                    "url": req.url,
                    "post_data": req.post_data,
                    "headers": {k: v for k, v in req.headers.items() if k.lower() in {"content-type", "origin", "referer", "authorization"}},
                }
                records.append(item)
                print("REQUEST", json.dumps(item, ensure_ascii=False), flush=True)

        def on_response(resp):
            if any(marker in resp.url for marker in API_MARKERS):
                body = ""
                err = ""
                try:
                    body = resp.text()
                except Exception as exc:  # noqa: BLE001
                    err = repr(exc)
                item = {
                    "kind": "response",
                    "keyword": keyword,
                    "status": resp.status,
                    "url": resp.url,
                    "content_type": resp.headers.get("content-type", ""),
                    "body": body,
                    "error": err,
                }
                records.append(item)
                print("RESPONSE_META", json.dumps({k: item[k] for k in ("keyword", "status", "url", "content_type", "error")}, ensure_ascii=False), flush=True)
                print("RESPONSE_BODY", body[:30000], flush=True)

        page.on("request", on_request)
        page.on("response", on_response)
        url = f"https://www.fxbaogao.com/rp?keywords={quote(keyword)}&order=2&nop=-1"
        print("NAVIGATE", keyword, url, flush=True)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(12000)
            for _ in range(8):
                page.mouse.wheel(0, 5000)
                page.wait_for_timeout(700)
            body_text = page.locator("body").inner_text(timeout=30000)
            (OUT / f"{index:02d}_body.txt").write_text(body_text, encoding="utf-8")
            (OUT / f"{index:02d}_page.html").write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(OUT / f"{index:02d}_page.png"), full_page=True)
            print("BODY_SNIPPET", keyword, body_text[:12000], flush=True)
        except Exception as exc:  # noqa: BLE001
            print("NAVIGATE_ERROR", keyword, repr(exc), flush=True)
        (OUT / f"{index:02d}_network.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        all_records.extend(records)
        page.close()

    browser.close()

(OUT / "all_network.json").write_text(json.dumps(all_records, ensure_ascii=False, indent=2), encoding="utf-8")
print("TOTAL_RECORDS", len(all_records), flush=True)
