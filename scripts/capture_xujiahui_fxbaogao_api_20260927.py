from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

OUT = Path("xujiahui_fxbaogao_api_capture")
OUT.mkdir(exist_ok=True)
SEARCHES = [
    ("deep_exact", "徐家汇(002561)深度研究：优质商圈+高盈利能力+高分红", 1),
    ("deep_short", "徐家汇 优质商圈 高盈利能力 高分红", 1),
    ("research_2016", "徐家汇 主业经营稳健 持续深化全渠道布局", 1),
    ("research_2017", "徐家汇 经营稳健 加速推进全渠道融合", 1),
    ("company_code", "徐家汇 002561", -1),
]
API_MARKERS = (
    "api.fxbaogao.com/mofoun/report/",
    "api.fxbaogao.com/mofoun/order/paidReport/",
)

all_records: list[dict] = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    context = browser.new_context(
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
        locale="zh-CN",
        viewport={"width": 1600, "height": 1200},
    )

    for index, (label, keyword, nop) in enumerate(SEARCHES, 1):
        page = context.new_page()
        records: list[dict] = []

        def on_request(req, *, _label=label, _keyword=keyword):
            if any(marker in req.url for marker in API_MARKERS):
                item = {
                    "kind": "request",
                    "label": _label,
                    "keyword": _keyword,
                    "method": req.method,
                    "url": req.url,
                    "post_data": req.post_data,
                    "headers": {
                        key: value
                        for key, value in req.headers.items()
                        if key.lower() in {"content-type", "origin", "referer", "authorization"}
                    },
                }
                records.append(item)
                print("REQUEST", json.dumps(item, ensure_ascii=False), flush=True)

        def on_response(resp, *, _label=label, _keyword=keyword):
            if any(marker in resp.url for marker in API_MARKERS):
                body = ""
                error = ""
                try:
                    body = resp.text()
                except Exception as exc:  # noqa: BLE001
                    error = repr(exc)
                item = {
                    "kind": "response",
                    "label": _label,
                    "keyword": _keyword,
                    "status": resp.status,
                    "url": resp.url,
                    "content_type": resp.headers.get("content-type", ""),
                    "body": body,
                    "error": error,
                }
                records.append(item)
                print(
                    "RESPONSE_META",
                    json.dumps({key: item[key] for key in ("label", "status", "url", "content_type", "error")}, ensure_ascii=False),
                    flush=True,
                )
                print("RESPONSE_BODY", body[:100000], flush=True)

        page.on("request", on_request)
        page.on("response", on_response)
        url = f"https://www.fxbaogao.com/rp?keywords={quote(keyword)}&order=2&nop={nop}"
        print("NAVIGATE", label, keyword, url, flush=True)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(10000)
            for _ in range(4):
                page.mouse.wheel(0, 5000)
                page.wait_for_timeout(500)
            body_text = page.locator("body").inner_text(timeout=30000)
            (OUT / f"{index:02d}_{label}_body.txt").write_text(body_text, encoding="utf-8")
            (OUT / f"{index:02d}_{label}_page.html").write_text(page.content(), encoding="utf-8")
            print("BODY_SNIPPET", label, body_text[:8000], flush=True)
        except Exception as exc:  # noqa: BLE001
            print("NAVIGATE_ERROR", label, repr(exc), flush=True)
        (OUT / f"{index:02d}_{label}_network.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        all_records.extend(records)
        page.close()

    browser.close()

(OUT / "all_network.json").write_text(json.dumps(all_records, ensure_ascii=False, indent=2), encoding="utf-8")
print("TOTAL_RECORDS", len(all_records), flush=True)
