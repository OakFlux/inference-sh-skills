from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

URL = "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=7390878&stockid=605577"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}

r = requests.get(URL, headers=HEADERS, timeout=120, allow_redirects=True)
print("PAGE", r.status_code, len(r.content), r.url, r.headers.get("content-type"), flush=True)
r.raise_for_status()
text = r.content.decode("gb18030", errors="replace")
soup = BeautifulSoup(text, "html.parser")
print("TITLE", soup.title.get_text(" ", strip=True) if soup.title else "", flush=True)
for a in soup.find_all("a", href=True):
    label = " ".join(a.get_text(" ", strip=True).split())
    href = urljoin(r.url, a.get("href"))
    if ".pdf" in href.lower() or "下载公告" in label or "公告原文" in label:
        print("LINK", json.dumps({"label": label, "url": href}, ensure_ascii=False), flush=True)
for u in sorted(set(re.findall(r'https?://[^\s"\'<>]+\.PDF', text, flags=re.I))):
    print("REGEX_PDF", u, flush=True)
