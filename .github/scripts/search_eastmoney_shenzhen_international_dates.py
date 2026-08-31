from __future__ import annotations

import json
import time
from datetime import date, timedelta

import requests

API = "https://reportapi.eastmoney.com/report/list"
TARGETS = [
    (date(2025, 4, 17), ["华南物流园增值添利", "深圳国际"]),
    (date(2024, 8, 10), ["土地转性贡献弹性", "深圳国际"]),
    (date(2023, 12, 20), ["物流园资产释放盈利弹性", "深圳国际"]),
    (date(2025, 6, 24), ["国企优质资源禀赋", "深圳国际"]),
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Referer": "https://data.eastmoney.com/report/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})


def value(row: dict, *names: str) -> str:
    for name in names:
        if row.get(name) is not None:
            return str(row.get(name))
    return ""


all_matches: dict[str, dict] = {}
for center, keywords in TARGETS:
    begin = center - timedelta(days=1)
    end = center + timedelta(days=2)
    print("\n=== WINDOW", begin, end, "KEYWORDS", keywords, "===")
    for page in range(1, 13):
        params = {
            "industryCode": "*", "pageSize": "100", "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": begin.isoformat(), "endTime": end.isoformat(),
            "pageNo": str(page), "fields": "", "qType": "0",
            "orgCode": "", "code": "", "rcode": "",
            "p": str(page), "pageNum": str(page), "pageNumber": str(page),
            "_": str(int(time.time() * 1000)),
        }
        response = session.get(API, params=params, timeout=(20, 120))
        print("PAGE", page, "STATUS", response.status_code)
        response.raise_for_status()
        rows = response.json().get("data") or []
        print("ROWS", len(rows))
        if not rows:
            break
        for row in rows:
            title = value(row, "title", "Title")
            stock_name = value(row, "stockName", "StockName", "secuName")
            org = value(row, "orgSName", "orgName")
            researcher = value(row, "researcher")
            hay = " ".join([title, stock_name, org, researcher])
            if any(keyword in hay for keyword in keywords):
                info_code = value(row, "infoCode", "InfoCode", "encodeUrl")
                key = info_code or json.dumps(row, ensure_ascii=False, sort_keys=True)
                all_matches[key] = row
                print("MATCH", json.dumps(row, ensure_ascii=False))
        if len(rows) < 100:
            break
        time.sleep(0.15)

print("\n=== ALL MATCHES", len(all_matches), "===")
for key, row in all_matches.items():
    keep = {name: row.get(name) for name in (
        "infoCode", "title", "publishDate", "orgSName", "researcher",
        "stockName", "stockCode", "encodeUrl", "attachPages",
    ) if name in row}
    print(key, json.dumps(keep, ensure_ascii=False))
