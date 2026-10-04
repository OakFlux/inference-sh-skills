from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

OUT = Path('fxbaogao_longban_search_inventory.json')
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.7',
}
TERMS = ['龙版传媒', '深耕出版业务主业，业绩发展稳健', '605577', '王凤华 龙版传媒']
URL_PATTERNS = [
    'https://www.fxbaogao.com/search?keyword={q}',
    'https://www.fxbaogao.com/search?query={q}',
    'https://www.fxbaogao.com/search?q={q}',
    'https://www.fxbaogao.com/search/{q}',
    'https://www.fxbaogao.com/?keyword={q}',
    'https://www.fxbaogao.com/ai-search?keyword={q}',
    'https://www.fxbaogao.com/report/search?keyword={q}',
]


def scan_html(text: str, base: str) -> dict:
    soup = BeautifulSoup(text, 'html.parser')
    title = soup.title.get_text(' ', strip=True) if soup.title else ''
    links=[]
    for a in soup.find_all('a', href=True):
        label=' '.join(a.get_text(' ',strip=True).split())
        href=urljoin(base,a['href'])
        if any(t in (label+' '+href) for t in ['龙版传媒','605577','深耕出版业务','detail/']):
            links.append({'label':label,'url':href})
    scripts=[urljoin(base,s.get('src')) for s in soup.find_all('script') if s.get('src')]
    excerpts={}
    for token in ['龙版传媒','605577','深耕出版业务','search','keyword','query','api','report']:
        arr=[]
        for m in re.finditer(re.escape(token), text, re.I):
            arr.append(text[max(0,m.start()-500):m.start()+1500])
            if len(arr)>=10: break
        if arr: excerpts[token]=arr
    return {'title':title,'links':links[:200],'scripts':scripts,'excerpts':excerpts}

session=requests.Session(); session.headers.update(HEADERS)
records=[]
for term in TERMS:
    for pattern in URL_PATTERNS:
        url=pattern.format(q=quote(term))
        try:
            r=session.get(url,timeout=120,allow_redirects=True)
            item={'term':term,'url':url,'final_url':r.url,'status':r.status_code,'bytes':len(r.content),'content_type':r.headers.get('content-type'),'scan':scan_html(r.text,r.url),'prefix':r.text[:2000]}
            records.append(item)
            print('PAGE',json.dumps({k:item[k] for k in ('term','url','final_url','status','bytes','content_type')},ensure_ascii=False),flush=True)
            print('TITLE',item['scan']['title'],flush=True)
            print('LINKS',json.dumps(item['scan']['links'][:50],ensure_ascii=False),flush=True)
        except Exception as e:
            records.append({'term':term,'url':url,'error':repr(e)})
            print('ERROR',term,url,repr(e),flush=True)
# inspect scripts from the first successful page, de-duplicated
script_urls=[]
for rec in records:
    if 'scan' in rec:
        for u in rec['scan']['scripts']:
            if u not in script_urls: script_urls.append(u)
script_records=[]
for u in script_urls:
    try:
        r=session.get(u,timeout=120)
        text=r.text
        if any(tok.lower() in text.lower() for tok in ['search','keyword','report','api']):
            excerpts=[]
            for tok in ['search','keyword','/api/','report']:
                for m in re.finditer(re.escape(tok),text,re.I):
                    excerpts.append(text[max(0,m.start()-800):m.start()+2200])
                    if len(excerpts)>=20: break
                if len(excerpts)>=20: break
            sr={'url':u,'status':r.status_code,'bytes':len(r.content),'content_type':r.headers.get('content-type'),'excerpts':excerpts}
            script_records.append(sr)
            print('SCRIPT',json.dumps({'url':u,'status':r.status_code,'bytes':len(r.content)},ensure_ascii=False),flush=True)
            for ex in excerpts[:10]: print('SCRIPT_EXCERPT',u,json.dumps(ex,ensure_ascii=False),flush=True)
    except Exception as e:
        script_records.append({'url':u,'error':repr(e)})
OUT.write_text(json.dumps({'pages':records,'scripts':script_records},ensure_ascii=False,indent=2),encoding='utf-8')
print('DONE',OUT,flush=True)
