from __future__ import annotations

import re
import requests

URLS = [
    "https://www.hibor.com.cn/docdetail_1693330.html",
    "https://www.hibor.com.cn/docdetail_1758464.html",
    "https://www.hibor.com.cn/docdetail_1794762.html",
    "https://www.hibor.com.cn/docdetail_2053918.html",
]
session = requests.Session()
session.headers.update({"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36","Accept-Language":"zh-CN,zh;q=0.9,en;q=0.8","X-Requested-With":"XMLHttpRequest"})
for url in URLS:
    try:
        p=session.get(url,timeout=(20,90),allow_redirects=True)
        m=re.search(r"var\s+ncid\s*=\s*'([^']+)'",p.text)
        ncid=m.group(1) if m else ""
        r=session.post("https://www.hibor.com.cn/hiborweb/DocDetail/NewContent",data={"ncid":ncid},headers={"Referer":p.url},timeout=(20,90))
        print("URL",url,"FINAL",p.url,"NCID",ncid,"STATUS",r.status_code,"BYTES",len(r.content),flush=True)
        for key in ["metaTitle","metaKeywords","metaDescription","viewUrl","downloadUrl"]:
            mm=re.search(rf"var\s+{key}\s*=\s*'((?:\\'|[^'])*)'",r.text,re.S)
            print(key, mm.group(1) if mm else "", flush=True)
        clean=re.sub(r"<[^>]+>"," ",r.text)
        clean=re.sub(r"\s+"," ",clean)
        print("TEXT",clean[:3000],flush=True)
    except Exception as exc:
        print("ERROR",url,repr(exc),flush=True)
