from __future__ import annotations

import requests

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/pdf,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.fxbaogao.com/view?id=1332144",
    "Origin": "https://www.fxbaogao.com",
}

paths = [
    "/report/2019/06/17/1332144.pdf",
    "/report-cn/2019/06/17/1332144.pdf",
    "/report-en/2019/06/17/1332144.pdf",
    "report/2019/06/17/1332144.pdf",
]
hosts = [
    "https://report.fxbaogao.com",
    "https://dr.fxbaogao.com",
    "https://public.fxbaogao.com",
    "https://static.fxbaogao.com",
    "https://oss.fxbaogao.com",
]
for host in hosts:
    for path in paths:
        url = host + path
        try:
            r = session.get(url, headers=headers, timeout=120, allow_redirects=True)
            print("PDF_TRY", r.status_code, r.url, r.headers.get("content-type"), len(r.content), r.content[:20], flush=True)
        except Exception as exc:
            print("PDF_ERROR", url, repr(exc), flush=True)
