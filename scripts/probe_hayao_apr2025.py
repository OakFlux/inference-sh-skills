import json, time
from pathlib import Path
import requests

api='https://reportapi.eastmoney.com/report/list'
s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://data.eastmoney.com/'})
out=[]
for qtype in (0,1,2):
  page=1; total=1
  while page<=total:
    params={'industryCode':'*','pageSize':'100','industry':'*','rating':'*','ratingChange':'*','beginTime':'2025-04-24','endTime':'2025-04-27','pageNo':str(page),'fields':'','qType':str(qtype),'orgCode':'','code':'','rcode':'','p':str(page),'pageNum':str(page),'pageNumber':str(page)}
    r=s.get(api,params=params,timeout=180); print('Q',qtype,page,r.status_code,len(r.content),flush=True); r.raise_for_status()
    d=r.json(); total=int(d.get('TotalPage') or 1)
    for x in d.get('data') or []:
      h=' '.join(str(x.get(k) or '') for k in ('title','stockName','stockCode','orgName','orgSName'))
      if '哈药股份' in h or '600664' in h or '新班子' in h:
        out.append(x); print('MATCH',json.dumps(x,ensure_ascii=False,default=str),flush=True)
    page+=1; time.sleep(.1)
for x in out:
  info=str(x.get('infoCode') or '')
  for v in (1,2,3):
    u=f'https://pdf.dfcfw.com/pdf/H3_{info}_{v}.pdf'
    p=s.get(u,headers={'User-Agent':'Mozilla/5.0','Referer':'https://data.eastmoney.com/report/'},timeout=300)
    ok=p.status_code==200 and p.content.startswith(b'%PDF-')
    print('PDF',info,v,p.status_code,len(p.content),ok,flush=True)
    if ok:
      Path('hayao-apr2025-pdfs').mkdir(exist_ok=True)
      Path(f'hayao-apr2025-pdfs/{info}_{v}.pdf').write_bytes(p.content); break
Path('hayao-apr2025.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
