import requests

base = 'https://wt.hibor.com.cn'
paths = [
    '/hiborweb/DocDetailNew/js?v=JhJG5MdT9wDoAQX8-xy-bc9qho_6DU5Ailv07PYCEEg1',
    '/hiborweb/Layout/js?v=y-hSAvanSMBlkE1eYNOj0AZwGQP8Ydf-m7Ph5F3q0pk1',
]
headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://wt.hibor.com.cn/docdetail_1818027.html'}
for index, path in enumerate(paths, start=1):
    r = requests.get(base + path, headers=headers, timeout=120)
    r.raise_for_status()
    name = f'hibor_bundle_{index}.js'
    with open(name, 'wb') as f:
        f.write(r.content)
    print(name, len(r.content), r.url, r.headers.get('content-type'))
