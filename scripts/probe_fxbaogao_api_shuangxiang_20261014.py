#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import json, requests

IDS=['1859436','2156162','244900','15112']
BASES=['https://api.fxbaogao.com','https://api.fxbaogao.com/mofoun']
PATHS=[
 '/report/searchReport/detail',
 '/report/searchReportData/detail',
 '/report/report/getReportPreviewImages',
 '/report/report/report/preDownV2',
 '/report/report/file/downloadReport',
 '/report/report/downloadReportByBean',
]
H={'User-Agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/155 Safari/537.36','Accept':'application/json,text/plain,*/*','Origin':'https://www.fxbaogao.com','Referer':'https://www.fxbaogao.com/'}
S=requests.Session();S.headers.update(H)
for rid in IDS:
 print('\n### RID',rid)
 for base in BASES:
  for path in PATHS:
   for method in ['GET','POST']:
    try:
     kwargs={'timeout':20,'allow_redirects':True}
     if method=='GET': kwargs['params']={'id':rid,'reportId':rid}
     else:
      kwargs['json']={'id':int(rid),'reportId':int(rid)}
     r=S.request(method,base+path,**kwargs)
     ct=r.headers.get('content-type') or ''
     body=r.content
     head=(r.text[:1800] if 'text' in ct or 'json' in ct else body[:80].hex()).replace('\n',' ')
     print(method,base+path,'STATUS',r.status_code,'TYPE',ct,'BYTES',len(body),'FINAL',r.url,'HEAD',head)
    except Exception as e:
     print(method,base+path,'ERR',type(e).__name__,str(e)[:250])
