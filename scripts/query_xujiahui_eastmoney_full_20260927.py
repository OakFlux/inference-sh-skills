from __future__ import annotations

import json
from pathlib import Path

import requests

URL = "https://reportapi.eastmoney.com/report/list"
PARAMS = {
    "industryCode": "*",
    "pageSize": "5000",
    "industry": "*",
    "rating": "*",
    "ratingChange": "*",
    "beginTime": "2000-01-01",
    "endTime": "2027-01-01",
    "pageNo": "1",
    "fields": "",
    "qType": "0",
    "orgCode": "",
    "code": "002561",
    "rcode": "",
    "p": "1",
    "pageNum": "1",
    "pageNumber": "1",
}
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Referer": "https://data.eastmoney.com/report/002561.html",
}
response = requests.get(URL, params=PARAMS, headers=headers, timeout=120)
print("STATUS", response.status_code, response.url, response.headers.get("content-type"), len(response.content), flush=True)
response.raise_for_status()
payload = response.json()
Path("xujiahui_eastmoney_full.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print("META", json.dumps({k: payload.get(k) for k in ("hits", "size", "TotalPage", "pageNo", "currentYear")}, ensure_ascii=False), flush=True)
for idx, item in enumerate(payload.get("data") or [], 1):
    info = item.get("infoCode")
    pdf = f"https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf" if info else None
    record = {
        "index": idx,
        "title": item.get("title"),
        "publishDate": item.get("publishDate"),
        "orgSName": item.get("orgSName"),
        "researcher": item.get("researcher"),
        "author": item.get("author"),
        "infoCode": info,
        "attachPages": item.get("attachPages"),
        "attachSize": item.get("attachSize"),
        "pdfUrl": pdf,
    }
    print("REPORT", json.dumps(record, ensure_ascii=False), flush=True)
