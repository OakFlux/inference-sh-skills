#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json,re
from urllib.parse import urljoin
from pathlib import Path
import requests
from bs4 import BeautifulSoup

BASE='https://www.cmbi.com.hk'
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36'
s=requests.Session(); s.headers.update({'User-Agent':UA,'Accept-Language':'en-US,en;q=0.9,zh-CN;q=0.7'})
results=[]
for page in range(385,396):
    for lang in ('en','tc','cn'):
        url=f'{BASE}/market-stockreview?lang={lang}&page={page}'
        r=s.get(url,timeout=(20,120)); print('PAGE',page,lang,r.status_code,len(r.content),r.url,flush=True)
        soup=BeautifulSoup(r.text,'html.parser')
        for a in soup.find_all('a',href=True):
            label=' '.join(a.get_text(' ',strip=True).split())
            href=urljoin(r.url,a['href'])
            hay=(label+' '+href).lower()
            if any(k in hay for k in ('ming yuan','mingyuan','明源云','明源雲','909 hk','0909 hk')):
                rec={'page':page,'lang':lang,'label':label,'href':href}
                if rec not in results:
                    results.append(rec); print('MATCH',json.dumps(rec,ensure_ascii=False),flush=True)
Path('mingyuan-page390.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print('TOTAL',len(results),flush=True)
