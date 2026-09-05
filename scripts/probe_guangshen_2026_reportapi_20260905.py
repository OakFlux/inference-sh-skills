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

queries = [
    ("2026-01-01", "2026-09-05", "601333"),
    ("2026-03-29", "2026-04-08", ""),
    ("2026-04-28", "2026-05-15", ""),
    ("2026-08-25", "2026-09-05", ""),
]
results = []
seen = set()
for begin, end, code in queries:
    for qtype in (0, 1, 2):
        page = 1
        total = 1
        while page <= total:
            params = {
                "industryCode": "*", "pageSize": "100", "industry": "*", "rating": "*", "ratingChange": "*",
                "beginTime": begin, "endTime": end, "pageNo": str(page), "fields": "", "qType": str(qtype),
                "orgCode": "", "code": code, "rcode": "", "p": str(page), "pageNum": str(page), "pageNumber": str(page),
            }
            r = s.get(API, params=params, timeout=(30, 180))
            print("GET", begin, end, code, qtype, page, r.status_code, len(r.content), flush=True)
            r.raise_for_status()
            payload = r.json()
            total = int(payload.get("TotalPage") or 1)
            rows = payload.get("data") or []
            print("ROWS", len(rows), "TOTAL", total, flush=True)
            for row in rows:
                hay = " ".join(str(row.get(k) or "") for k in ("title", "stockName", "stockCode", "orgName", "orgSName"))
                if "广深铁路" not in hay and str(row.get("stockCode") or "") not in {"601333", "00525", "525"}:
                    continue
                info = str(row.get("infoCode") or "")
                if info in seen:
                    continue
                seen.add(info)
                item = {"query": [begin, end, code, qtype], **row}
                results.append(item)
                print("MATCH", json.dumps(item, ensure_ascii=False, default=str), flush=True)
                if info:
                    candidates = [
                        f"https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf",
                        f"https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf?{int(time.time())}",
                    ]
                    for u in candidates:
                        try:
                            p = s.get(u, headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/report/"}, timeout=(30, 300))
                            print("PDF", info, p.status_code, p.headers.get("content-type"), len(p.content), p.content[:5], u, flush=True)
                            if p.status_code == 200 and p.content.startswith(b"%PDF-"):
                                Path(f"guangshen-2026-{info}.pdf").write_bytes(p.content)
                                break
                        except Exception as exc:
                            print("PDFERR", info, repr(exc), flush=True)
            page += 1
            time.sleep(0.1)

Path("guangshen-2026-reportapi-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print("TOTAL MATCHES", len(results), flush=True)
