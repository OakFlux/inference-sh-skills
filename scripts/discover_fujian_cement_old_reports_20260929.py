from __future__ import annotations

import re
from urllib.parse import urljoin
import requests

s = requests.Session()
s.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://data.eastmoney.com/'})
url='https://data.eastmoney.com/stockcalendar/600802.html'
r=s.get(url,timeout=60)
print('PAGE',r.status_code,len(r.content),r.url,r.headers.get('content-type'),flush=True)
text=r.text
for pat in ['区域整合的领头羊','供需失衡致半年亏损','stockcalendar','reportName','研报']:
    print('PAGE_FIND',pat,text.find(pat),flush=True)

scripts=re.findall(r'<script[^>]+src=["\']([^"\']+)',text,re.I)
print('SCRIPTS',len(scripts),flush=True)
for src in scripts:
    full=urljoin(r.url,src)
    print('SCRIPT',full,flush=True)

for src in scripts:
    full=urljoin(r.url,src)
    try:
        rr=s.get(full,timeout=60)
        body=rr.text
        interesting=any(k.lower() in body.lower() for k in ['stockcalendar','reportname','研报','calendar'])
        if interesting:
            print('\n=== INTERESTING',full,rr.status_code,len(body),'===',flush=True)
            for key in ['stockcalendar','reportName','研报','RPT','calendar','datacenter-web','api/data']:
                start=0
                count=0
                low=body.lower(); target=key.lower()
                while True:
                    pos=low.find(target,start)
                    if pos<0 or count>=20: break
                    print('CTX',key,pos,body[max(0,pos-250):pos+500].replace('\n',' ')[:800],flush=True)
                    start=pos+len(target); count+=1
    except Exception as exc:
        print('SCRIPT_ERR',full,repr(exc),flush=True)
