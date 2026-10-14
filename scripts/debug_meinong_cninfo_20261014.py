#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import time
import requests

CODE = "301156"
H = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://www.cninfo.com.cn",
    "Referer": f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={CODE}",
    "X-Requested-With": "XMLHttpRequest",
}
S = requests.Session(); S.headers.update(H)

for url in [
    "https://www.cninfo.com.cn/new/data/szse_stock.json",
    "https://www.cninfo.com.cn/new/data/szse_stock.json?_=" + str(int(time.time()*1000)),
    "https://www.cninfo.com.cn/data20/dataapi/stock/p_stock0000",
]:
    try:
        r = S.get(url, timeout=45)
        print("GET", url, r.status_code, r.headers.get("content-type"), len(r.content), r.text[:300].replace("\n", " "))
        if r.ok and "json" in (r.headers.get("content-type") or ""):
            data = r.json()
            text = json.dumps(data, ensure_ascii=False)
            idx = text.find(CODE)
            print("CODE_INDEX", idx, text[max(0,idx-500):idx+1000] if idx>=0 else "")
            def walk(obj):
                if isinstance(obj, dict):
                    if any(str(v)==CODE for v in obj.values()):
                        print("MATCH", json.dumps(obj, ensure_ascii=False))
                    for v in obj.values(): walk(v)
                elif isinstance(obj, list):
                    for v in obj: walk(v)
            walk(data)
    except Exception as e:
        print("GET_ERROR", url, repr(e))

query_url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
stock_values = [CODE]
# Add likely values discovered manually if any can be extracted from the stock list in a later run.
for stock in stock_values:
    for category, searchkey in [
        ("category_ndbg_szsh", ""),
        ("", "年度报告"),
        ("", "美农生物"),
        ("", ""),
    ]:
        payload = {
            "pageNum":"1","pageSize":"30","column":"szse","tabName":"fulltext","plate":"sz",
            "stock":stock,"searchkey":searchkey,"secid":"","category":category,"trade":"",
            "seDate":"2021-01-01~2026-10-14","sortName":"","sortType":"","isHLtitle":"true",
        }
        try:
            r = S.post(query_url, data=payload, timeout=60)
            print("POST", stock, category, searchkey, r.status_code, r.headers.get("content-type"), len(r.content))
            print("POST_HEAD", r.text[:500].replace("\n", " "))
            if r.ok:
                d = r.json()
                anns = d.get("announcements") or []
                print("COUNT", len(anns), "TOTAL", d.get("totalAnnouncement"), d.get("totalpages"))
                for a in anns[:10]:
                    print("ANN", a.get("secCode"), a.get("secName"), a.get("orgId"), a.get("announcementTitle"), a.get("adjunctUrl"))
        except Exception as e:
            print("POST_ERROR", stock, category, searchkey, repr(e))
