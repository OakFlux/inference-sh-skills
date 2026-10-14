#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json, requests
RID=1859436
U='https://api.fxbaogao.com/mofoun/report/searchReport/detail'
H={'User-Agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/155 Safari/537.36','Accept':'application/json,text/plain,*/*','Origin':'https://www.fxbaogao.com','Referer':f'https://www.fxbaogao.com/view?id={RID}'}
S=requests.Session();S.headers.update(H)
variants=[
 ('json',{'id':RID}),('json',{'reportId':RID}),('json',{'id':str(RID)}),('json',{'reportId':str(RID)}),
 ('form',{'id':RID}),('form',{'reportId':RID}),('form',{'id':str(RID)}),('form',{'reportId':str(RID)}),
]
for kind,payload in variants:
 try:
  kwargs={'timeout':12,'allow_redirects':True}
  if kind=='json': kwargs['json']=payload
  else: kwargs['data']=payload
  r=S.post(U,**kwargs)
  print(kind,payload,'STATUS',r.status_code,'TYPE',r.headers.get('content-type'),'BYTES',len(r.content),'HEAD',r.text[:10000].replace('\n',' '))
 except Exception as e: print(kind,payload,'ERR',type(e).__name__,str(e)[:300])
