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

js_url = "https://www.fxbaogao.com/_fxbg/2610141742/js/app-pages-fxbg-main-js.fd6234d1ab18d90a303e.chunk.js"
r = session.get(js_url, headers=headers, timeout=120)
print("JS", r.status_code, len(r.content), r.headers.get("content-type"), flush=True)
js = r.text
for key in [
    "urlPdf:function",
    "urlPdfByDownload:function",
    "pdfViewer:function",
    "HOST_DOWNLOAD_OSSBUY",
    "HOST_PDFSTATIC",
    "PATH_PDF",
    "PDFSTATIC_IMAGES",
    "report.fxbaogao.com",
    "pdfPath",
    "readReport/readReport",
    "detail/anon",
]:
    print("\n=== KEY", key, flush=True)
    start = 0
    count = 0
    while True:
        idx = js.find(key, start)
        if idx < 0:
            break
        count += 1
        print("OCC", count, "INDEX", idx, flush=True)
        print(js[max(0, idx-2000):min(len(js), idx+5000)], flush=True)
        start = idx + len(key)
        if count >= 5:
            break

print("TAIL", js[-1000:], flush=True)
map_match = re.search(r"sourceMappingURL=([^\s*]+)", js[-2000:])
if map_match:
    map_url = urljoin(js_url, map_match.group(1))
    mr = session.get(map_url, headers=headers, timeout=120)
    print("MAP", mr.status_code, map_url, mr.headers.get("content-type"), len(mr.content), flush=True)
    if mr.status_code == 200:
        mtext = mr.text
        for key in ["urlPdf", "pdfViewer", "HOST_DOWNLOAD_OSSBUY", "report.fxbaogao.com", "detail/anon"]:
            idx = mtext.find(key)
            print("MAP_KEY", key, idx, flush=True)
            if idx >= 0:
                print(mtext[max(0,idx-3000):idx+8000], flush=True)
