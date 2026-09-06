#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import time
from pathlib import Path

import requests

API = "https://reportapi.eastmoney.com/report/list"
CODE = "600664"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
s = requests.Session()
s.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})

all_rows = {}
for year in range(2015, 2027):
    begin = f"{year}-01-01"
    end = "2026-09-06" if year == 2026 else f"{year}-12-31"
    for qtype in (0, 1, 2):
        params = {
            "industryCode": "*", "pageSize": "100", "industry": "*", "rating": "*", "ratingChange": "*",
            "beginTime": begin, "endTime": end, "pageNo": "1", "fields": "", "qType": str(qtype),
            "orgCode": "", "code": CODE, "rcode": "", "p": "1", "pageNum": "1", "pageNumber": "1",
        }
        r = s.get(API, params=params, timeout=(30, 180))
        print("QUERY", year, qtype, r.status_code, len(r.content), flush=True)
        r.raise_for_status()
        payload = r.json()
        rows = payload.get("data") or []
        print("ROWS", year, qtype, len(rows), "TOTALPAGE", payload.get("TotalPage"), flush=True)
        for row in rows:
            info = str(row.get("infoCode") or "")
            if info:
                all_rows[info] = row
        time.sleep(0.1)

rows = list(all_rows.values())
rows.sort(key=lambda r: (int(r.get("attachPages") or 0), str(r.get("publishDate") or "")), reverse=True)
print("TOTAL", len(rows), flush=True)
for row in rows:
    print("REPORT", json.dumps(row, ensure_ascii=False, default=str), flush=True)
    info = str(row.get("infoCode") or "")
    if int(row.get("attachPages") or 0) >= 6:
        url = f"https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf"
        try:
            p = s.get(url, headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/report/"}, timeout=(30, 300))
            ok = p.status_code == 200 and p.content.startswith(b"%PDF-")
            print("PDF", info, p.status_code, p.headers.get("content-type"), len(p.content), ok, flush=True)
            if ok:
                out = Path("hayao-direct-pdfs")
                out.mkdir(exist_ok=True)
                (out / f"{info}.pdf").write_bytes(p.content)
        except Exception as exc:
            print("PDFERR", info, repr(exc), flush=True)

Path("hayao-direct-probe.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
