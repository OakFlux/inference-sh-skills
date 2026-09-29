import json
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

url = 'https://wt.hibor.com.cn/docdetail_1818027.html'
headers = {'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'zh-CN,zh;q=0.9'}
r = requests.get(url, headers=headers, timeout=120)
r.raise_for_status()
r.encoding = r.apparent_encoding or 'utf-8'
soup = BeautifulSoup(r.text, 'html.parser')
items = []
for tag in soup.find_all(['img', 'a']):
    value = tag.get('src') or tag.get('data-src') or tag.get('data-original') or tag.get('href')
    if value:
        full = urljoin(r.url, value)
        text = ' '.join(tag.get_text(' ', strip=True).split())
        if tag.name == 'img' or any(word in (full + text).lower() for word in ['pdf','download','report','doc','1818027','view']):
            items.append({'tag': tag.name, 'url': full, 'text': text, 'alt': tag.get('alt')})
with open('hibor_1818027_links.json', 'w', encoding='utf-8') as f:
    json.dump(items, f, ensure_ascii=False, indent=2)
print(json.dumps(items, ensure_ascii=False, indent=2))
