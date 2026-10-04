from __future__ import annotations
import json,re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

LIST_URL='https://q.stock.sohu.com/cn/300817/gsgg_1.shtml'
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36','Accept-Language':'zh-CN,zh;q=0.9,en;q=0.7'}
s=requests.Session();s.headers.update(HEADERS)
records=[]
r=s.get(LIST_URL,timeout=120); print('LIST',r.status_code,len(r.content),r.url,r.apparent_encoding,flush=True)
r.encoding=r.apparent_encoding or 'gb18030'
soup=BeautifulSoup(r.text,'html.parser')
for a in soup.find_all('a',href=True):
    text=' '.join(a.get_text(' ',strip=True).split())
    if '招股说明书' in text or ('双飞股份' in text and '首次公开发行' in text):
        url=urljoin(r.url,a['href'])
        item={'text':text,'url':url}
        records.append(item); print('MATCH',json.dumps(item,ensure_ascii=False),flush=True)
        try:
            q=s.get(url,timeout=120); q.encoding=q.apparent_encoding or 'gb18030'
            print('DETAIL',q.status_code,len(q.content),q.url,q.apparent_encoding,flush=True)
            sp=BeautifulSoup(q.text,'html.parser')
            links=[]
            for b in sp.find_all('a',href=True):
                t=' '.join(b.get_text(' ',strip=True).split())
                u=urljoin(q.url,b['href'])
                if any(k in (t+' '+u).lower() for k in ('pdf','公告原文','招股说明书','download','cninfo','static')):
                    links.append({'text':t,'url':u})
            texts=' '.join(sp.get_text(' ',strip=True).split())
            rec={'detail_url':q.url,'title':sp.title.get_text(' ',strip=True) if sp.title else '', 'links':links, 'excerpts':[]}
            for token in ['PDF','公告原文','cninfo','static.cninfo','adjunctUrl']:
                for m in re.finditer(re.escape(token),q.text,re.I):
                    rec['excerpts'].append(q.text[max(0,m.start()-500):m.start()+1200])
                    if len(rec['excerpts'])>=20: break
            item['detail']=rec
            print('LINKS',json.dumps(links,ensure_ascii=False),flush=True)
            for x in rec['excerpts'][:20]: print('EXCERPT',json.dumps(x,ensure_ascii=False),flush=True)
        except Exception as e:
            item['error']=repr(e);print('ERROR',repr(e),flush=True)
open('shuangfei_sohu_prospectus.json','w',encoding='utf-8').write(json.dumps(records,ensure_ascii=False,indent=2))
