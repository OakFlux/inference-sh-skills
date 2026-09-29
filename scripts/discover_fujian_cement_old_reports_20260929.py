from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin
import requests

s = requests.Session()
s.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://data.eastmoney.com/'})
url='https://data.eastmoney.com/stockcalendar/600802.html'
r=s.get(url,timeout=60)
print('PAGE',r.status_code,len(r.content),r.url,r.headers.get('content-type'),flush=True)
text=r.text

patterns = ['区域整合的领头羊','供需失衡致半年亏损']
for pat in patterns:
    pos=text.find(pat)
    print('PAGE_FIND',pat,pos,flush=True)
    if pos >= 0:
        snippet=text[max(0,pos-3500):pos+3500]
        print('\n=== TITLE_SNIPPET',pat,'===\n',snippet,'\n=== END_SNIPPET ===',flush=True)
        for rx in [
            r'INFO_CODE[\\\"\':= ]+([A-Za-z0-9_\-]+)',
            r'infoCode[\\\"\':= ]+([A-Za-z0-9_\-]+)',
            r'AP\d{15,}',
            r'INFOCODE[^A-Za-z0-9]+([A-Za-z0-9_\-]+)',
        ]:
            print('REGEX',rx,re.findall(rx,snippet,re.I)[:20],flush=True)

# Locate and decode the embedded page-data object if possible.
for marker in ['var pagedata =', 'pagedata =', 'window.pagedata']:
    pos=text.find(marker)
    print('PAGEDATA_MARKER',marker,pos,flush=True)
    if pos >= 0:
        print(text[pos:pos+2500],flush=True)

# Generic extraction of all research-report event objects near the embedded data.
# The page contains JSON-like data; scan bounded objects that include EVENT_TYPE_CODE 020.
objects=[]
for match in re.finditer(r'\{[^{}]{0,6000}?EVENT_TYPE_CODE[^{}]{0,6000}?\}', text, re.S):
    block=html.unescape(match.group(0))
    if re.search(r'EVENT_TYPE_CODE\\?"?\s*:\s*\\?"?020',block):
        objects.append(block)
print('RESEARCH_EVENT_BLOCKS',len(objects),flush=True)
for block in objects:
    if '600802' in block or '福建水泥' in block:
        print('RESEARCH_BLOCK',block[:7000],flush=True)

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
            for key in ['pagedata','sjyl','EVENT_TYPE_CODE','stockcalendar','reportName','研报','RPT','calendar','datacenter-web','api/data']:
                start=0
                count=0
                low=body.lower(); target=key.lower()
                while True:
                    pos=low.find(target,start)
                    if pos<0 or count>=12: break
                    print('CTX',key,pos,body[max(0,pos-350):pos+700].replace('\n',' ')[:1100],flush=True)
                    start=pos+len(target); count+=1
    except Exception as exc:
        print('SCRIPT_ERR',full,repr(exc),flush=True)
