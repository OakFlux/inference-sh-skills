#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import requests

reports = [
    ("1859436", "2019/12/15"),
    ("2156162", "2020/09/06"),
    ("244900", "2018/06/14"),
    ("15112", "2018/05/02"),
]
H = {"User-Agent":"Mozilla/5.0", "Referer":"https://www.fxbaogao.com/"}
S = requests.Session(); S.headers.update(H)
for rid, date in reports:
    print("REPORT", rid, date)
    for base in ["https://public.fxbaogao.com/report-image", "http://public.fxbaogao.com/report-image"]:
        found=[]
        for p in range(1, 31):
            u=f"{base}/{date}/{rid}-{p}.png"
            try:
                r=S.get(u,timeout=8,allow_redirects=True)
                ok=r.status_code==200 and len(r.content)>1000 and (r.content[:8]==b'\x89PNG\r\n\x1a\n' or 'image' in (r.headers.get('content-type') or ''))
                if ok:
                    found.append({"p":p,"bytes":len(r.content),"url":r.url})
                elif p>=5 and not found:
                    break
                elif found and p>found[-1]["p"]+2:
                    break
            except Exception as e:
                print("ERR",p,type(e).__name__)
                break
        print("BASE",base,"FOUND",json.dumps(found,ensure_ascii=False))
