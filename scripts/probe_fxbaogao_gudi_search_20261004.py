from __future__ import annotations

import re
import json
from urllib.parse import quote, urljoin
import requests

s=requests.Session()
s.headers.update({'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36','Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8'})
urls=[
    'https://www.fxbaogao.com/search?keyword='+quote('顾地科技'),
    'https://www.fxbaogao.com/search?q='+quote('顾地科技'),
    'https://www.fxbaogao.com/search/'+quote('顾地科技'),
    'https://www.fxbaogao.com/?s='+quote('顾地科技'),
    'https://fxbaogao.com/search?keyword='+quote('顾地科技'),
    'https://fxbaogao.com/search?q='+quote('顾地科技'),
]
for url in urls:
    try:
        r=s.get(url,timeout=(20,120),allow_redirects=True)
        print('URL',url,'HTTP',r.status_code,r.headers.get('content-type'),len(r.content),r.url,flush=True)
        print('HEAD',repr(r.content[:200]),flush=True)
        text=r.text
        for pat in ('顾地科技','布局完善','国内大型综合','AP201210260005551948','AP201208060005410276'):
            print('FIND',pat,text.find(pat),flush=True)
        links=[]
        for href,body in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',text,re.I|re.S):
            clean=re.sub(r'<[^>]+>','',body)
            if any(x in clean or x in href for x in ('顾地','002694','布局完善','塑料管道')):
                links.append((urljoin(r.url,href),re.sub(r'\s+',' ',clean).strip()))
        print('LINKS',json.dumps(links[:100],ensure_ascii=False),flush=True)
        # print script endpoints and snippets mentioning search/api
        for src in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']',text,re.I):
            print('SCRIPT',urljoin(r.url,src),flush=True)
    except Exception as exc:
        print('ERROR',url,repr(exc),flush=True)
