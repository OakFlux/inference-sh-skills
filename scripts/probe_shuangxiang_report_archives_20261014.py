#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

URLS = [
    "https://q.stock.sohu.com/cn/002395/news_gg.shtml",
    "https://webf10.gw.com.cn/SZ/B11/SZ002395_B11.html",
    "https://vip.stock.finance.sina.com.cn/q/go.php/vReport_List/kind/company/index.phtml?symbol=002395",
    "https://vip.stock.finance.sina.com.cn/q/go.php/vReport_List/kind/company/index.phtml?symbol=sz002395",
    "https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/company/index.phtml?symbol=sz002395",
]

session = requests.Session()
session.headers.update(HEADERS)

for url in URLS:
    print("\n=== URL", url, "===")
    try:
        response = session.get(url, timeout=90, allow_redirects=True)
        print("STATUS", response.status_code, response.headers.get("content-type"), "BYTES", len(response.content), "FINAL", response.url)
        response.raise_for_status()
        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding
        html = response.text
        print("ENCODING", response.encoding)
        print("HEAD", re.sub(r"\s+", " ", html[:1500]))
        soup = BeautifulSoup(html, "html.parser")
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        print("TEXT", text[:6000])
        seen = set()
        for a in soup.find_all("a", href=True):
            label = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
            href = urljoin(response.url, a.get("href"))
            hay = f"{label} {href}"
            if any(keyword in hay for keyword in ["双象", "002395", "报告", "研报", "vReport", ".pdf", ".PDF"]):
                key = (label, href)
                if key not in seen:
                    seen.add(key)
                    print("LINK", repr(label), href)
    except Exception as exc:
        print("ERROR", repr(exc))
