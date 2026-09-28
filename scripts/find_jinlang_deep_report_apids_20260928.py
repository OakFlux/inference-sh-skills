from __future__ import annotations

import json
import re
import requests

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

ranges = [
    ("2020-07-14", "2020-07-21"),
    ("2020-09-18", "2020-09-27"),
    ("2023-02-27", "2023-03-05"),
]

for begin, end in ranges:
    url = (
        "https://reportapi.eastmoney.com/report/list"
        f"?cb=datatable&pageSize=100&pageNo=1&fields=&qType=0&orgCode=&author="
        f"&beginTime={begin}&endTime={end}&code=300763"
        "&industryCode=*&industry=*&rating=*&ratingChange=*"
    )
    response = session.get(url, headers=headers, timeout=90)
    print("HTTP", begin, end, response.status_code, response.headers.get("content-type"), len(response.content), flush=True)
    response.raise_for_status()
    match = re.search(r"datatable\((.*)\)\s*$", response.text, flags=re.S)
    if not match:
        raise RuntimeError(f"unexpected response for {begin}~{end}: {response.text[:500]}")
    payload = json.loads(match.group(1))
    print("RANGE", begin, end, "hits", payload.get("hits"), flush=True)
    for row in payload.get("data") or []:
        item = {
            "title": row.get("title"),
            "stockName": row.get("stockName"),
            "orgSName": row.get("orgSName"),
            "publishDate": row.get("publishDate"),
            "infoCode": row.get("infoCode"),
            "attachPages": row.get("attachPages"),
            "attachSize": row.get("attachSize"),
            "researcher": row.get("researcher"),
            "indvIsNew": row.get("indvIsNew"),
            "reportType": row.get("reportType"),
            "rating": row.get("emRatingName"),
        }
        print("REPORT", json.dumps(item, ensure_ascii=False), flush=True)
