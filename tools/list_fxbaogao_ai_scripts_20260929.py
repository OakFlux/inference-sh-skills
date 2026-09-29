from pathlib import Path
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

url = 'https://www.fxbaogao.com/aisearch/report'
headers = {'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'zh-CN,zh;q=0.9'}
r = requests.get(url, headers=headers, timeout=120)
r.raise_for_status()
soup = BeautifulSoup(r.text, 'html.parser')
scripts = [urljoin(r.url, tag.get('src')) for tag in soup.find_all('script') if tag.get('src')]
Path('fxbaogao_ai_script_urls.json').write_text(json.dumps(scripts, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(scripts, ensure_ascii=False, indent=2))
