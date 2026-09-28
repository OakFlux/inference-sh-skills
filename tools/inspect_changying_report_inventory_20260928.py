from __future__ import annotations
import json,re,requests

API='https://reportapi.eastmoney.com/report/list'
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36','Accept-Language':'zh-CN,zh;q=0.9,en;q=0.7'}

def parse(text):
 s=text.strip()
 if s.startswith('{'): return json.loads(s)
 m=re.search(r'^[^(]+\((.*)\)\s*;?\s*$',s,re.S)
 return json.loads(m.group(1)) if m else {}

s=requests.Session();s.headers.update(HEADERS)
rows=[]
for year in range(2018,2027):
 p={'cb':'datatable','pageSize':'200','pageNo':'1','qType':'0','orgCode':'','code':'300115','industryCode':'','industry':'','rating':'','ratingchange':'','beginTime':f'{year}-01-01','endTime':f'{year}-12-31','fields':'','p':'1','pageNum':'1','pageNumber':'1'}
 r=s.get(API,params=p,timeout=120);r.raise_for_status();d=parse(r.text)
 arr=d.get('data') or d.get('result') or []
 if isinstance(arr,dict): arr=arr.get('data') or arr.get('list') or arr.get('rows') or []
 print('YEAR',year,'COUNT',len(arr),flush=True)
 for x in arr:
  rec={'year':year,'infoCode':x.get('infoCode'),'title':x.get('title'),'publishDate':x.get('publishDate'),'org':x.get('orgSName') or x.get('orgName'),'researcher':x.get('researcher'),'rating':x.get('emRatingName') or x.get('ratingName')}
  print('ROW',json.dumps(rec,ensure_ascii=False),flush=True);rows.append(rec)
open('changying_report_inventory.json','w',encoding='utf-8').write(json.dumps(rows,ensure_ascii=False,indent=2))
