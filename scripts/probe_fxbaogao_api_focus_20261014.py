#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import requests, json
RID='1859436'
H={'User-Agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/155 Safari/537.36','Accept':'application/json,text/plain,*/*','Origin':'https://www.fxbaogao.com','Referer':f'https://www.fxbaogao.com/view?id={RID}','Content-Type':'application/json;charset=UTF-8'}
S=requests.Session();S.headers.update(H)
urls=[
 f'https://api.fxbaogao.com/report/searchReport/detail?id={RID}',
 f'https://api.fxbaogao.com/mofoun/report/searchReport/detail?id={RID}',
 f'https://api.fxbaogao.com/report/searchReportData/detail?id={RID}',
 f'https://api.fxbaogao.com/mofoun/report/searchReportData/detail?id={RID}',
 f'https://api.fxbaogao.com/report/report/getReportPreviewImages?reportId={RID}',
 f'https://api.fxbaogao.com/mofoun/report/report/getReportPreviewImages?reportId={RID}',
 f'https://api.fxbaogao.com/report/report/report/preDownV2?reportId={RID}',
 f'https://api.fxbaogao.com/mofoun/report/report/report/preDownV2?reportId={RID}',
 f'https://api.fxbaogao.com/report/report/file/downloadReport?reportId={RID}',
 f'https://api.fxbaogao.com/mofoun/report/report/file/downloadReport?reportId={RID}',
]
for u in urls:
 try:
  r=S.get(u,timeout=8,allow_redirects=True)
  ct=r.headers.get('content-type') or ''
  head=(r.text[:5000] if ('json' in ct or 'text' in ct) else r.content[:100].hex()).replace('\n',' ')
  print('GET',u,'STATUS',r.status_code,'TYPE',ct,'BYTES',len(r.content),'FINAL',r.url,'HEAD',head)
 except Exception as e: print('GET',u,'ERR',type(e).__name__,str(e)[:250])
