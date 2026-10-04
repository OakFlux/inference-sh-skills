from __future__ import annotations

import re
import requests

url = 'https://www.sdyanbao.com/detail/839553'
s = requests.Session()
s.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://www.sdyanbao.com/'})
r = s.get(url, timeout=(20,90), allow_redirects=True)
print('PAGE', r.status_code, r.headers.get('content-type'), len(r.content), r.url, flush=True)
text = r.text
for key in ['pdf','download','下载','839553','file','preview','oss','cos','cdn']:
    print('\nKEY', key, 'COUNT', text.lower().count(key.lower()), flush=True)
    start=0
    lower=text.lower(); target=key.lower(); count=0
    while count<20:
        pos=lower.find(target,start)
        if pos<0: break
        print('CTX',pos,text[max(0,pos-500):pos+1200].replace('\n',' ')[:1700],flush=True)
        start=pos+len(target); count+=1

urls=sorted(set(re.findall(r'https?://[^"\'<>\s]+',text)))
print('\nURL_COUNT',len(urls),flush=True)
for u in urls:
    if any(k in u.lower() for k in ['pdf','download','file','oss','cos','cdn','839553']):
        print('URL',u[:2000],flush=True)

scripts=re.findall(r'<script[^>]+src=["\']([^"\']+)',text,re.I)
print('SCRIPTS',len(scripts),flush=True)
for src in scripts:
    print('SCRIPT',src,flush=True)
