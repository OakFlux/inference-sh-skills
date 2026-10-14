#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import requests
from bs4 import BeautifulSoup

H = {"User-Agent": "Mozilla/5.0", "Accept-Language": "zh-CN,zh;q=0.9"}
S = requests.Session(); S.headers.update(H)

for i in range(1, 31):
    url = f"https://webf10.gw.com.cn/SZ/B{i}/SZ002395_B{i}.html"
    try:
        r = S.get(url, timeout=45)
        if r.status_code != 200 or len(r.content) < 300:
            print(i, r.status_code, len(r.content), "SKIP")
            continue
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        flags = []
        for kw in ["投资研究", "研究报告", "券商", "目标价", "评级", "国联证券", "东兴证券", "华泰证券", "光大证券"]:
            if kw in text:
                flags.append(kw)
        print("SECTION", i, "STATUS", r.status_code, "BYTES", len(r.content), "TITLE", repr(title), "FLAGS", flags, "TEXT", text[:500])
    except Exception as e:
        print("SECTION", i, "ERROR", repr(e))
