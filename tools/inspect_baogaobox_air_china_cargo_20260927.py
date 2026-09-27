from __future__ import annotations
import html,json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

URL='https://www.baogaobox.com/reports/260104000089436.html'
OUT=Path('baogaobox_air_china_cargo_inventory.json')
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36','Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8','Accept-Language':'zh-CN,zh;q=0.9,en;q=0.7'}

def scan(text,base):
 d=html.unescape(text).replace('\\/','/')
 urls=set()
 for pat in [r'https?://[^\s"\'<>]+',r'//[^\s"\'<>]+',r'["\'](/[^"\']+(?:pdf|report|download|file|api|image|page)[^"\']*)["\']']:
  for x in re.findall(pat,d,re.I):
   if x.startswith('//'): x='https:'+x
   elif x.startswith('/'): x=urljoin(base,x)
   x=x.rstrip(',);]}\\')
   if any(k in x.lower() for k in ('pdf','report','download','file','api','image','page','260104000089436')): urls.add(x)
 soup=BeautifulSoup(text,'html.parser')
 scripts=[urljoin(base,t.get('src')) for t in soup.find_all('script') if t.get('src')]
 next_data=''
 nd=soup.find('script',id='__NEXT_DATA__')
 if nd: next_data=nd.get_text()
 excerpts={}
 for token in ['260104000089436','pdf','download','fileUrl','pdfUrl','reportId','pageCount','pages','preview','image','attachment','api']:
  arr=[]
  for m in re.finditer(re.escape(token),text,re.I):
   arr.append(text[max(0,m.start()-600):m.start()+1600])
   if len(arr)>=10:break
  if arr:excerpts[token]=arr
 return {'urls':sorted(urls),'scripts':scripts,'next_data':next_data,'excerpts':excerpts}

def main():
 s=requests.Session();s.headers.update(HEADERS)
 records=[]
 try:
  r=s.get(URL,timeout=120,allow_redirects=True)
  rec={'kind':'page','url':URL,'final_url':r.url,'status':r.status_code,'bytes':len(r.content),'content_type':r.headers.get('content-type'),'headers':dict(r.headers),'title':'','scan':scan(r.text,r.url),'prefix':r.text[:5000]}
  sp=BeautifulSoup(r.text,'html.parser')
  if sp.title:rec['title']=sp.title.get_text(' ',strip=True)
  records.append(rec)
  print('PAGE',json.dumps({k:rec[k] for k in ('final_url','status','bytes','content_type','title')},ensure_ascii=False),flush=True)
  print('URLS',json.dumps(rec['scan']['urls'],ensure_ascii=False),flush=True)
  print('NEXT',rec['scan']['next_data'][:5000],flush=True)
  for token,arr in rec['scan']['excerpts'].items():
   for x in arr:print('EXCERPT',token,json.dumps(x,ensure_ascii=False),flush=True)
  for u in rec['scan']['scripts']:
   try:
    q=s.get(u,timeout=120,allow_redirects=True)
    sr={'kind':'script','url':u,'final_url':q.url,'status':q.status_code,'bytes':len(q.content),'content_type':q.headers.get('content-type'),'scan':scan(q.text,q.url),'prefix':q.text[:3000]}
    records.append(sr)
    print('SCRIPT',json.dumps({k:sr[k] for k in ('url','status','bytes','content_type')},ensure_ascii=False),flush=True)
    for token,arr in sr['scan']['excerpts'].items():
     if token in ('260104000089436','pdf','download','fileUrl','pdfUrl','reportId','pageCount','pages','preview','attachment','api'):
      for x in arr[:5]:print('SCRIPT_EXCERPT',u,token,json.dumps(x,ensure_ascii=False),flush=True)
   except Exception as e:records.append({'kind':'script','url':u,'error':repr(e)})
 except Exception as e:
  records.append({'kind':'page','url':URL,'error':repr(e)});print('ERROR',repr(e),flush=True)
 OUT.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
