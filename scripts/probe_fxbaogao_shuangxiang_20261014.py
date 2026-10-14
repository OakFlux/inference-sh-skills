#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

REPORTS = [
    {"id": "1859436", "date": "2019/12/15", "title": "立足原料优势，看好公司PMMA产业链一体化布局"},
    {"id": "2156162", "date": "2020/09/06", "title": "收到拆迁款加速重庆超纤项目建设，看好公司PMMA产业链一体化发展"},
    {"id": "244900", "date": "2018/06/14", "title": "超纤革稳健发展，PMMA放量在即进口替代加速"},
    {"id": "15112", "date": "2018/05/02", "title": "营收规模持续增长，光学级PMMA不断向下游延伸"},
]

H = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
S = requests.Session(); S.headers.update(H)

for item in REPORTS:
    rid = item["id"]
    print("\n### REPORT", json.dumps(item, ensure_ascii=False))
    for url in [
        f"https://www.fxbaogao.com/detail/{rid}",
        f"https://www.fxbaogao.com/view?id={rid}",
        f"https://www.fxbaogao.com/view/{rid}",
        f"https://api.fxbaogao.com/report/{rid}",
        f"https://www.fxbaogao.com/api/report/{rid}",
    ]:
        try:
            r = S.get(url, timeout=45, allow_redirects=True)
            print("FETCH", url, "STATUS", r.status_code, "TYPE", r.headers.get("content-type"), "BYTES", len(r.content), "FINAL", r.url)
            if r.status_code == 200 and "text" in (r.headers.get("content-type") or ""):
                if not r.encoding or r.encoding.lower() == "iso-8859-1":
                    r.encoding = r.apparent_encoding
                text = r.text
                print("HEAD", re.sub(r"\s+", " ", text[:1200]))
                for pat in [r'https?://[^"\'<> ]+', r'/(?:api|report|download|file|pdf|view)[^"\'<> ]*']:
                    vals = sorted(set(re.findall(pat, text, flags=re.I)))
                    for val in vals[:200]:
                        if any(k in val.lower() for k in ["pdf", "download", "report", "file", "view", "image", "api"]):
                            print("ASSET", val[:1000])
                soup = BeautifulSoup(text, "html.parser")
                for tag in soup.find_all(["script", "a", "img"]):
                    for attr in ["src", "href", "data-src", "data-url"]:
                        raw = tag.get(attr)
                        if raw:
                            absolute = urljoin(r.url, raw)
                            if any(k in absolute.lower() for k in ["pdf", "download", "report", "view", "api", "image"]):
                                print("TAG", tag.name, attr, absolute)
        except Exception as e:
            print("FETCH_ERROR", url, repr(e))

    # Probe public image pages. We probe multiple common image suffixes and dates.
    found = []
    for page in range(1, 45):
        urls = [
            f"https://public.fxbaogao.com/report-image/{item['date']}/{rid}-{page}.png",
            f"https://public.fxbaogao.com/report-image/{item['date']}/{rid}-{page}.jpg",
            f"https://public.fxbaogao.com/report-image/{item['date']}/{rid}_{page}.png",
        ]
        ok = None
        for url in urls:
            try:
                r = S.get(url, timeout=20, allow_redirects=True)
                ctype = (r.headers.get("content-type") or "").lower()
                if r.status_code == 200 and ("image" in ctype or r.content[:8] == b"\x89PNG\r\n\x1a\n") and len(r.content) > 1000:
                    ok = {"page": page, "url": r.url, "type": ctype, "bytes": len(r.content), "head": r.content[:12].hex()}
                    break
            except Exception:
                pass
        if ok:
            found.append(ok)
        elif page > 3 and not found:
            break
        elif found and page > found[-1]["page"] + 3:
            break
    print("IMAGE_PAGES", json.dumps(found, ensure_ascii=False))
