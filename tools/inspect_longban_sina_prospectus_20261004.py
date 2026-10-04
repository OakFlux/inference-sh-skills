from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

LIST_URL = "https://money.finance.sina.com.cn/corp/go.php/vISSUE_RaiseExplanation/stockid/605577.phtml"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}


def decode(content: bytes) -> str:
    for encoding in ("gb18030", "gbk", "utf-8"):
        try:
            text = content.decode(encoding)
        except Exception:
            continue
        if "招股说明" in text or "龙版传媒" in text:
            return text
    return content.decode("gb18030", errors="replace")


session = requests.Session()
session.headers.update(HEADERS)
response = session.get(LIST_URL, timeout=120, allow_redirects=True)
print("LIST", response.status_code, len(response.content), response.url, response.headers.get("content-type"), flush=True)
response.raise_for_status()
text = decode(response.content)
soup = BeautifulSoup(text, "html.parser")
matches = []
for anchor in soup.find_all("a", href=True):
    label = " ".join(anchor.get_text(" ", strip=True).split())
    if "招股说明书" not in label or "摘要" in label or "意向书" in label or "申报稿" in label:
        continue
    url = urljoin(response.url, anchor.get("href"))
    matches.append({"label": label, "url": url})
    print("MATCH", json.dumps(matches[-1], ensure_ascii=False), flush=True)

for match in matches:
    detail = session.get(match["url"], timeout=120, allow_redirects=True)
    print("DETAIL", detail.status_code, len(detail.content), detail.url, detail.headers.get("content-type"), flush=True)
    detail.raise_for_status()
    dtext = decode(detail.content)
    dsoup = BeautifulSoup(dtext, "html.parser")
    for anchor in dsoup.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split())
        href = urljoin(detail.url, anchor.get("href"))
        if ".pdf" in href.lower() or "下载公告" in label or "公告原文" in label:
            print("PDF_LINK", json.dumps({"label": label, "url": href}, ensure_ascii=False), flush=True)
    for url in sorted(set(re.findall(r'https?://[^\s"\'<>]+\.PDF', dtext, flags=re.I))):
        print("REGEX_PDF", url, flush=True)
