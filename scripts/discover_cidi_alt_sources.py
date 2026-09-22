from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

OUT = Path('cidi_alt_sources')
OUT.mkdir(exist_ok=True)
S = requests.Session(); S.trust_env = False
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36'
H = {'User-Agent': UA, 'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8', 'Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8'}

sources = {
  'eet_guosen': 'https://www.eet-china.com/mp/a469518.html',
  'eet_dongwu': 'https://www.eet-china.com/mp/a472858.html',
  'vzkoo_dongwu': 'https://www.vzkoo.com/read/4629775438372147200.html',
  'baogaobox_guosen': 'https://www.baogaobox.com/insights/260119000024898.html',
  'baogaobox_dongwu': 'https://www.baogaobox.com/insights/260126000025082.html',
  'sdyanbao_guosen': 'https://www.sdyanbao.com/detail/943185',
  'fhyanbao_zhongyou': 'https://www.fhyanbao.com/rpview/1917215',
  'sgpjbg_dongwu': 'https://www.sgpjbg.com/bgdown/1272831.html',
}

def extract(name, url, body, final_url, ctype):
    text = body.decode('utf-8', errors='replace')
    soup = BeautifulSoup(text, 'html.parser')
    urls=[]
    attrs=['href','src','data-src','data-original','data-lazy-src','data-url','data-file','content']
    for tag in soup.find_all(True):
        for a in attrs:
            v=tag.get(a)
            if isinstance(v,str) and v.strip():
                u=urljoin(final_url,v.strip())
                if any(x in u.lower() for x in ['.pdf','.png','.jpg','.jpeg','.webp','download','file','report','attachment','oss','cos','cdn']):
                    urls.append(u)
    for m in re.findall(r'https?://[^\s"\'<>]+', text):
        if any(x in m.lower() for x in ['.pdf','.png','.jpg','.jpeg','.webp','download','file','report','attachment','oss','cos','cdn']):
            urls.append(m)
    rec={'requested_url':url,'final_url':final_url,'content_type':ctype,'bytes':len(body),'urls':list(dict.fromkeys(urls)),'title':soup.title.get_text(' ',strip=True) if soup.title else ''}
    (OUT/f'{name}_extracted.json').write_text(json.dumps(rec,ensure_ascii=False,indent=2),encoding='utf-8')
    return rec

summary={}
for name,url in sources.items():
    try:
        r=S.get(url,headers=H,timeout=(15,90),allow_redirects=True)
        body=r.content; ctype=r.headers.get('content-type','')
        (OUT/f'{name}.html').write_bytes(body)
        rec=extract(name,url,body,r.url,ctype); rec['status']=r.status_code
        summary[name]=rec
        print('REQ',name,r.status_code,len(body),len(rec['urls']),r.url,flush=True)
    except Exception as e:
        summary[name]={'url':url,'error':repr(e)}; print('REQ_ERROR',name,repr(e),flush=True)

try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
        ctx=browser.new_context(user_agent=UA,locale='zh-CN',viewport={'width':1600,'height':1200})
        for name,url in sources.items():
            page=ctx.new_page(); events=[]
            def on_resp(resp):
                u=resp.url; ct=resp.headers.get('content-type','')
                if any(x in (u+' '+ct).lower() for x in ['pdf','image','json','download','file','report','attachment','png','jpg','jpeg','webp']):
                    events.append({'url':u,'status':resp.status,'content_type':ct})
            page.on('response',on_resp)
            try:
                page.goto(url,wait_until='domcontentloaded',timeout=90000)
                for _ in range(12):
                    page.mouse.wheel(0,5000); page.wait_for_timeout(1000)
                page.wait_for_timeout(5000)
                html=page.content(); (OUT/f'{name}_rendered.html').write_text(html,encoding='utf-8')
                (OUT/f'{name}_network.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
                # collect DOM attributes after lazy loading
                domurls=page.evaluate('''() => Array.from(document.querySelectorAll('*')).flatMap(el => ['href','src','data-src','data-original','data-lazy-src','data-url','data-file'].map(a=>el.getAttribute(a)).filter(Boolean))''')
                domurls=[urljoin(page.url,x) for x in domurls]
                (OUT/f'{name}_domurls.json').write_text(json.dumps(list(dict.fromkeys(domurls)),ensure_ascii=False,indent=2),encoding='utf-8')
                page.screenshot(path=str(OUT/f'{name}.png'),full_page=True)
                print('BROWSER',name,page.url,len(events),len(domurls),flush=True)
            except Exception as e:
                (OUT/f'{name}_browser_error.txt').write_text(repr(e),encoding='utf-8'); print('BROWSER_ERROR',name,repr(e),flush=True)
            finally: page.close()
        browser.close()
except Exception as e:
    (OUT/'playwright_error.txt').write_text(repr(e),encoding='utf-8')

(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
