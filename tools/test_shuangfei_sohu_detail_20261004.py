import requests
from bs4 import BeautifulSoup

urls = [
    'https://q.stock.sohu.com/cn/gg/2020/300817/38387201.shtml',
    'http://q.stock.sohu.com/cn/gg/2020/300817/38387201.shtml',
    'https://q.stock.sohu.com/cn/gg/300817/38387201.shtml',
    'https://q.stock.sohu.com/cn/300817/gg/38387201.shtml',
]
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36',
    'Referer': 'https://q.stock.sohu.com/cn/300817/gsgg_1.shtml',
}
for url in urls:
    try:
        response = requests.get(url, headers=headers, timeout=120, allow_redirects=True)
        response.encoding = response.apparent_encoding or 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        print('URL', url)
        print('STATUS', response.status_code, 'FINAL', response.url, 'BYTES', len(response.content))
        print('TITLE', soup.title.get_text(' ', strip=True) if soup.title else '')
        print('TEXT', ' '.join(soup.get_text(' ', strip=True).split())[:1500])
        for tag in soup.find_all(['a', 'iframe', 'embed', 'object']):
            value = tag.get('href') or tag.get('src') or tag.get('data')
            if value and ('pdf' in value.lower() or 'cninfo' in value.lower() or 'download' in value.lower()):
                print('LINK', tag.name, value, tag.get_text(' ', strip=True))
    except Exception as exc:
        print('ERROR', url, repr(exc))
