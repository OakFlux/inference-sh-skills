#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

URL = "https://webf10.gw.com.cn/SZ/B16/SZ002395_B16.html"
H = {"User-Agent": "Mozilla/5.0", "Accept-Language": "zh-CN,zh;q=0.9"}
r = requests.get(URL, headers=H, timeout=90)
print("STATUS", r.status_code, r.headers.get("content-type"), len(r.content), r.url)
r.raise_for_status(); r.encoding = "utf-8"
html = r.text
print("HTML_HEAD", html[:3000].replace("\n", " "))

# Print script variables and lines around research-related keywords.
for line_no, line in enumerate(html.splitlines(), 1):
    compact = re.sub(r"\s+", " ", line).strip()
    if any(k in compact for k in ["国联证券", "研究报告", "目标价", "评级", "report", "research", "研报", "forecast", "broker", "jg", "机构"]):
        print("LINE", line_no, compact[:8000])

soup = BeautifulSoup(html, "html.parser")
print("TITLE", soup.title.get_text(" ", strip=True) if soup.title else "")
print("ALL_LINKS")
for a in soup.find_all("a", href=True):
    label = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
    href = urljoin(r.url, a.get("href"))
    print(json.dumps({"label": label, "href": href, "onclick": a.get("onclick"), "class": a.get("class")}, ensure_ascii=False))

print("SCRIPT_SRCS")
for s in soup.find_all("script"):
    if s.get("src"):
        print(urljoin(r.url, s.get("src")))
    elif s.string and any(k in s.string for k in ["国联", "研究", "评级", "002395", "forecast"]):
        print("INLINE", s.string[:20000])

text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
print("TEXT_FULL", text[:50000])
