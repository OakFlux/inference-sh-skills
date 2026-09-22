from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

OUT = Path('cidi_sgpjbg_preview')
OUT.mkdir(exist_ok=True)
URL = 'https://www.sgpjbg.com/baogao/1272831.html'
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36'

s = requests.Session(); s.trust_env = False
r = s.get(URL, headers={'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'}, timeout=(15,120), allow_redirects=True)
print('REQUEST', r.status_code, r.url, r.headers.get('content-type'), len(r.content), flush=True)
r.raise_for_status()
(OUT/'page.html').write_bytes(r.content)
text = r.text
soup = BeautifulSoup(text, 'html.parser')
urls=[]
for tag in soup.find_all(True):
    for attr in ('src','href','data-src','data-original','data-lazy-src','data-url','data-file'):
        v=tag.get(attr)
        if isinstance(v,str) and v.strip():
            u=urljoin(r.url,v.strip())
            if any(x in u.lower() for x in ('fileroot','fileupload','preview','page','1272831','.png','.jpg','.jpeg','.webp','.gif','.pdf')):
                urls.append(u)
for m in re.findall(r'https?://[^\s"\'<>]+',text):
    if any(x in m.lower() for x in ('fileroot','fileupload','preview','page','1272831','.png','.jpg','.jpeg','.webp','.gif','.pdf')):
        urls.append(m)
record={'url':URL,'final_url':r.url,'status':r.status_code,'bytes':len(r.content),'urls':list(dict.fromkeys(urls))}
(OUT/'request_urls.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')

try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
        ctx=browser.new_context(user_agent=UA,locale='zh-CN',viewport={'width':1600,'height':1200})
        page=ctx.new_page(); events=[]
        def on_response(resp):
            u=resp.url; ct=resp.headers.get('content-type','')
            if any(x in (u+' '+ct).lower() for x in ('image','json','pdf','fileroot','fileupload','1272831','preview','page')):
                events.append({'url':u,'status':resp.status,'content_type':ct})
        page.on('response',on_response)
        page.goto(URL,wait_until='domcontentloaded',timeout=120000)
        for _ in range(20):
            page.mouse.wheel(0,4000); page.wait_for_timeout(500)
        page.wait_for_timeout(5000)
        (OUT/'rendered.html').write_text(page.content(),encoding='utf-8')
        domurls=page.evaluate('''() => Array.from(document.querySelectorAll('*')).flatMap(el => ['href','src','data-src','data-original','data-lazy-src','data-url','data-file'].map(a=>el.getAttribute(a)).filter(Boolean))''')
        domurls=[urljoin(page.url,x) for x in domurls]
        (OUT/'domurls.json').write_text(json.dumps(list(dict.fromkeys(domurls)),ensure_ascii=False,indent=2),encoding='utf-8')
        (OUT/'network.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
        page.screenshot(path=str(OUT/'page.png'),full_page=True)
        print('BROWSER',page.url,len(events),len(domurls),flush=True)
        browser.close()
except Exception as exc:
    (OUT/'browser_error.txt').write_text(repr(exc),encoding='utf-8')
    print('BROWSER_ERROR',repr(exc),flush=True)
