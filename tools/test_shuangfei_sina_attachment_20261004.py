from __future__ import annotations
import re, json
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

headers={
 'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36',
 'Accept-Language':'zh-CN,zh;q=0.9,en;q=0.7',
}
page='https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=5885348&stockid=300817'
candidates=[
 'http://file.finance.sina.com.cn/211.154.219.97:9494/MRGG/CNSESH_STOCK/2020/2020-2/2020-02-05/5885348.PDF',
 'https://file.finance.sina.com.cn/211.154.219.97:9494/MRGG/CNSESH_STOCK/2020/2020-2/2020-02-05/5885348.PDF',
 'http://file.finance.sina.com.cn/211.154.219.97:9494/MRGG/CNSESH_STOCK/2020/2020-02/2020-02-05/5885348.PDF',
]
s=requests.Session();s.headers.update(headers)
r=s.get(page,timeout=120,allow_redirects=True)
print('PAGE',r.status_code,len(r.content),r.url,r.apparent_encoding,flush=True)
r.encoding=r.apparent_encoding or 'gb18030'
print('PREFIX',r.text[:1000],flush=True)
sp=BeautifulSoup(r.text,'html.parser')
for a in sp.find_all('a',href=True):
    t=' '.join(a.get_text(' ',strip=True).split());u=urljoin(r.url,a['href'])
    if any(k in (t+' '+u).lower() for k in ('pdf','附件','公告原文','download','file.finance')):
        print('PAGE_LINK',json.dumps({'text':t,'url':u},ensure_ascii=False),flush=True)
        candidates.append(u)
for m in re.finditer(r'https?[^\"\'<> ]+\.PDF',r.text,re.I):
    u=m.group(0).replace('&amp;','&'); print('REGEX_PDF',u,flush=True);candidates.append(u)
seen=set()
for u in candidates:
    if not u or u in seen:continue
    seen.add(u)
    try:
        q=s.get(u,timeout=180,allow_redirects=True,headers={**headers,'Referer':page})
        print('CANDIDATE',json.dumps({'url':u,'status':q.status_code,'final':q.url,'bytes':len(q.content),'content_type':q.headers.get('content-type'),'prefix':q.content[:8].hex()},ensure_ascii=False),flush=True)
    except Exception as e:print('ERROR',u,repr(e),flush=True)
