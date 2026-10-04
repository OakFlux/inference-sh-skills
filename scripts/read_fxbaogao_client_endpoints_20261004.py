import re

import requests

session = requests.Session()
session.trust_env = False
session.headers.update({"User-Agent": "Mozilla/5.0 Chrome/152 Safari/537.36"})

assets = [
    "https://static.fxbaogao.com/pub/js/config/production.js",
    "https://www.fxbaogao.com/_fxbg/2609291744/js/runtime.f40e62a59d16c7ce3dad.js",
    "https://www.fxbaogao.com/_fxbg/2609291744/js/vendors~app-pages-fxbg-main-js.3e614d4b195978fb4799.chunk.js",
    "https://www.fxbaogao.com/_fxbg/2609291744/js/app-pages-fxbg-main-js.4e85af91191f3f7c70f1.chunk.js",
]

terms = [
    "report-image",
    "docId",
    "pageCount",
    "page_count",
    "download",
    "preview",
    "reportDetail",
    "report/detail",
    "/view",
    "/pdf",
    "api.fxbaogao.com",
    "mofoun",
    "original",
    "fileUrl",
    "file_url",
]

for url in assets:
    response = session.get(url, timeout=120)
    print("ASSET", response.status_code, response.url, response.headers.get("content-type"), len(response.content))
    text = response.text
    print(text[:3000])
    for term in terms:
        positions = [m.start() for m in re.finditer(re.escape(term), text, re.I)]
        print("TERM", term, len(positions))
        for position in positions[:30]:
            print(text[max(0, position-700):position+1800])
