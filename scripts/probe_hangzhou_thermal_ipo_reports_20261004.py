from __future__ import annotations

import json
import time
import requests

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Referer": "https://data.eastmoney.com/report/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})

BASE = "https://reportapi.eastmoney.com/report/list"


def call(label: str, params: dict):
    r = session.get(BASE, params=params, timeout=(20, 90), allow_redirects=True)
    print("CALL", label, r.status_code, r.headers.get("content-type"), len(r.content), r.url, flush=True)
    try:
        data = r.json()
    except Exception:
        print(r.text[:1000], flush=True)
        return []
    rows = data.get("data") or data.get("result") or []
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("list") or []
    print("ROWS", label, len(rows), "META", json.dumps({k:v for k,v in data.items() if k not in ('data','result')}, ensure_ascii=False)[:1000], flush=True)
    for row in rows:
        text = json.dumps(row, ensure_ascii=False)
        if "杭州热电" in text or "605011" in text or "707011" in text:
            print("MATCH", label, text, flush=True)
    return rows

common = {
    "industryCode": "*",
    "pageSize": 100,
    "industry": "*",
    "rating": "*",
    "ratingChange": "*",
    "beginTime": "2020-01-01",
    "endTime": "2026-10-04",
    "pageNo": 1,
    "fields": "",
    "qType": 0,
    "orgCode": "",
    "rcode": "",
    "p": 1,
    "pageNum": 1,
    "pageNumber": 1,
}

for code in ["605011", "707011", "杭州热电", "hzrd"]:
    for qtype in [0, 1, 2]:
        params = dict(common)
        params["code"] = code
        params["qType"] = qtype
        call(f"code={code};qType={qtype}", params)

# Search all research published near the IPO, page by page, to catch records not tagged to the final code.
for start, end in [
    ("2021-06-01", "2021-06-30"),
    ("2021-05-01", "2021-07-31"),
    ("2023-05-01", "2023-06-30"),
]:
    for page in range(1, 61):
        params = dict(common)
        params.update({
            "code": "",
            "beginTime": start,
            "endTime": end,
            "pageNo": page,
            "p": page,
            "pageNum": page,
            "pageNumber": page,
        })
        rows = call(f"global {start}~{end} page={page}", params)
        if not rows:
            break
        if len(rows) < 100:
            break
        time.sleep(0.1)
