from __future__ import annotations

import html as html_lib
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.fxbaogao.com"
REPORT_IDS = [4788440, 4438234, 4069371]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": BASE + "/view?id=4788440",
})

# Discover the current view-page JavaScript chunks from HTML and inspect them.
view_response = session.get(BASE + "/view?id=4788440", timeout=(20, 180))
print("VIEW", view_response.status_code, len(view_response.content), view_response.url)
view_response.raise_for_status()
view_text = html_lib.unescape(view_response.text).replace("\\/", "/")
soup = BeautifulSoup(view_text, "html.parser")
asset_urls = [urljoin(view_response.url, tag["src"]) for tag in soup.find_all("script", src=True)]
for asset_url in asset_urls:
    try:
        response = session.get(asset_url, timeout=(20, 180))
        print("JS", response.status_code, len(response.content), response.url)
        if response.status_code != 200:
            continue
        text = response.text
        if "/api/report" not in text and "report/read" not in text:
            continue
        for keyword in ("/api/report/read", "/api/report", "download", "file_url", "fileUrl", "pdf", "pages", "preview"):
            positions = [m.start() for m in re.finditer(re.escape(keyword), text, flags=re.I)]
            if positions:
                print("KEY", keyword, "COUNT", len(positions))
            for pos in positions[:30]:
                print(re.sub(r"\s+", " ", text[max(0,pos-1000):pos+2500])[:3800])
    except Exception as exc:
        print("JS ERROR", asset_url, repr(exc))

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
            print(r.text[:10000])
        except Exception as exc:
            print("ERROR", url, repr(exc))
