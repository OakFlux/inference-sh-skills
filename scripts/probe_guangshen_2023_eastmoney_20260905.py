#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import time
from pathlib import Path

import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
API = "https://reportapi.eastmoney.com/report/list"
s = requests.Session()
s.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})
results = []

queries = [
    ("2023-01-01", "2023-12-31", 0, "601333"),
    ("2023-09-14", "2023-09-20", 0, ""),
    ("2023-09-14", "2023-09-20", 1, ""),
    ("2023-09-14", "2023-09-20", 2, ""),
    ("2023-06-18", "2023-06-23", 0, ""),
]

for begin, end, qtype, code in queries:
    page = 1
    total = 1
    while page <= total:
        params = {
            "industryCode": "*", "pageSize": "100", "industry": "*", "rating": "*", "ratingChange": "*",
            "beginTime": begin, "endTime": end, "pageNo": str(page), "fields": "", "qType": str(qtype),
            "orgCode": "", "code": code, "rcode": "", "p": str(page), "pageNum": str(page), "pageNumber": str(page),
        }
        r = s.get(API, params=params, timeout=(30, 180))
        print("GET", begin, end, qtype, code, page, r.status_code, len(r.content), flush=True)
        r.raise_for_status()
        data = r.json()
        total = int(data.get("TotalPage") or 1)
        rows = data.get("data") or []
        print("ROWS", len(rows), "TOTALPAGES", total, flush=True)
        for row in rows:
            hay = " ".join(str(row.get(k) or "") for k in ("title", "stockName", "stockCode", "orgName", "orgSName"))
            if "广深铁路" in hay or str(row.get("stockCode") or "") in {"601333", "00525", "525"} or "全面迈入高铁运营领域" in hay or "步入高铁运营时代" in hay:
                item = {"query": [begin, end, qtype, code], **row}
                results.append(item)
                print("MATCH", json.dumps(item, ensure_ascii=False, default=str), flush=True)
                info = str(row.get("infoCode") or "")
                if info:
                    url = f"https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf"
                    p = s.get(url, headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/report/"}, timeout=(30, 300))
                    print("PDF", info, p.status_code, p.headers.get("content-type"), len(p.content), p.content[:5], flush=True)
                    if p.status_code == 200 and p.content.startswith(b"%PDF-"):
                        Path(f"eastmoney-{info}.pdf").write_bytes(p.content)
        page += 1
        time.sleep(0.15)

Path("guangshen-2023-eastmoney-probe.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print("TOTAL", len(results), flush=True)
