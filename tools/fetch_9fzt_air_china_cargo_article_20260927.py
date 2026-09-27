from pathlib import Path
import json,re,requests
from bs4 import BeautifulSoup

URL='https://www.9fzt.com/detail/sz_001391_10_820515916583.html'
headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36','Accept-Language':'zh-CN,zh;q=0.9,en;q=0.7'}
r=requests.get(URL,headers=headers,timeout=120)
r.raise_for_status()
Path('9fzt_air_china_cargo_article.html').write_bytes(r.content)
# decode with apparent encoding
r.encoding=r.apparent_encoding or 'utf-8'
soup=BeautifulSoup(r.text,'html.parser')
for tag in soup(['script','style','noscript']): tag.decompose()
text='\n'.join(line.strip() for line in soup.get_text('\n').splitlines() if line.strip())
Path('9fzt_air_china_cargo_article.txt').write_text(text,encoding='utf-8')
classes=[]
for tag in soup.find_all(True):
 cls=' '.join(tag.get('class',[]))
 if cls and any(k in cls.lower() for k in ('article','content','detail','main')):
  t=' '.join(tag.get_text(' ',strip=True).split())
  if len(t)>100:
   classes.append({'tag':tag.name,'class':cls,'id':tag.get('id'),'text':t})
Path('9fzt_air_china_cargo_candidates.json').write_text(json.dumps(classes,ensure_ascii=False,indent=2),encoding='utf-8')
print('status',r.status_code,'bytes',len(r.content),'text_chars',len(text),'candidates',len(classes),flush=True)
for x in sorted(classes,key=lambda z:len(z['text']),reverse=True)[:20]:
 print('CAND',x['tag'],x['class'],x['id'],len(x['text']),x['text'][:2000],flush=True)
