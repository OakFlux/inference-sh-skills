from __future__ import annotations

import json
import re
from pathlib import Path

import requests

URL = "https://data.eastmoney.com/newstatic/js/report/singlestock.js"
OUT = Path("eastmoney_singlestock_api_excerpts.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/report/605577.html",
}

r = requests.get(URL, headers=HEADERS, timeout=180)
r.raise_for_status()
text = r.text
patterns = [
    r"/report/list",
    r"report/list",
    r"dataurl\(\)",
    r"qType",
    r"beginTime",
    r"endTime",
    r"reportapi",
    r"pageSize",
    r"orgCode",
    r"code:",
    r"secucode",
]
results = {}
for pattern in patterns:
    items = []
    for m in re.finditer(pattern, text, re.I):
        items.append(text[max(0, m.start()-1600): min(len(text), m.end()+3000)])
        if len(items) >= 30:
            break
    results[pattern] = items
    print("PATTERN", pattern, "COUNT", len(items), flush=True)
    for i, item in enumerate(items, 1):
        print("EXCERPT", pattern, i, json.dumps(item, ensure_ascii=False), flush=True)

# Also extract all URL-like and API path strings mentioning report.
strings = sorted(set(re.findall(r'["\']([^"\']*(?:report|Report)[^"\']*)["\']', text)))
results["report_strings"] = strings
print("REPORT_STRINGS", json.dumps(strings[:500], ensure_ascii=False), flush=True)
OUT.write_text(json.dumps({"url": URL, "bytes": len(r.content), "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
