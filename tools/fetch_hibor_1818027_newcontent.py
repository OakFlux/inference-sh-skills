import re
import requests

base = 'https://wt.hibor.com.cn'
page = base + '/docdetail_1818027.html'
endpoint = base + '/hiborweb/DocDetail/NewContent'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.7',
}
s = requests.Session()
s.headers.update(headers)
page_response = s.get(page, timeout=120)
page_response.raise_for_status()
page_response.encoding = page_response.apparent_encoding or 'utf-8'
match = re.search(r"var\s+ncid\s*=\s*['\"]([^'\"]+)['\"]", page_response.text)
if not match:
    raise RuntimeError('Unable to find ncid on report page')
ncid = match.group(1)
print('ncid', ncid)
r = s.post(
    endpoint,
    data={'ncid': ncid},
    headers={
        'Referer': page,
        'Origin': base,
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': '*/*',
    },
    timeout=120,
)
r.raise_for_status()
r.encoding = r.apparent_encoding or 'utf-8'
with open('hibor_1818027_newcontent.html', 'w', encoding='utf-8') as f:
    f.write(r.text)
print('status', r.status_code, 'bytes', len(r.content), 'url', r.url)
print(r.text[:20000])
