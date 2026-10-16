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

tests = [
    ("detail-query-empty", "https://api.fxbaogao.com/mofoun/report/searchReport/detail/anon?id=1332144", "json", {}),
    ("detail-json-id", "https://api.fxbaogao.com/mofoun/report/searchReport/detail/anon", "json", {"id": 1332144}),
    ("detail-json-reportId", "https://api.fxbaogao.com/mofoun/report/searchReport/detail/anon", "json", {"reportId": 1332144}),
    ("detail-form-id", "https://api.fxbaogao.com/mofoun/report/searchReport/detail/anon", "form", {"id": "1332144"}),
    ("detail-form-reportId", "https://api.fxbaogao.com/mofoun/report/searchReport/detail/anon", "form", {"reportId": "1332144"}),
    ("read-query-empty", "https://api.fxbaogao.com/mofoun/report/readReport/readReport?reportId=1332144", "json", {}),
    ("read-json-reportId", "https://api.fxbaogao.com/mofoun/report/readReport/readReport", "json", {"reportId": 1332144}),
    ("read-json-id", "https://api.fxbaogao.com/mofoun/report/readReport/readReport", "json", {"id": 1332144}),
    ("read-form-reportId", "https://api.fxbaogao.com/mofoun/report/readReport/readReport", "form", {"reportId": "1332144"}),
]

for label, url, mode, payload in tests:
    try:
        if mode == "json":
            r = session.post(url, headers={**headers, "Content-Type":"application/json;charset=UTF-8"}, json=payload, timeout=120, allow_redirects=True)
        else:
            r = session.post(url, headers={**headers, "Content-Type":"application/x-www-form-urlencoded"}, data=payload, timeout=120, allow_redirects=True)
    except Exception as exc:
        print("ERROR", label, repr(exc), flush=True)
        continue
    print("TEST", label, r.status_code, r.url, r.headers.get("content-type"), len(r.content), flush=True)
    print("BODY", r.text[:30000], flush=True)
