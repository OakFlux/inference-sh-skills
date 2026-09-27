from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import requests

API = "https://api.fxbaogao.com/mofoun/report/searchReport/searchNoAuth"
PUBLIC = "https://public.fxbaogao.com/"
OUT = Path("xujiahui_fxbaogao_all.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.fxbaogao.com",
    "Referer": "https://www.fxbaogao.com/rp?keywords=%E5%BE%90%E5%AE%B6%E6%B1%87%20002561&order=2&nop=-1",
}
SESSION = requests.Session()
SESSION.trust_env = False


def post(payload: dict[str, Any]) -> dict[str, Any]:
    for attempt in range(1, 6):
        try:
            r = SESSION.post(API, json=payload, headers=HEADERS, timeout=(20, 120))
            print("POST", attempt, r.status_code, len(r.content), flush=True)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            print("POST_FAIL", attempt, repr(exc), flush=True)
            time.sleep(min(2 * attempt, 8))
    raise RuntimeError("API failed")


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")

all_rows: list[dict[str, Any]] = []
seen: set[int] = set()
page = 1
page_size = 100
while True:
    payload = {
        "order": "2",
        "pdfPage": "-1",
        "pageNum": page,
        "pageSize": page_size,
        "paragraphSize": 1,
        "keywords": "徐家汇 002561",
    }
    obj = post(payload)
    data = obj.get("data") or {}
    rows = data.get("dataList") or []
    print("PAGE", page, "rows", len(rows), "count", data.get("count"), "pageCount", data.get("pageCount"), flush=True)
    for row in rows:
        doc_id = int(row.get("docId") or 0)
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            all_rows.append(row)
    total_pages = int(data.get("pageCount") or 0)
    if not rows or page >= total_pages or page >= 30:
        break
    page += 1

# Keep genuine stock-specific rows and print broker/institution reports separately.
company_rows: list[dict[str, Any]] = []
for row in all_rows:
    title = strip_html(str(row.get("title") or ""))
    stocks = row.get("stocks") or []
    stock_match = any(str(s.get("key")) == "002561" for s in stocks if isinstance(s, dict))
    if stock_match or "徐家汇" in title:
        copy = dict(row)
        copy["cleanTitle"] = title
        company_rows.append(copy)

excluded_orgs = {"财报", "发现报告", "公司公告", "公告"}
broker_rows = [
    row for row in company_rows
    if str(row.get("orgName") or "").strip() not in excluded_orgs
    and not any(term in row["cleanTitle"] for term in ("年度报告", "半年度报告", "一季度报告", "季度报告", "机构调研纪要"))
]

print("TOTAL_UNIQUE", len(all_rows), "COMPANY_ROWS", len(company_rows), "BROKER_ROWS", len(broker_rows), flush=True)
for row in broker_rows:
    info = {
        "docId": row.get("docId"),
        "title": row.get("cleanTitle"),
        "pdfPath": row.get("pdfPath"),
        "pageNum": row.get("pageNum"),
        "pubTime": row.get("pubTime"),
        "pubTimeStr": row.get("pubTimeStr"),
        "orgName": row.get("orgName"),
        "authors": row.get("authors"),
        "reportType": row.get("reportType"),
        "isDeep": row.get("isDeep"),
        "fileUrl": row.get("fileUrl"),
        "docType": row.get("docType"),
        "publicUrl": PUBLIC + str(row.get("pdfPath") or "").lstrip("/"),
    }
    print("BROKER", json.dumps(info, ensure_ascii=False), flush=True)

# Probe direct public PDF URLs for every broker row.
probes: list[dict[str, Any]] = []
for row in broker_rows:
    url = PUBLIC + str(row.get("pdfPath") or "").lstrip("/")
    try:
        rr = SESSION.get(url, headers={"User-Agent": HEADERS["User-Agent"], "Referer": "https://www.fxbaogao.com/"}, timeout=(20, 120), stream=True)
        head = b""
        for chunk in rr.iter_content(1024):
            if chunk:
                head += chunk
                if len(head) >= 16:
                    break
        probe = {
            "docId": row.get("docId"), "url": url, "status": rr.status_code,
            "contentType": rr.headers.get("content-type"), "contentLength": rr.headers.get("content-length"),
            "headHex": head[:16].hex(), "isPdf": head.startswith(b"%PDF-"),
        }
        rr.close()
    except Exception as exc:  # noqa: BLE001
        probe = {"docId": row.get("docId"), "url": url, "error": repr(exc)}
    probes.append(probe)
    print("PROBE", json.dumps(probe, ensure_ascii=False), flush=True)

OUT.write_text(json.dumps({
    "all_count": len(all_rows),
    "company_rows": company_rows,
    "broker_rows": broker_rows,
    "probes": probes,
}, ensure_ascii=False, indent=2), encoding="utf-8")
