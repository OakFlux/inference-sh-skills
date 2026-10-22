#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import json, time
from pathlib import Path
import requests

OUT=Path('find_wuhan_fingu_apids'); OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session(); s.trust_env=False
s.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/155 Safari/537.36','Accept':'application/json,text/plain,*/*','Accept-Language':'zh-CN,zh;q=0.9','Referer':'https://data.eastmoney.com/report/stock.jshtml'})
ENDPOINT='https://reportapi.eastmoney.com/report/list2'
WINDOWS=[
 ('2020-08-09','2020-08-12','haitong_2020'),
 ('2020-11-02','2020-11-04','eastmoney_2020'),
 ('2019-04-02','2019-04-04','caitong_2019'),
 ('2019-10-23','2019-10-29','reports_2019_oct'),
 ('2014-06-02','2014-06-04','cmb_2014'),
 ('2014-02-16','2014-02-18','huachuang_2014'),
 ('2012-06-20','2012-06-22','pingan_2012'),
]

def req(body):
 errs=[]
 for a in range(1,6):
  try:
   r=s.post(ENDPOINT,json=body,headers={'Content-Type':'application/json'},timeout=(20,180))
   print('HTTP',r.status_code,'attempt',a,'bytes',len(r.content),'body',body,flush=True)
   r.raise_for_status(); return r
  except Exception as e:
   errs.append(repr(e)); time.sleep(a*2)
 raise RuntimeError(errs)

all_matches=[]; summaries=[]
for begin,end,label in WINDOWS:
 matches=[]; page=1; total=1
 while page<=total and page<=100:
  body={'pageSize':100,'pageNo':page,'p':page,'pageNum':page,'pageNumber':page,'beginTime':begin,'endTime':end,'industryCode':'*','rating':None,'ratingChange':None,'orgCode':None,'rcode':''}
  r=req(body)
  try: p=r.json()
  finally: r.close()
  total=int(p.get('TotalPage') or p.get('totalPage') or 1)
  data=p.get('data') or []
  print('PAGE',label,page,'total',total,'rows',len(data),flush=True)
  for row in data:
   if not isinstance(row,dict): continue
   code=str(row.get('stockCode') or '')
   title=str(row.get('title') or '')
   name=str(row.get('stockName') or '')
   if code=='002194' or '武汉凡谷' in title or '武汉凡谷' in name or '*ST凡谷' in title or 'ST凡谷' in name:
    compact={k:row.get(k) for k in ['title','stockName','stockCode','orgName','orgSName','publishDate','infoCode','reportType','researcher','emRatingName','sRatingName','attachSize','attachPages','encodeUrl','market']}
    compact['window']=label
    matches.append(compact); all_matches.append(compact)
    print('MATCH',json.dumps(compact,ensure_ascii=False),flush=True)
  page+=1
 summaries.append({'label':label,'begin':begin,'end':end,'pages_scanned':page-1,'total_pages':total,'matches':matches})
 (OUT/f'{label}.json').write_text(json.dumps(matches,ensure_ascii=False,indent=2),encoding='utf-8')
print('ALL_MATCHES',json.dumps(all_matches,ensure_ascii=False,indent=2),flush=True)
(OUT/'summary.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding='utf-8')
