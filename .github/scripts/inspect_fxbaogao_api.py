from __future__ import annotations

import json
import re

import requests

BASE = "https://www.fxbaogao.com"
REPORT_IDS = [4788440, 4438234, 4069371]
JS_URL = "https://static.fxbaogao.com/report_view_source/_next/static/chunks/pages/view-60434c7812efed80.js"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": BASE + "/view?id=4788440",
})

response = session.get(JS_URL, timeout=(20, 180))
print("JS", response.status_code, len(response.content), response.url)
response.raise_for_status()
text = response.text
for keyword in ("/api/report/read", "/api/report", "download", "file_url", "fileUrl", "pdf", "pages", "preview"):
    positions = [m.start() for m in re.finditer(re.escape(keyword), text, flags=re.I)]
    print("KEY", keyword, "COUNT", len(positions))
    for pos in positions[:30]:
        print(re.sub(r"\s+", " ", text[max(0,pos-1000):pos+2500])[:3800])

for report_id in REPORT_IDS:
    print("\nREPORT", report_id)
    urls = [
        f"{BASE}/api/report/read?report_id={report_id}",
        f"{BASE}/api/report/detail?report_id={report_id}",
        f"{BASE}/api/report/preview?report_id={report_id}",
        f"{BASE}/api/report/download?report_id={report_id}",
        f"{BASE}/api/report/{report_id}",
    ]
    for url in urls:
        try:
            r = session.get(url, timeout=(20, 120), allow_redirects=True)
            print("GET", url, "STATUS", r.status_code, "TYPE", r.headers.get("content-type"), "BYTES", len(r.content), "FINAL", r.url)
            print(r.text[:5000])
        except Exception as exc:
            print("ERROR", url, repr(exc))
