from __future__ import annotations

import re
from urllib.parse import urljoin
import requests

URL = "https://data.eastmoney.com/report/info/AP201210260005551948.html"
s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Referer": "https://data.eastmoney.com/",
})
r = s.get(URL, timeout=(20, 120))
print("PAGE", r.status_code, len(r.content), r.url, flush=True)
r.raise_for_status()
html = r.text
srcs = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, re.I)
print("SCRIPTS", len(srcs), flush=True)
for src in srcs:
    full = urljoin(URL, src)
    print("SCRIPT_URL", full, flush=True)
    try:
        rr = s.get(full, timeout=(20, 120), headers={"Referer": URL})
        print("SCRIPT_HTTP", rr.status_code, rr.headers.get("content-type"), len(rr.content), rr.url, flush=True)
        if not rr.ok or len(rr.content) > 5_000_000:
            continue
        text = rr.text
        hits = []
        for pat in ("pdf-link", "attach_pages", "zwinfo", "encodeUrl", "pdf.dfcfw", "infocode", "infoCode", "reportapi", "附件未授权", "pdfUrl", "pdfurl"):
            if pat.lower() in text.lower():
                hits.append(pat)
        if hits:
            print("SCRIPT_HITS", full, hits, flush=True)
            lines = text.splitlines()
            for i, line in enumerate(lines, 1):
                low = line.lower()
                if any(p.lower() in low for p in hits):
                    print("JS_LINE", i, line[:12000], flush=True)
    except Exception as exc:
        print("SCRIPT_ERROR", full, repr(exc), flush=True)

# Also inspect inline scripts around zwinfo and pdf-link selectors.
for pat in ("pdf-link", "zwinfo", "attach_pages", "info_code", "pdf.dfcfw"):
    pos = html.lower().find(pat.lower())
    print("INLINE_POS", pat, pos, flush=True)
    if pos >= 0:
        print("INLINE_CONTEXT", html[max(0, pos-2000):pos+6000], flush=True)
