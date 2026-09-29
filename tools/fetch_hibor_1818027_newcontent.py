import requests

base = 'https://wt.hibor.com.cn'
page = base + '/docdetail_1818027.html'
endpoint = base + '/hiborweb/DocDetail/NewContent'
headers = {
    'User-Agent': 'Mozilla/5.0',
    'Referer': page,
    'Origin': base,
    'X-Requested-With': 'XMLHttpRequest',
}
s = requests.Session()
s.headers.update(headers)
s.get(page, timeout=120)
r = s.post(endpoint, data={'ncid': '8002774a-8624-45d2-89ee-6a319bd74082'}, timeout=120)
r.raise_for_status()
r.encoding = r.apparent_encoding or 'utf-8'
with open('hibor_1818027_newcontent.html', 'w', encoding='utf-8') as f:
    f.write(r.text)
print('status', r.status_code, 'bytes', len(r.content), 'url', r.url)
print(r.text[:12000])
