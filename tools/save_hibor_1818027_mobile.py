import requests

url = 'https://wt.hibor.com.cn/wap_detail.aspx?id=60dbee073e3d1bce091ca09fcb5046c8&un=&wp=2&fromtype=2&sm=1'
headers = {'User-Agent': 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 Mobile Safari/537.36', 'Accept-Language': 'zh-CN,zh;q=0.9'}
r = requests.get(url, headers=headers, timeout=120, allow_redirects=True)
r.raise_for_status()
r.encoding = r.apparent_encoding or 'utf-8'
with open('hibor_1818027_mobile.html', 'w', encoding='utf-8') as f:
    f.write(r.text)
print('status', r.status_code, 'bytes', len(r.content), 'url', r.url)
print(r.text[:20000])
