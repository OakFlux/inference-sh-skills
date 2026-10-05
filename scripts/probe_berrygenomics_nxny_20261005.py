from __future__ import annotations

import re
import requests
from urllib.parse import urljoin

URLS = [
    "https://www.nxny.com/report/view_6098637.html",
    "https://www.nxny.com/report/view_4482804.html",
    "https://www.nxny.com/report/view_4416079.html",
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})

for url in URLS:
    print("\n===", url, "===", flush=True)
    for variant in [url, url.replace("https://", "http://"), url.replace("www.nxny.com", "nxny.com")]:
        try:
            r = session.get(variant, timeout=(20, 60), allow_redirects=True)
            print("GET", variant, r.status_code, r.url, r.headers.get("content-type"), len(r.content), flush=True)
            text = r.text
            print("PREFIX", repr(text[:1200]), flush=True)
            urls = set()
            for m in re.finditer(r'''(?:href|src|url|file|path|pdf|download)\s*[:=]\s*["']([^"']+)["']''', text, re.I):
                value = m.group(1)
                if any(k in value.lower() for k in ("pdf", "down", "report", "file", "view", "attach")):
                    urls.add(urljoin(r.url, value))
            for m in re.finditer(r'''https?://[^\s"'<>]+''', text, re.I):
                value = m.group(0)
                if any(k in value.lower() for k in ("pdf", "down", "report", "file", "attach")):
                    urls.add(value)
            print("CANDIDATES", flush=True)
            for value in sorted(urls):
                print(value, flush=True)
        except Exception as exc:
            print("ERROR", variant, repr(exc), flush=True)
