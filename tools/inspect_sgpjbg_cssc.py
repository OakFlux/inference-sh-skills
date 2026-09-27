from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

OUT = Path('_inspect_sgpjbg_cssc')
OUT.mkdir(exist_ok=True)
URLS = [
    'https://www.sgpjbg.com/zhuanti/chuanboyanjiubaogao.html',
    'https://www.sgpjbg.com/zhuanti/youyun.html',
    'https://www.vzkoo.com/read/2025060902a1862f3c72dda89647d923.html',
    'https://www.fxbaogao.com/detail/4887981',
]
NEEDLES = ['中国船舶租赁', '产业壁垒较高', '专业船舶租赁', '受益油运景气上升', '船厂系船舶租赁商龙头']
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.7',
}
session = requests.Session()
session.headers.update(HEADERS)

all_results = []
for idx, url in enumerate(URLS, 1):
    try:
        r = session.get(url, timeout=90, allow_redirects=True)
        print('GET', idx, r.status_code, len(r.content), r.url, r.headers.get('content-type'), flush=True)
        (OUT / f'{idx:02d}.bin').write_bytes(r.content)
        text = r.text
        (OUT / f'{idx:02d}.html').write_text(text, encoding='utf-8', errors='replace')
        soup = BeautifulSoup(text, 'html.parser')
        rows = []
        for tag in soup.find_all(['a','iframe','embed','object','script','img','link','source']):
            attrs = {}
            for key in ('href','src','data-src','data-url','data-original','data-pdf','value'):
                if tag.get(key):
                    attrs[key] = urljoin(r.url, tag.get(key))
            content = ' '.join(tag.get_text(' ', strip=True).split())
            joined = ' '.join([content, *attrs.values()])
            if any(n in joined for n in NEEDLES) or any(k in joined.lower() for k in ('pdf','download','downfile','bgdown','report','fileurl','oss','cos','cdn')):
                row = {'tag': tag.name, 'text': content[:500], 'attrs': attrs}
                rows.append(row)
                print('MATCH', idx, json.dumps(row, ensure_ascii=False), flush=True)
        # Also search raw HTML for likely URLs and target context.
        urls = sorted(set(re.findall(r'https?://[^"\'<>\\\s]+', text)))
        likely = [u for u in urls if any(k in u.lower() for k in ('pdf','download','file','oss','cos','cdn','report'))]
        for u in likely[:300]:
            print('RAWURL', idx, u[:1000], flush=True)
        result = {
            'requested_url': url,
            'final_url': r.url,
            'status': r.status_code,
            'content_type': r.headers.get('content-type'),
            'title': soup.title.get_text(' ', strip=True) if soup.title else '',
            'matches': rows,
            'likely_raw_urls': likely,
        }
        all_results.append(result)
    except Exception as exc:
        print('ERROR', idx, url, repr(exc), flush=True)
        all_results.append({'requested_url': url, 'error': repr(exc)})

(OUT / 'summary.json').write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding='utf-8')
