from __future__ import annotations

import re
import requests

url='https://data.eastmoney.com/newstatic/js/report/zw_macresearch.js'
r=requests.get(url,timeout=(20,120),headers={'User-Agent':'Mozilla/5.0','Referer':'https://data.eastmoney.com/report/info/AP201210260005551948.html'})
print('HTTP',r.status_code,len(r.content),r.url,flush=True)
r.raise_for_status()
text=r.text
terms=['pdf-link','ctx-content','attach_pages','page_size','info_code','notice_content','pdfUrl','pdfurl','report/content','report/detail','getContent','zwinfo.','attachPages','encodeUrl']
for term in terms:
    positions=[m.start() for m in re.finditer(re.escape(term),text,re.I)]
    print('TERM',term,'COUNT',len(positions),'POSITIONS',positions[:100],flush=True)
    for idx,pos in enumerate(positions[:20]):
        print('CONTEXT',term,idx,text[max(0,pos-1200):pos+2500],flush=True)
