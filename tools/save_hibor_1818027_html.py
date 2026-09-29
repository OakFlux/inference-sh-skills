import requests

url = 'https://wt.hibor.com.cn/docdetail_1818027.html'
headers = {'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'zh-CN,zh;q=0.9'}
r = requests.get(url, headers=headers, timeout=120)
r.raise_for_status()
r.encoding = r.apparent_encoding or 'utf-8'
with open('hibor_1818027_page.html', 'w', encoding='utf-8') as f:
    f.write(r.text)
print('saved', len(r.text), r.url)
