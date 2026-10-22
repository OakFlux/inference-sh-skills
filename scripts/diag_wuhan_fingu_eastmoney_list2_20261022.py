#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import json, time
from pathlib import Path
import requests

OUT=Path('diag_wuhan_fingu_eastmoney_list2'); OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session(); s.trust_env=False
s.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/155 Safari/537.36','Accept':'application/json,text/plain,*/*','Referer':'https://data.eastmoney.com/report/stock.jshtml'})
endpoint='https://reportapi.eastmoney.com/report/list2'
bodies=[
 {'pageSize':200,'pageNo':1,'p':1,'pageNum':1,'pageNumber':1,'beginTime':'2000-01-01','endTime':'2026-10-22','code':'002194','industryCode':'*','rating':None,'ratingChange':None,'orgCode':None,'rcode':''},
 {'pageSize':200,'pageNo':1,'beginTime':'2000-01-01','endTime':'2026-10-22','code':'002194'},
 {'pageSize':200,'pageNo':1,'beginTime':'2000-01-01','endTime':'2026-10-22','stockCode':'002194'},
]
records=[]
for i,body in enumerate(bodies,1):
 rec={'body':body}
 try:
  r=s.post(endpoint,json=body,headers={'Content-Type':'application/json'},timeout=(20,180))
  rec.update({'status':r.status_code,'url':r.url,'content_type':r.headers.get('content-type'),'bytes':len(r.content),'text_head':r.text[:1000]})
  try: rec['json']=r.json()
  except Exception as e: rec['json_error']=repr(e)
  (OUT/f'response_{i}.txt').write_bytes(r.content)
  print('RESPONSE',i,json.dumps(rec,ensure_ascii=False)[:20000],flush=True)
  r.close()
 except Exception as e:
  rec['error']=repr(e); print('ERROR',i,repr(e),flush=True)
 records.append(rec)
 time.sleep(1)
(OUT/'summary.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
