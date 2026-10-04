from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone

import requests

CODE = "605011"
ORG_ID = "9900039850"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://www.cninfo.com.cn",
    "Referer": f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={CODE}&orgId={ORG_ID}",
})

endpoint = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
all_rows = []
seen = set()
for start, end in [("2020-01-01", "2020-12-31"), ("2021-01-01", "2021-12-31"), ("2022-01-01", "2026-10-04")]:
    page = 1
    while True:
        payload = {
            "pageNum": str(page),
            "pageSize": "30",
            "column": "sse",
            "tabName": "fulltext",
            "plate": "sh",
            "stock": f"{CODE},{ORG_ID}",
            "searchkey": "",
            "secid": "",
            "category": "",
            "trade": "",
            "seDate": f"{start}~{end}",
            "sortName": "time",
            "sortType": "asc",
            "isHLtitle": "true",
        }
        r = session.post(endpoint, data=payload, timeout=(20, 90))
        print("QUERY", start, end, page, r.status_code, len(r.content), flush=True)
        r.raise_for_status()
        data = r.json()
        rows = data.get("announcements") or []
        total = int(data.get("totalAnnouncement") or 0)
        for row in rows:
            ident = str(row.get("announcementId") or row.get("adjunctUrl") or "")
            if ident and ident not in seen:
                seen.add(ident)
                all_rows.append(row)
        if not rows or page * 30 >= total:
            break
        page += 1
        if page > 40:
            break
        time.sleep(0.15)

print("TOTAL", len(all_rows), flush=True)
keywords = ("平安证券", "保荐", "承销", "核查意见", "持续督导", "投资价值", "估值", "发行人基本情况")
for row in sorted(all_rows, key=lambda r: int(r.get("announcementTime") or 0)):
    title = re.sub(r"<[^>]+>", "", str(row.get("announcementTitle") or ""))
    if any(keyword in title for keyword in keywords):
        timestamp = int(row.get("announcementTime") or 0)
        date = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if timestamp else ""
        print("BROKER_DOC", json.dumps({
            "date": date,
            "title": title,
            "url": row.get("adjunctUrl"),
            "size_kb": row.get("adjunctSize"),
            "announcement_id": row.get("announcementId"),
        }, ensure_ascii=False), flush=True)
