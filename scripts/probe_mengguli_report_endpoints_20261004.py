from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin

import requests

S = requests.Session()
S.trust_env = False
H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def get(url: str) -> requests.Response:
    r = S.get(url, headers=H, timeout=40, allow_redirects=True)
    print("GET", url, "=>", r.status_code, r.url, r.headers.get("content-type"), len(r.content))
    return r


def interesting_lines(text: str, keywords: tuple[str, ...], limit: int = 250):
    count = 0
    for idx, line in enumerate(text.splitlines(), start=1):
        low = line.lower()
        if any(k.lower() in low for k in keywords):
            print(f"L{idx}: {line[:2500]}")
            count += 1
            if count >= limit:
                break


print("=== SDYANBAO DETAIL FOCUSED ===")
for detail in (943276, 970423):
    url = f"https://www.sdyanbao.com/detail/{detail}"
    r = get(url)
    t = r.text
    print("DETAIL", detail)
    interesting_lines(t, ("oss.sdyanbao", "pdf", "download", "file", "report", "page", "1286977", "1333943", "5653", "14758", "840", "389"))
    # decode escaped URLs
    for raw in sorted(set(re.findall(r'https?:\\u002F\\u002F[^"< ]+', t))):
        decoded = raw.replace('\\u002F','/').replace('\\u003A',':').replace('\\u0026','&')
        print("ESCAPED_URL", decoded[:2000])
    print("CONTEXTS")
    for token in ("1286977", "1333943", "oss.sdyanbao", "download", "pdf", "file_path", "fileUrl", "page_url"):
        pos = 0
        shown = 0
        while True:
            i = t.lower().find(token.lower(), pos)
            if i < 0 or shown >= 12:
                break
            print("TOKEN", token, "CTX", t[max(0,i-500):i+1200].replace("\n"," "))
            pos = i + len(token)
            shown += 1

print("=== SDYANBAO JS ===")
for asset in ("0bec462.js", "7ff3a18.js", "359ac1f.js", "a94fdf1.js"):
    url = "https://www.sdyanbao.com/_nuxt/" + asset
    r = get(url)
    t = r.text
    print("ASSET", asset)
    # print snippets around likely API strings
    for token in ("download", "pdf", "detail", "report", "oss.sdyanbao", "api/", "$axios", "page_url", "file"):
        pos=0; shown=0
        while True:
            i=t.lower().find(token.lower(),pos)
            if i<0 or shown>=20: break
            print("TOKEN", token, "CTX", t[max(0,i-400):i+1000])
            pos=i+len(token); shown+=1

print("=== NXNY DETAIL ===")
url="https://www.nxny.com/report/view_6345192.html"
r=get(url)
t=r.content.decode('utf-8','replace')
interesting_lines(t,("download","down","vip","login","6345192","viewvip","reportid","pdf","onclick","form","input","href"),limit=500)
print("ALL FORMS")
for m in re.finditer(r'<form\b.*?</form>',t,re.I|re.S):
    print(m.group(0)[:8000])
print("ALL SCRIPTS")
for m in re.finditer(r'<script[^>]+src=["\']([^"\']+)',t,re.I):
    print(urljoin(r.url,m.group(1)))

print("=== NXNY JS ===")
for asset in ("/js/index.js?v=1.08","/js/Popup.js?v=1.01","/js/jquery/jquery.cookie.js"):
    rr=get(urljoin(url,asset))
    tt=rr.content.decode('utf-8','replace')
    print("ASSET",asset)
    interesting_lines(tt,("download","down","report","viewvip","viewlogin","pdf","location","ajax","url","href"),limit=500)

print("=== NXNY CANDIDATE ENDPOINTS ===")
cands = [
    "/report/download_6345192.html",
    "/report/down_6345192.html",
    "/report/download.aspx?id=6345192",
    "/report/down.aspx?id=6345192",
    "/report/download.asp?id=6345192",
    "/report/down.asp?id=6345192",
    "/user/download.asp?id=6345192",
    "/download.asp?id=6345192",
    "/down.asp?id=6345192",
]
for p in cands:
    try:
        rr=S.get(urljoin(url,p),headers={**H,"Referer":url},timeout=20,allow_redirects=False)
        print(p,rr.status_code,rr.headers.get('location'),rr.headers.get('content-type'),len(rr.content),rr.content[:20])
    except Exception as exc:
        print(p,"ERR",repr(exc))

print("=== HIBOR FOCUSED ===")
url="https://wap.hibor.com.cn/repinfodetail_4884517.html"
r=get(url)
t=r.text
interesting_lines(t,("5000103","56ef79932778d36396799a34a8d46947","202602031415544700","download","open","checkmd5","file","pdf","docid","did=","img/2026"),limit=500)
for asset in re.findall(r'<script[^>]+src=["\']([^"\']+)',t,re.I):
    if 'DocDetailNew' in asset or 'Layout' in asset:
        rr=get(urljoin(url,asset))
        tt=rr.text
        print("HIBOR_ASSET",rr.url)
        interesting_lines(tt,("download","checkmd5","did","open","pdf","file","image","img","ajax","url"),limit=500)
