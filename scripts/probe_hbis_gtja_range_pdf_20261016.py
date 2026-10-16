from __future__ import annotations

import requests

s = requests.Session()
s.trust_env = False
base_headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/pdf,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.fxbaogao.com/view?id=1332144",
    "Origin": "https://www.fxbaogao.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}
urls = [
    "https://report.fxbaogao.com/report/2019/06/17/1332144.pdf",
    "http://report.fxbaogao.com/report/2019/06/17/1332144.pdf",
    "https://dr.fxbaogao.com/report/2019/06/17/1332144.pdf",
    "http://dr.fxbaogao.com/report/2019/06/17/1332144.pdf",
]
for url in urls:
    print("\nURL", url, flush=True)
    for range_value in ["bytes=0-1024", "bytes=0-65535", "bytes=0-", None]:
        headers = dict(base_headers)
        if range_value:
            headers["Range"] = range_value
        try:
            r = s.get(url, headers=headers, timeout=(15, 45), allow_redirects=False)
            print(
                "TRY", range_value,
                "status", r.status_code,
                "url", r.url,
                "ct", r.headers.get("content-type"),
                "len", len(r.content),
                "cr", r.headers.get("content-range"),
                "ar", r.headers.get("accept-ranges"),
                "cl", r.headers.get("content-length"),
                "loc", r.headers.get("location"),
                "head", r.content[:40],
                flush=True,
            )
        except Exception as exc:
            print("ERROR", range_value, repr(exc), flush=True)
