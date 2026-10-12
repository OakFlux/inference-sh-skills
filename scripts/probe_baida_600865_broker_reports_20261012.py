from __future__ import annotations

import json
import requests

CODE = "600865"
END_DATE = "2026-10-12"
URL = "https://reportapi.eastmoney.com/report/list2"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Content-Type": "application/json",
    "Referer": "https://data.eastmoney.com/report/stock.jshtml",
})

body = {
    "pageSize": 200,
    "pageNo": 1,
    "p": 1,
    "pageNum": 1,
    "pageNumber": 1,
    "beginTime": "2000-01-01",
    "endTime": END_DATE,
    "code": CODE,
    "industryCode": "*",
    "rating": None,
    "ratingChange": None,
    "orgCode": None,
    "rcode": "",
}

response = session.post(URL, json=body, timeout=(20, 180))
print("HTTP", response.status_code, response.headers.get("content-type"), len(response.content), flush=True)
response.raise_for_status()
data = response.json()
print("HITS", data.get("hits"), "SIZE", data.get("size"), flush=True)
rows = data.get("data") or []
for index, row in enumerate(rows, 1):
    compact = {
        "index": index,
        "title": row.get("title"),
        "orgSName": row.get("orgSName"),
        "publishDate": row.get("publishDate"),
        "infoCode": row.get("infoCode"),
        "attachPages": row.get("attachPages"),
        "attachSize": row.get("attachSize"),
        "researcher": row.get("researcher"),
        "rating": row.get("emRatingName") or row.get("sRatingName"),
        "column": row.get("column"),
        "reportType": row.get("reportType"),
        "encodeUrl": row.get("encodeUrl"),
    }
    print("REPORT", json.dumps(compact, ensure_ascii=False), flush=True)
