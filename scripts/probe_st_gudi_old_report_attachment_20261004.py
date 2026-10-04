from __future__ import annotations

import json
import re
from urllib.parse import quote

import requests

INFO = "AP201210260005551948"
DETAIL = f"https://data.eastmoney.com/report/info/{INFO}.html"

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Referer": "https://data.eastmoney.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})

r = s.get(DETAIL, timeout=(20, 120))
print("DETAIL", r.status_code, r.headers.get("content-type"), len(r.content), r.url, flush=True)
print("HEADERS", json.dumps(dict(r.headers), ensure_ascii=False), flush=True)
text = r.text
for i, line in enumerate(text.splitlines(), 1):
    low = line.lower()
    if any(k in low for k in ("pdf", "attach", "encodeurl", "download", "附件", INFO.lower(), "reportapi")):
        print("HTML_LINE", i, line[:4000], flush=True)

patterns = [
    r'https?://[^"\']+',
    r'encodeUrl\s*[:=]\s*["\']([^"\']+)',
    r'attach[^"\']*["\']([^"\']+)',
    r'pdf[^"\']*["\']([^"\']+)',
]
for pattern in patterns:
    try:
        vals = re.findall(pattern, text, re.I)
        print("PATTERN", pattern, json.dumps(vals[:100], ensure_ascii=False), flush=True)
    except Exception as exc:
        print("PATTERN_ERROR", pattern, repr(exc), flush=True)

urls = []
for prefix in ("H1", "H2", "H3", "H4", "H5", "H0"):
    for suffix in ("1", "2", "0"):
        for ext in ("pdf", "PDF"):
            urls.append(f"https://pdf.dfcfw.com/pdf/{prefix}_{INFO}_{suffix}.{ext}")
            urls.append(f"http://pdf.dfcfw.com/pdf/{prefix}_{INFO}_{suffix}.{ext}")

# Known Eastmoney attachment/download route shapes seen in current pages.
urls.extend([
    f"https://data.eastmoney.com/report/zw_stock.jshtml?infocode={INFO}",
    f"https://reportapi.eastmoney.com/report/detail?infoCode={INFO}",
    f"https://reportapi.eastmoney.com/report/detail?infoCode={INFO}&qType=0",
    f"https://data.eastmoney.com/report/zw_stock.jshtml?encodeUrl={quote(INFO)}",
])

seen = set()
for url in urls:
    if url in seen:
        continue
    seen.add(url)
    try:
        rr = s.get(url, timeout=(15, 60), allow_redirects=True, headers={"Referer": DETAIL, "Accept": "application/pdf,application/json,text/plain,*/*"})
        print("PROBE", rr.status_code, rr.headers.get("content-type"), len(rr.content), rr.url, url, repr(rr.content[:80]), flush=True)
        if rr.content.startswith(b"%PDF"):
            print("FOUND_PDF", url, len(rr.content), flush=True)
            break
    except Exception as exc:
        print("PROBE_ERROR", url, repr(exc), flush=True)
