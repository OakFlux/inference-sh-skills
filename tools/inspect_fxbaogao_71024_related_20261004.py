import json,re,requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

url='https://www.fxbaogao.com/detail/71024'
r=requests.get(url,headers={'User-Agent':'Mozilla/5.0 Chrome/152.0.0.0','Accept-Language':'zh-CN,zh;q=0.9'},timeout=90)
r.raise_for_status()
s=BeautifulSoup(r.text,'html.parser')
rows=[]
for a in s.find_all('a',href=True):
    href=urljoin(r.url,a['href'])
    txt=' '.join(a.get_text(' ',strip=True).split())
    if '/detail/' in href:
        rows.append({'url':href,'text':txt})
print(json.dumps(rows,ensure_ascii=False,indent=2),flush=True)
open('fxbaogao_71024_related.json','w',encoding='utf-8').write(json.dumps(rows,ensure_ascii=False,indent=2))
