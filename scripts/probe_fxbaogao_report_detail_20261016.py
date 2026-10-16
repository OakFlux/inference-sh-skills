from __future__ import annotations

import requests

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://www.fxbaogao.com",
    "Referer": "https://www.fxbaogao.com/view?id=1332144",
    "X-Requested-With": "XMLHttpRequest",
}

base = "https://api.fxbaogao.com/mofoun/report/readReport/readReport"
param_sets = [
    {"reportId": "1332144"},
    {"reportId": "1332144", "isEnglish": "false"},
    {"reportId": "1332144", "isEnglish": "0"},
    {"reportId": "1332144", "source": "pc"},
    {"id": "1332144"},
    {"reportIds": "1332144"},
]
for params in param_sets:
    try:
        r = session.get(base, params=params, headers=headers, timeout=120, allow_redirects=True)
    except Exception as exc:
        print("READ_ERROR", params, repr(exc), flush=True)
        continue
    print("READ", params, r.status_code, r.url, r.headers.get("content-type"), len(r.content), flush=True)
    print("READ_BODY", r.text[:30000], flush=True)

for url in [
    "https://api.fxbaogao.com/mofoun/report/searchReport/detail/anon?id=1332144",
    "https://api.fxbaogao.com/mofoun/report/searchReport/detail/anon?reportId=1332144",
]:
    r = session.get(url, headers=headers, timeout=120, allow_redirects=True)
    print("DETAIL", r.status_code, r.url, r.headers.get("content-type"), len(r.content), flush=True)
    print("DETAIL_BODY", r.text[:30000], flush=True)
