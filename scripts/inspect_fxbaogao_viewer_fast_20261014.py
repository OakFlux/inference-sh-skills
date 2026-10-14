#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re, json, requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup

RID='1859436'
H={'User-Agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/155 Safari/537.36','Accept-Language':'zh-CN,zh;q=0.9'}
S=requests.Session();S.headers.update(H)
for u in [f'https://www.fxbaogao.com/detail/{RID}',f'https://www.fxbaogao.com/view?id={RID}']:
 try:
  r=S.get(u,timeout=20,allow_redirects=True)
  print('\nPAGE',u,r.status_code,r.headers.get('content-type'),len(r.content),r.url)
  if not r.ok: continue
  r.encoding='utf-8'; t=r.text
  print('HEAD',re.sub(r'\s+',' ',t[:4000]))
  soup=BeautifulSoup(t,'html.parser')
  scripts=[]
  for x in soup.find_all('script',src=True):
   a=urljoin(r.url,x.get('src')); scripts.append(a); print('SCRIPT_SRC',a)
  for key in ['report-image','download','pdf','api/','reportId','pageCount','pageNum','fileUrl','oss','public.fxbaogao']:
   if key.lower() in t.lower():
    print('HTML_KEY',key)
  for m in sorted(set(re.findall(r'https?://[^"\'<> ]+',t,re.I))): print('HTML_URL',m[:1500])
  # only fetch same-host app chunks
  for s in scripts:
   if 'www.fxbaogao.com/_fxbg/' not in s: continue
   try:
    q=S.get(s,timeout=25,headers={**H,'Referer':r.url})
    print('JS',s,q.status_code,len(q.content),q.headers.get('content-type'))
    if not q.ok: continue
    z=q.text
    hits=[]
    for pat in [r'https?://[^"\'` ]+',r'/(?:api|report|download|file|view|user|auth)[A-Za-z0-9_?&=./{}:-]*',r'[A-Za-z0-9_./-]*(?:report-image|download|fileUrl|pdfUrl|pageCount|reportId)[A-Za-z0-9_?&=./{}:-]*']:
     hits += re.findall(pat,z,re.I)
    for h in sorted(set(hits)):
     if len(h)>2: print('JS_HIT',h[:2000])
   except Exception as e: print('JS_ERR',s,type(e).__name__,str(e)[:200])
 except Exception as e: print('PAGE_ERR',u,type(e).__name__,str(e)[:300])
