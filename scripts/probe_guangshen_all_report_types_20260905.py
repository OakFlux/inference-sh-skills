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

WINDOWS = [
    ("2019-09-27", "2019-10-05"),
    ("2024-07-12", "2024-07-20"),
    ("2025-10-27", "2025-11-04"),
]
KEYWORDS = ["广深铁路", "广铁核心枢纽", "广铁枢纽高铁化", "内生增长动力充足"]
results = []

for begin, end in WINDOWS:
    for qtype in (0, 1, 2):
        page = 1
        total = 1
        while page <= total:
            params = {
                "industryCode": "*", "pageSize": "100", "industry": "*", "rating": "*", "ratingChange": "*",
                "beginTime": begin, "endTime": end, "pageNo": str(page), "fields": "", "qType": str(qtype),
                "orgCode": "", "code": "", "rcode": "", "p": str(page), "pageNum": str(page), "pageNumber": str(page),
            }
            r = s.get(API, params=params, timeout=(30, 180))
            print("GET", begin, end, qtype, page, r.status_code, len(r.content), flush=True)
            r.raise_for_status()
            data = r.json()
            total = int(data.get("TotalPage") or 1)
            rows = data.get("data") or []
            for row in rows:
                hay = " ".join(str(row.get(k) or "") for k in ("title", "stockName", "stockCode", "orgName", "orgSName"))
                if any(k in hay for k in KEYWORDS) or str(row.get("stockCode") or "") in {"601333", "00525", "525"}:
                    item = {"begin": begin, "end": end, "qType": qtype, **row}
                    results.append(item)
                    print("MATCH", json.dumps(item, ensure_ascii=False, default=str), flush=True)
                    info = str(row.get("infoCode") or "")
                    if info:
                        url = f"https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf"
                        try:
                            p = s.get(url, headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/report/"}, timeout=(30, 180))
                            print("PDF", info, p.status_code, p.headers.get("content-type"), len(p.content), p.content[:5], flush=True)
                        except Exception as exc:
                            print("PDFERR", info, repr(exc), flush=True)
            page += 1
            time.sleep(0.15)

Path("guangshen-all-types-probe.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print("TOTAL MATCHES", len(results), flush=True)
