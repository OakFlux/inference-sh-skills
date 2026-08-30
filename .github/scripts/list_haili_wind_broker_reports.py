from __future__ import annotations

import json
import requests

STOCK_CODE = "301155"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Referer": "https://data.eastmoney.com/report/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})

params = {
    "industryCode": "*",
    "pageSize": "200",
    "industry": "*",
    "rating": "*",
    "ratingChange": "*",
    "companyType": "*",
    "beginTime": "2000-01-01",
    "endTime": "2030-01-01",
    "pageNo": "1",
    "fields": "",
    "qType": "0",
    "orgCode": "",
    "code": STOCK_CODE,
    "rcode": "",
    "p": "1",
    "pageNum": "1",
    "pageNumber": "1",
}

response = session.get(
    "https://reportapi.eastmoney.com/report/list",
    params=params,
    headers={"Accept": "application/json,text/javascript,*/*;q=0.9"},
    timeout=(30, 180),
)
response.raise_for_status()
payload = response.json()
records = payload.get("data", []) if isinstance(payload, dict) else []
print(f"REPORT_COUNT={len(records)}")
for item in records:
    print(
        f"{item.get('infoCode')} | {str(item.get('publishDate') or '')[:10]} | "
        f"{item.get('orgSName') or item.get('orgName')} | pages={item.get('attachPages')} | "
        f"{item.get('researcher')} | {item.get('title')}"
    )
