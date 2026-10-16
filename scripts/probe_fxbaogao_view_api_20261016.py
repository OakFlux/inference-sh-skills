from __future__ import annotations

import re
from urllib.parse import urljoin

import requests

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.fxbaogao.com/view?id=1332144",
}

for root in ["https://www.fxbaogao.com/view?id=1332144", "https://m.fxbaogao.com/view?id=1332144"]:
    print("\nROOT", root, flush=True)
    r = session.get(root, headers=headers, timeout=120)
    print("ROOT_STATUS", r.status_code, r.url, r.headers.get("content-type"), len(r.content), flush=True)
    text = r.text
    scripts = re.findall(r"<script[^>]+src=[\"']([^\"']+)[\"']", text, re.I)
    for src in scripts:
        full = urljoin(r.url, src.strip())
        try:
            rr = session.get(full, headers=headers, timeout=120)
        except Exception as exc:
            print("SCRIPT_ERROR", full, repr(exc), flush=True)
            continue
        print("SCRIPT", rr.status_code, full, rr.headers.get("content-type"), len(rr.content), flush=True)
        js = rr.text
        # Print unique endpoint-like strings.
        strings = re.findall(r"[\"']([^\"']{3,300})[\"']", js)
        seen = set()
        for s in strings:
            if s in seen:
                continue
            low = s.lower()
            if any(k in low for k in ["api", "report", "document", "download", "pdf", "preview", "viewer", "page", "image", "docid", "fileurl", "1332144"]):
                seen.add(s)
                print("JS_STRING", s[:500], flush=True)
        for key in ["1332144", "report-image", "docId", "documentId", "fileUrl", "pdfUrl", "download", "/api/", "pageCount", "pages"]:
            for m in re.finditer(re.escape(key), js, re.I):
                print("JS_CTX", key, re.sub(r"\s+", " ", js[max(0,m.start()-500):m.end()+1200])[:2200], flush=True)
                break

# Try common API patterns discovered or likely.
candidates = [
    "https://www.fxbaogao.com/api/report/1332144",
    "https://www.fxbaogao.com/api/report?id=1332144",
    "https://www.fxbaogao.com/api/document/1332144",
    "https://www.fxbaogao.com/api/document?id=1332144",
    "https://www.fxbaogao.com/api/view?id=1332144",
    "https://www.fxbaogao.com/api/doc?id=1332144",
    "https://m.fxbaogao.com/api/report/1332144",
    "https://m.fxbaogao.com/api/report?id=1332144",
]
for url in candidates:
    try:
        r = session.get(url, headers={**headers, "Accept":"application/json,text/plain,*/*"}, timeout=60, allow_redirects=True)
        print("API_TRY", r.status_code, r.url, r.headers.get("content-type"), len(r.content), r.content[:500], flush=True)
    except Exception as exc:
        print("API_ERROR", url, repr(exc), flush=True)
