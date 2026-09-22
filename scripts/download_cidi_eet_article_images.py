from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageOps, ImageDraw

OUT = Path('cidi_eet_images')
OUT.mkdir(exist_ok=True)
S = requests.Session(); S.trust_env = False
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}
ARTICLES = {
    'guosen': 'https://www.eet-china.com/mp/a469518.html',
    'dongwu': 'https://www.eet-china.com/mp/a472858.html',
}

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

manifest={}
for label,url in ARTICLES.items():
    d=OUT/label; d.mkdir(exist_ok=True)
    h=dict(HEADERS); h['Referer']='https://www.eet-china.com/'
    r=S.get(url,headers=h,timeout=(15,90)); r.raise_for_status()
    (d/'article.html').write_bytes(r.content)
    soup=BeautifulSoup(r.content,'html.parser')
    title=soup.title.get_text(' ',strip=True) if soup.title else ''
    imgs=[]
    # Prefer main article containers, then fall back to all document images.
    containers=[]
    for sel in ['article','.article-content','.content','.article-detail','.rich_media_content','.mp-article','.detail-content','#article-content']:
        containers.extend(soup.select(sel))
    roots=containers if containers else [soup]
    seen=set()
    for root in roots:
        for tag in root.find_all('img'):
            vals=[]
            for attr in ['data-original','data-src','data-lazy-src','src']:
                v=tag.get(attr)
                if isinstance(v,str) and v.strip(): vals.append(v.strip())
            for v in vals:
                u=urljoin(r.url,v)
                if 'mianbaoban-assets.eet-china.com' not in u and 'xinyu-images' not in u:
                    continue
                if u in seen: continue
                seen.add(u)
                imgs.append({'url':u,'alt':tag.get('alt',''),'class':tag.get('class',[]),'attrs':dict(tag.attrs)})
    # Fall back to raw source URL order if selector missed content.
    if len(imgs)<5:
        raw=r.text
        for u in re.findall(r'https?://[^\s"\'<>]+',raw):
            u=u.replace('\\u002F','/').replace('\\/','/')
            if ('mianbaoban-assets.eet-china.com' in u or 'xinyu-images' in u) and u not in seen:
                seen.add(u); imgs.append({'url':u,'alt':'','class':[],'attrs':{}})
    records=[]
    for i,item in enumerate(imgs,1):
        iu=item['url']
        ih=dict(HEADERS); ih['Referer']=r.url; ih['Accept']='image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
        ir=S.get(iu,headers=ih,timeout=(15,120)); ir.raise_for_status()
        suffix=Path(urlparse(iu).path).suffix.lower() or '.img'
        temp=d/f'{i:03d}{suffix}'
        temp.write_bytes(ir.content)
        try:
            with Image.open(temp) as im:
                im.load(); w,hgt=im.size; fmt=im.format; mode=im.mode
                png=d/f'{i:03d}.png'
                if im.mode not in ('RGB','L'): im=im.convert('RGB')
                im.save(png,'PNG')
            if temp != png: temp.unlink(missing_ok=True)
            p=png
            records.append({'index':i,'url':iu,'path':str(p),'width':w,'height':hgt,'format':fmt,'mode':mode,'bytes':p.stat().st_size,'sha256':sha256(p),'alt':item['alt']})
            print(label,i,w,hgt,iu,flush=True)
        except Exception as exc:
            records.append({'index':i,'url':iu,'path':str(temp),'bytes':temp.stat().st_size,'error':repr(exc),'alt':item['alt']})
            print(label,i,'ERROR',repr(exc),iu,flush=True)
    # Contact sheets: preserve aspect ratio, numbered thumbnails, max 12 per sheet.
    pages=[]
    valid=[x for x in records if 'width' in x]
    for start in range(0,len(valid),12):
        subset=valid[start:start+12]
        thumb_w=360; thumb_h=520; margin=30; label_h=40; cols=3; rows=4
        sheet=Image.new('RGB',(cols*(thumb_w+margin)+margin,rows*(thumb_h+label_h+margin)+margin),'white')
        draw=ImageDraw.Draw(sheet)
        for j,rec in enumerate(subset):
            im=Image.open(rec['path']).convert('RGB')
            im.thumbnail((thumb_w,thumb_h))
            x=margin+(j%cols)*(thumb_w+margin)+(thumb_w-im.width)//2
            y=margin+(j//cols)*(thumb_h+label_h+margin)+(thumb_h-im.height)//2
            sheet.paste(im,(x,y))
            draw.text((margin+(j%cols)*(thumb_w+margin), margin+(j//cols)*(thumb_h+label_h+margin)+thumb_h+5),f"#{rec['index']} {rec['width']}x{rec['height']}",fill='black')
        sp=d/f'contact_{start+1:03d}_{start+len(subset):03d}.jpg'; sheet.save(sp,'JPEG',quality=85)
        pages.append(str(sp))
    manifest[label]={'article_url':url,'final_url':r.url,'title':title,'image_count':len(records),'images':records,'contact_sheets':pages}
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
