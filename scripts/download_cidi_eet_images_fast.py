from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from PIL import Image

OUT=Path('cidi_eet_fast'); OUT.mkdir(exist_ok=True)
ARTICLES={
 'guosen':'https://www.eet-china.com/mp/a469518.html',
 'dongwu':'https://www.eet-china.com/mp/a472858.html',
}
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36'

def sha256(p:Path):
 h=hashlib.sha256(); h.update(p.read_bytes()); return h.hexdigest()

def get_article(url):
 s=requests.Session();s.trust_env=False
 r=s.get(url,headers={'User-Agent':UA},timeout=(10,45));r.raise_for_status();return r

def image_urls(text, base):
 # Preserve source order and restrict to article-upload asset naming.
 patterns=[
   r'https?://static\.mianbaoban-assets\.eet-china\.com/xinyu-images/MBXY-CR-[A-Za-z0-9_-]+\.(?:png|jpe?g|webp)',
   r'//static\.mianbaoban-assets\.eet-china\.com/xinyu-images/MBXY-CR-[A-Za-z0-9_-]+\.(?:png|jpe?g|webp)',
 ]
 matches=[]
 for pat in patterns:
  matches.extend((m.start(),m.group(0)) for m in re.finditer(pat,text,re.I))
 matches.sort()
 out=[];seen=set()
 for _,u in matches:
  u=urljoin(base,u.replace('\\/','/'))
  if u not in seen: seen.add(u);out.append(u)
 return out

def fetch_one(args):
 label,idx,url,d=args
 s=requests.Session();s.trust_env=False
 r=s.get(url,headers={'User-Agent':UA,'Referer':ARTICLES[label],'Accept':'image/avif,image/webp,image/apng,image/*,*/*;q=0.8'},timeout=(10,35));r.raise_for_status()
 temp=d/f'{idx:03d}.bin';temp.write_bytes(r.content)
 with Image.open(temp) as im:
  im.load();w,h=im.size;fmt=im.format
  if im.mode not in ('RGB','L'): im=im.convert('RGB')
  p=d/f'{idx:03d}.png';im.save(p,'PNG')
 temp.unlink(missing_ok=True)
 return {'index':idx,'url':url,'path':str(p),'width':w,'height':h,'format':fmt,'bytes':p.stat().st_size,'sha256':sha256(p)}

manifest={}
for label,url in ARTICLES.items():
 d=OUT/label;d.mkdir(exist_ok=True)
 r=get_article(url);(d/'article.html').write_bytes(r.content)
 text=r.text.replace('\\u002F','/').replace('\\/','/')
 urls=image_urls(text,r.url)
 print(label,'URL_COUNT',len(urls),flush=True)
 records=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
  futs={ex.submit(fetch_one,(label,i,u,d)):(i,u) for i,u in enumerate(urls,1)}
  for fut in concurrent.futures.as_completed(futs):
   i,u=futs[fut]
   try: rec=fut.result();records.append(rec);print(label,i,rec['width'],rec['height'],flush=True)
   except Exception as e: records.append({'index':i,'url':u,'error':repr(e)});print(label,i,'ERROR',repr(e),flush=True)
 records.sort(key=lambda x:x['index'])
 manifest[label]={'article_url':url,'final_url':r.url,'count':len(records),'images':records}
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
