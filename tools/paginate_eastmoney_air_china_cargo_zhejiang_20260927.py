from __future__ import annotations

import json,re
from pathlib import Path
from typing import Any
import requests

OUT=Path('eastmoney_air_china_cargo_paginated.json')
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36','Referer':'https://data.eastmoney.com/report/stock.jshtml','Accept':'application/json,text/plain,*/*'}

def dec(t:str)->Any:
 t=t.strip().lstrip('\ufeff')
 try:return json.loads(t)
 except:
  m=re.match(r'^[^(]+\((.*)\)\s*;?$',t,re.S)
  if not m:raise
  return json.loads(m.group(1))

def main():
 s=requests.Session();s.headers.update(HEADERS)
 allrows=[]; meta=[]
 for qtype in (0,1,2):
  for page in range(1,8):
   params={'cb':'datatable123456','industryCode':'*','pageSize':'100','industry':'*','rating':'*','ratingChange':'*','beginTime':'2025-12-20','endTime':'2026-01-10','pageNo':str(page),'fields':'','qType':str(qtype),'orgCode':'','code':'','rcode':'','p':str(page),'pageNum':str(page),'pageNumber':str(page)}
   r=s.get('https://reportapi.eastmoney.com/report/list',params=params,timeout=120)
   p=dec(r.text); rows=p.get('data',[]) if isinstance(p,dict) else []
   meta.append({'qtype':qtype,'page':page,'status':r.status_code,'bytes':len(r.content),'hits':p.get('hits') if isinstance(p,dict) else None,'count':len(rows)})
   print('PAGE',json.dumps(meta[-1],ensure_ascii=False),flush=True)
   if not rows:break
   for x in rows:
    blob=json.dumps(x,ensure_ascii=False)
    if any(t in blob for t in ('国货航','001391','跨境电商方兴未艾','航空货运龙头顺势而为','李丹','李逸')):
     print('MATCH',json.dumps(x,ensure_ascii=False),flush=True)
     allrows.append(x)
   if len(rows)<100:break
 OUT.write_text(json.dumps({'meta':meta,'matches':allrows},ensure_ascii=False,indent=2),encoding='utf-8')
 print('DONE matches',len(allrows),flush=True)

if __name__=='__main__':main()
