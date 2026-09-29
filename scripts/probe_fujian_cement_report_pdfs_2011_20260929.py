from __future__ import annotations
import re, requests
from pypdf import PdfReader
from io import BytesIO
s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://data.eastmoney.com/'})
for code in ['AP201203080005024676','AP201203080005024552']:
    print('\n===',code,'===',flush=True)
    r=s.get(f'https://data.eastmoney.com/report/info/{code}.html',timeout=(15,60))
    print('DETAIL',r.status_code,len(r.content),r.url,flush=True)
    title=re.search(r'<h1[^>]*>(.*?)</h1>',r.text,re.S)
    print('TITLE',re.sub(r'<[^>]+>','',title.group(1)).strip() if title else '',flush=True)
    spans=[re.sub(r'<[^>]+>','',x).strip() for x in re.findall(r'<span[^>]*>(.*?)</span>',r.text,re.S)]
    print('SPANS',[x for x in spans if x][:20],flush=True)
    rr=s.get(f'https://pdf.dfcfw.com/pdf/H3_{code}_1.pdf',timeout=(15,60))
    pages=len(PdfReader(BytesIO(rr.content),strict=False).pages) if rr.status_code==200 and rr.content.startswith(b'%PDF') else None
    print('PDF',rr.status_code,rr.headers.get('content-type'),len(rr.content),rr.content[:8],'pages',pages,flush=True)
