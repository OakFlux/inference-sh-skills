from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("xujiahui_fxbaogao_pages")
OUT.mkdir(exist_ok=True)
URL = "https://www.fxbaogao.com/rp?keywords=%E5%BE%90%E5%AE%B6%E6%B1%87%20002561&order=2&nop=-1"


def clean(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")

all_rows: list[dict] = []
seen: set[int] = set()
request_bodies: list[dict] = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    context = browser.new_context(
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
        locale="zh-CN",
        viewport={"width": 1600, "height": 1200},
    )
    page = context.new_page()

    def capture_request(req):
        if "searchReport/searchNoAuth" in req.url:
            try:
                body = req.post_data_json
            except Exception:
                body = req.post_data
            request_bodies.append({"url": req.url, "body": body})
            print("SEARCH_REQUEST", json.dumps(body, ensure_ascii=False), flush=True)

    def add_response(resp, page_label: str):
        try:
            obj = resp.json()
        except Exception as exc:
            print("PARSE_FAIL", page_label, repr(exc), flush=True)
            return
        data = obj.get("data") or {}
        rows = data.get("dataList") or []
        new_count = 0
        for row in rows:
            doc_id = int(row.get("docId") or 0)
            if doc_id and doc_id not in seen:
                seen.add(doc_id)
                all_rows.append(row)
                new_count += 1
        print(
            "PAGE_RESPONSE", page_label,
            "curr", data.get("currPage"), "rows", len(rows), "new", new_count,
            "unique", len(all_rows), "total", data.get("count"), "pages", data.get("pageCount"),
            flush=True,
        )

    page.on("request", capture_request)
    with page.expect_response(lambda r: "searchReport/searchNoAuth" in r.url, timeout=120000) as initial_info:
        page.goto(URL, wait_until="domcontentloaded", timeout=120000)
    initial = initial_info.value
    add_response(initial, "1")
    page.wait_for_timeout(3000)

    for page_number in range(2, 26):
        next_button = page.locator("li.ant-pagination-next button")
        if next_button.count() == 0:
            print("NO_NEXT_BUTTON", page_number, flush=True)
            break
        disabled = page.locator("li.ant-pagination-next").get_attribute("aria-disabled")
        if disabled == "true":
            print("NEXT_DISABLED", page_number, flush=True)
            break
        try:
            with page.expect_response(lambda r: "searchReport/searchNoAuth" in r.url, timeout=60000) as info:
                next_button.click(timeout=30000)
            add_response(info.value, str(page_number))
            page.wait_for_timeout(700)
        except Exception as exc:
            print("NEXT_ERROR", page_number, repr(exc), flush=True)
            break

    browser.close()

company_rows: list[dict] = []
for row in all_rows:
    title = clean(str(row.get("title") or ""))
    stocks = row.get("stocks") or []
    if any(str(s.get("key")) == "002561" for s in stocks if isinstance(s, dict)) or "徐家汇" in title:
        row = dict(row)
        row["cleanTitle"] = title
        company_rows.append(row)

for row in company_rows:
    title = row.get("cleanTitle")
    org = str(row.get("orgName") or "")
    if org not in {"财报", "发现报告", "公司公告", "公告"} or any(
        term in title for term in ("优质商圈", "主业经营稳健", "全渠道", "深度研究", "首次覆盖")
    ):
        print("CANDIDATE", json.dumps({
            "docId": row.get("docId"), "title": title, "pdfPath": row.get("pdfPath"),
            "fileUrl": row.get("fileUrl"), "pageNum": row.get("pageNum"),
            "pubTimeStr": row.get("pubTimeStr"), "pubTime": row.get("pubTime"),
            "orgName": row.get("orgName"), "authors": row.get("authors"),
            "reportType": row.get("reportType"), "isDeep": row.get("isDeep"),
            "docType": row.get("docType"), "isNotBroker": row.get("isNotBroker"),
        }, ensure_ascii=False), flush=True)

(OUT / "all_rows.json").write_text(json.dumps(all_rows, ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / "company_rows.json").write_text(json.dumps(company_rows, ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / "request_bodies.json").write_text(json.dumps(request_bodies, ensure_ascii=False, indent=2), encoding="utf-8")
print("FINAL", "all", len(all_rows), "company", len(company_rows), flush=True)
