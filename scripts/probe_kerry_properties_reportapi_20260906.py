#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
API = "https://reportapi.eastmoney.com/report/list"
OUT = Path("kerry-reportapi-pdfs")
OUT.mkdir(exist_ok=True)
RESULT = Path("kerry-reportapi-results.json")

s = requests.Session()
s.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/report/", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"})

QUERIES = [
    # Direct code attempts.
    ("2015-01-01", "2026-09-06", "00683"),
    ("2015-01-01", "2026-09-06", "683"),
    ("2015-01-01", "2026-09-06", "00683.HK"),
    # Narrow broad windows around known reports.
    ("2025-02-15", "2025-02-22", ""),
    ("2025-11-03", "2025-11-10", ""),
    ("2026-03-20", "2026-03-30", ""),
    ("2026-08-22", "2026-08-30", ""),
]


def is_target(row: dict) -> bool:
    hay = " ".join(str(row.get(k) or "") for k in ("title", "stockName", "stockCode", "orgName", "orgSName"))
    low = hay.lower()
    return (
        "嘉里建设" in hay
        or "嘉里建設" in hay
        or "kerry properties" in low
        or str(row.get("stockCode") or "") in {"00683", "683", "00683.HK", "683.HK"}
    )


def fetch_pdf(info_code: str) -> dict:
    candidates = [
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf?{int(time.time())}",
    ]
    rec = {"info_code": info_code, "attempts": []}
    for url in candidates:
        try:
            r = s.get(url, headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/report/", "Accept": "application/pdf,*/*"}, timeout=(30, 300), allow_redirects=True)
            att = {"url": url, "resolved": r.url, "status": r.status_code, "type": r.headers.get("content-type"), "bytes": len(r.content), "pdf": r.content.startswith(b"%PDF-")}
            rec["attempts"].append(att)
            print("PDF", json.dumps(att, ensure_ascii=False), flush=True)
            if r.status_code == 200 and r.content.startswith(b"%PDF-"):
                path = OUT / f"{info_code}.pdf"
                path.write_bytes(r.content)
                rec["path"] = str(path)
                return rec
        except Exception as exc:
            rec["attempts"].append({"url": url, "error": repr(exc)})
    return rec


def main() -> None:
    matches: dict[str, dict] = {}
    query_stats = []
    for begin, end, code in QUERIES:
        for qtype in (0, 1, 2):
            page = 1
            total = 1
            scanned = 0
            while page <= total:
                params = {
                    "industryCode": "*", "pageSize": "100", "industry": "*", "rating": "*", "ratingChange": "*",
                    "beginTime": begin, "endTime": end, "pageNo": str(page), "fields": "", "qType": str(qtype),
                    "orgCode": "", "code": code, "rcode": "", "p": str(page), "pageNum": str(page), "pageNumber": str(page),
                }
                try:
                    r = s.get(API, params=params, timeout=(30, 180))
                    print("QUERY", begin, end, code, qtype, page, r.status_code, len(r.content), flush=True)
                    r.raise_for_status()
                    payload = r.json()
                except Exception as exc:
                    print("QUERY ERROR", begin, end, code, qtype, page, repr(exc), flush=True)
                    break
                total = int(payload.get("TotalPage") or 1)
                rows = payload.get("data") or []
                scanned += len(rows)
                for row in rows:
                    if not is_target(row):
                        continue
                    info = str(row.get("infoCode") or "")
                    if not info:
                        continue
                    matches[info] = row
                    print("MATCH", json.dumps(row, ensure_ascii=False, default=str), flush=True)
                page += 1
                time.sleep(0.08)
            query_stats.append({"begin": begin, "end": end, "code": code, "qtype": qtype, "pages": total, "rows": scanned})

    reports = []
    for info, row in matches.items():
        reports.append({"metadata": row, "download": fetch_pdf(info)})
    RESULT.write_text(json.dumps({"query_stats": query_stats, "match_count": len(reports), "reports": reports}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("TOTAL MATCHES", len(reports), flush=True)


if __name__ == "__main__":
    main()
