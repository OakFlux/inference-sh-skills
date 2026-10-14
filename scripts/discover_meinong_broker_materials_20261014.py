#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import requests
from datetime import datetime, timezone, timedelta

CODE = "301156"
ORG = "gfbj0873489"
URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
H = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://www.cninfo.com.cn",
    "Referer": f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={CODE}",
    "X-Requested-With": "XMLHttpRequest",
}
TZ = timezone(timedelta(hours=8))
S = requests.Session(); S.headers.update(H)

def date_of(v):
    if isinstance(v, (int,float)):
        return datetime.fromtimestamp(v/1000, TZ).strftime('%Y-%m-%d')
    return str(v)[:10]

for key in ["中泰证券", "保荐", "核查意见", "上市保荐书", "发行保荐书", "持续督导"]:
    print("=== SEARCH", key, "===")
    for page in range(1, 6):
        payload = {
            "pageNum": str(page), "pageSize": "50", "column": "szse", "tabName": "fulltext",
            "plate": "sz", "stock": f"{CODE},{ORG}", "searchkey": key,
            "secid": "", "category": "", "trade": "", "seDate": "2020-01-01~2026-10-14",
            "sortName": "", "sortType": "", "isHLtitle": "true",
        }
        r = S.post(URL, data=payload, timeout=60)
        print("PAGE", page, "STATUS", r.status_code, "BYTES", len(r.content))
        r.raise_for_status()
        data = r.json()
        anns = data.get("announcements") or []
        print("COUNT", len(anns), "TOTAL", data.get("totalAnnouncement"), "PAGES", data.get("totalpages"))
        for a in anns:
            print("ANN", json.dumps({
                "date": date_of(a.get("announcementTime")),
                "title": a.get("announcementTitle"),
                "announcementId": a.get("announcementId"),
                "adjunctUrl": a.get("adjunctUrl"),
                "sizeKB": a.get("adjunctSize"),
            }, ensure_ascii=False))
        if not anns or not data.get("hasMore"):
            break
