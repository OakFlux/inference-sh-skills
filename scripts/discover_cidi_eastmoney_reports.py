from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlencode

import requests

OUT = Path('cidi_eastmoney_discovery')
OUT.mkdir(exist_ok=True)
S = requests.Session()
S.trust_env = False
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36',
    'Accept': 'application/json,text/javascript,*/*;q=0.01',
    'Referer': 'https://data.eastmoney.com/report/',
}

codes = ['03881', '03881.HK', '3881', '3881.HK']
base = 'https://reportapi.eastmoney.com/report/list'
variants = []
for code in codes:
    for qtype in ['0', '1', '2']:
        params = {
            'pageSize': '100', 'pageNo': '1', 'qType': qtype, 'code': code,
            'beginTime': '2025-01-01', 'endTime': '2026-09-22',
        }
        variants.append((f'list_{code.replace(".","_")}_q{qtype}', base + '?' + urlencode(params)))
        params2 = dict(params)
        params2.update({'industryCode': '*', 'industry': '*', 'rating': '*', 'ratingChange': '*', 'orgCode': '*'})
        variants.append((f'listfull_{code.replace(".","_")}_q{qtype}', base + '?' + urlencode(params2)))

# Public search and report pages that may reveal attachment links or info codes.
variants += [
    ('stock_page_03881', 'https://data.eastmoney.com/report/stock.jshtml?stockcode=03881'),
    ('stock_page_03881hk', 'https://data.eastmoney.com/report/stock.jshtml?stockcode=03881.HK'),
    ('search_page_name', 'https://so.eastmoney.com/web/s?keyword=%E5%B8%8C%E8%BF%AA%E6%99%BA%E9%A9%BE'),
]

results = {}
for name, url in variants:
    try:
        r = S.get(url, headers=HEADERS, timeout=(10, 45), allow_redirects=True)
        body = r.content
        ctype = r.headers.get('content-type', '')
        suffix = '.json' if 'json' in ctype else '.html' if 'html' in ctype else '.txt'
        path = OUT / f'{name}{suffix}'
        path.write_bytes(body)
        text = body.decode(r.encoding or 'utf-8', errors='replace')
        info_codes = sorted(set(re.findall(r'AP\d{18}', text)))
        pdf_urls = sorted(set(re.findall(r'https?://[^\s"\'<>]+\.pdf(?:\?[^\s"\'<>]*)?', text, flags=re.I)))
        results[name] = {
            'url': url, 'final_url': r.url, 'status': r.status_code,
            'content_type': ctype, 'bytes': len(body), 'saved_as': str(path),
            'info_codes': info_codes, 'pdf_urls': pdf_urls[:100],
            'text_head': text[:1000],
        }
        print(name, r.status_code, len(body), len(info_codes), len(pdf_urls), r.url, flush=True)
    except Exception as exc:
        results[name] = {'url': url, 'error': repr(exc)}
        print(name, 'ERROR', repr(exc), flush=True)

# Try a few Eastmoney general APIs/search endpoints.
extra_urls = [
    'https://searchapi.eastmoney.com/api/suggest/get?input=%E5%B8%8C%E8%BF%AA%E6%99%BA%E9%A9%BE&type=14&count=20',
    'https://searchapi.eastmoney.com/api/suggest/get?input=03881&type=14&count=20',
    'https://search-api-web.eastmoney.com/search/jsonp?cb=jQuery&q=%E5%B8%8C%E8%BF%AA%E6%99%BA%E9%A9%BE&type=report&pageindex=1&pagesize=100',
]
for idx, url in enumerate(extra_urls):
    name = f'extra_{idx}'
    try:
        r = S.get(url, headers=HEADERS, timeout=(10, 45), allow_redirects=True)
        body = r.content
        text = body.decode(r.encoding or 'utf-8', errors='replace')
        path = OUT / f'{name}.txt'
        path.write_bytes(body)
        results[name] = {
            'url': url, 'final_url': r.url, 'status': r.status_code,
            'content_type': r.headers.get('content-type',''), 'bytes': len(body),
            'saved_as': str(path),
            'info_codes': sorted(set(re.findall(r'AP\d{18}', text))),
            'pdf_urls': sorted(set(re.findall(r'https?://[^\s"\'<>]+\.pdf(?:\?[^\s"\'<>]*)?', text, flags=re.I)))[:100],
            'text_head': text[:2000],
        }
        print(name, r.status_code, len(body), flush=True)
    except Exception as exc:
        results[name] = {'url': url, 'error': repr(exc)}

(OUT / 'summary.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
