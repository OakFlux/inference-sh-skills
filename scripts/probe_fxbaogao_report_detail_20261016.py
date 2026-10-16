from __future__ import annotations

import json
import requests

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://www.fxbaogao.com",
    "Referer": "https://www.fxbaogao.com/view?id=1332144",
}

api_urls = [
    "https://api.fxbaogao.com/mofoun/report/searchReport/detail/anon?id=1332144",
    "https://api.fxbaogao.com/mofoun/report/readReport/readReport?reportId=1332144",
]
for url in api_urls:
    try:
        r = session.get(url, headers=headers, timeout=120, allow_redirects=True)
    except Exception as exc:
        print("API_ERROR", url, repr(exc), flush=True)
        continue
    print("API", r.status_code, r.url, r.headers.get("content-type"), len(r.content), flush=True)
    print("API_BODY", r.text[:20000], flush=True)

pdf_candidates = [
    "https://public.fxbaogao.com/report/2019/06/17/1332144.pdf",
    "https://public.fxbaogao.com/report-cn/2019/06/17/1332144.pdf",
    "https://public.fxbaogao.com/report/2019/06/17/1332144.PDF",
    "https://public.fxbaogao.com/report-cn/2019/06/17/1332144.PDF",
]
for url in pdf_candidates:
    try:
        r = session.get(url, headers={**headers, "Accept":"application/pdf,*/*;q=0.8"}, timeout=120, allow_redirects=True)
    except Exception as exc:
        print("PDF_ERROR", url, repr(exc), flush=True)
        continue
    print("PDF", r.status_code, r.url, r.headers.get("content-type"), len(r.content), r.content[:20], flush=True)
