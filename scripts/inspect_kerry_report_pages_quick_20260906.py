#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"})

PAGES = [
    "https://www.sgpjbg.com/labels/jialijianshenianbao.html",
    "https://www.fxbaogao.com/detail/4702606",
    "https://www.fxbaogao.com/detail/5642153",
    "https://www.baogaobox.com/insights/250304000007937.html",
]

for url in PAGES:
    try:
        r = s.get(url, timeout=(20, 60), allow_redirects=True)
        r.encoding = r.apparent_encoding or r.encoding
        text = r.text
        soup = BeautifulSoup(text, "html.parser")
        print("PAGE", json.dumps({"requested": url, "resolved": r.url, "status": r.status_code, "type": r.headers.get("content-type"), "bytes": len(r.content), "title": soup.title.get_text(" ", strip=True) if soup.title else ""}, ensure_ascii=False), flush=True)
        for a in soup.find_all("a", href=True):
            label = " ".join(a.get_text(" ", strip=True).split())
            href = urljoin(r.url, a["href"])
            hay = (label + " " + href).lower()
            if any(k in hay for k in ("嘉里建设", "嘉里建設", "稳定分红", "kerry", "download", ".pdf", "4702606", "5642153", "250218")):
                print("ANCHOR", json.dumps({"text": label, "href": href, "raw": a["href"]}, ensure_ascii=False), flush=True)
        for tag in soup.find_all(True):
            attrs = {k: v for k, v in tag.attrs.items() if isinstance(v, str) and any(x in v.lower() for x in ("pdf", "download", "file", "4702606", "5642153", "250218"))}
            if attrs:
                print("TAG", json.dumps({"tag": tag.name, "attrs": attrs, "text": " ".join(tag.get_text(" ", strip=True).split())[:300]}, ensure_ascii=False), flush=True)
        for m in re.finditer(r".{0,300}(?:\.pdf|download|file_url|fileUrl|4702606|5642153|250218|稳定分红).{0,600}", text, flags=re.I | re.S):
            print("SNIP", re.sub(r"\s+", " ", m.group(0))[:1200], flush=True)
    except Exception as exc:
        print("ERROR", url, repr(exc), flush=True)
