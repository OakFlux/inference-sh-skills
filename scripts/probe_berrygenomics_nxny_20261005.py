from __future__ import annotations

import re
import requests
from urllib.parse import urljoin

URLS = [
    "https://www.nxny.com/stock/stock_000710/",
    "https://www.nxny.com/stock/stock_000710/index_2.html",
    "https://www.nxny.com/stock/stock_000710/index_3.html",
    "https://www.nxny.com/report/view_6098637.html",
    "https://www.nxny.com/report/view_4482804.html",
    "https://www.nxny.com/report/view_4416079.html",
]
TARGETS = ["6098637", "4482804", "4416079", "解码生命经纬", "基因测序行业的领头羊", "肿瘤早筛"]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})

for url in URLS:
    print("\n===", url, "===", flush=True)
    try:
        r = session.get(url, timeout=(20, 60), allow_redirects=True)
        print("GET", url, r.status_code, r.url, r.headers.get("content-type"), len(r.content), flush=True)
        encoding = r.apparent_encoding or r.encoding or "utf-8"
        try:
            text = r.content.decode(encoding, errors="replace")
        except Exception:
            text = r.text
        print("ENCODING", encoding, flush=True)
        print("PREFIX", repr(text[:1200]), flush=True)
        for target in TARGETS:
            pos = text.find(target)
            if pos >= 0:
                print("CONTEXT", target, repr(text[max(0, pos-1200): pos+2200]), flush=True)
        urls = set()
        for m in re.finditer(r'''(?:href|src|url|file|path|pdf|download)\s*[:=]\s*["']([^"']+)["']''', text, re.I):
            value = m.group(1)
            if any(k in value.lower() for k in ("pdf", "down", "report", "file", "view", "attach", "upload")):
                urls.add(urljoin(r.url, value))
        for m in re.finditer(r'''https?://[^\s"'<>]+''', text, re.I):
            value = m.group(0)
            if any(k in value.lower() for k in ("pdf", "down", "report", "file", "attach", "upload")):
                urls.add(value)
        print("CANDIDATES", flush=True)
        for value in sorted(urls):
            print(value, flush=True)
    except Exception as exc:
        print("ERROR", url, repr(exc), flush=True)
