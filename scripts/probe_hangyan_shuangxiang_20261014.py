#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re, json, requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup

urls=[
 "https://www.hangyan.co/reports/2530133840773514831",
 "https://www.hangyan.co/reports/2530133840773514831/",
]
H={"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/155 Safari/537.36","Accept-Language":"zh-CN,zh;q=0.9"}
S=requests.Session();S.headers.update(H)
for u in urls:
 try:
  r=S.get(u,timeout=60,allow_redirects=True)
  print("URL",u,"STATUS",r.status_code,"TYPE",r.headers.get("content-type"),"BYTES",len(r.content),"FINAL",r.url)
  r.raise_for_status(); r.encoding=r.apparent_encoding
  t=r.text
  print("HEAD",re.sub(r"\s+"," ",t[:3000]))
  for pattern in [r'https?://[^"\'<> ]+',r'[^"\'<> ]+\.pdf[^"\'<> ]*',r'/(?:api|download|file|report)[^"\'<> ]*']:
   for x in sorted(set(re.findall(pattern,t,re.I))):
    if any(k in x.lower() for k in ["pdf","download","file","report","api","oss","cos","storage"]): print("MATCH",x[:2000])
  soup=BeautifulSoup(t,"html.parser")
  for tag in soup.find_all(["script","a","iframe","embed","object","source"]):
   for attr in ["src","href","data-src","data-url","value"]:
    x=tag.get(attr)
    if x:
     a=urljoin(r.url,x)
     if any(k in a.lower() for k in ["pdf","download","report","api","file","oss","cos"]): print("TAG",tag.name,attr,a)
  for s in soup.find_all("script"):
   txt=s.string or s.get_text() or ""
   if any(k in txt.lower() for k in ["pdf","download","fileurl","reporturl","2530133840773514831"]):
    print("SCRIPT",txt[:20000])
 except Exception as e: print("ERR",repr(e))
