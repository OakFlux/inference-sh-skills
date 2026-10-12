from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests

URLS = [
    "https://www.hibor.com.cn/docdetail_1692114.html",
    "https://www.hibor.com.cn/docdetail_1694746.html",
    "https://www.hibor.com.cn/docdetail_1718411.html",
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
})

for url in URLS:
    print("===", url, flush=True)
    r = session.get(url, timeout=(20, 90), allow_redirects=True)
    print("PAGE", r.status_code, r.url, len(r.content), flush=True)
    text = r.text
    ncid_match = re.search(r"var\s+ncid\s*=\s*'([^']+)'", text)
    ncid = ncid_match.group(1) if ncid_match else ""
    print("NCID", ncid, flush=True)
    endpoint = urljoin(r.url, "/hiborweb/DocDetail/NewContent")
    variants = [
        ("GET_QUERY_NCID", "GET", {"params": {"ncid": ncid}}),
        ("POST_FORM_NCID", "POST", {"data": {"ncid": ncid}}),
        ("POST_JSON_NCID", "POST", {"json": {"ncid": ncid}}),
        ("POST_FORM_ID", "POST", {"data": {"id": ncid}}),
        ("POST_FORM_NCID_CAP", "POST", {"data": {"Ncid": ncid}}),
    ]
    for name, method, kwargs in variants:
        try:
            rr = session.request(method, endpoint, headers={"Referer": r.url}, timeout=(20, 90), allow_redirects=True, **kwargs)
            prefix = re.sub(r"\s+", " ", rr.text)[:2500]
            print(name, rr.status_code, rr.headers.get("content-type"), len(rr.content), rr.url, flush=True)
            print("BODY", prefix, flush=True)
        except Exception as exc:
            print(name, "ERROR", repr(exc), flush=True)

# Fetch JavaScript bundle and print lines around NewContent/$.ajax
js_url = "https://www.hibor.com.cn/hiborweb/DocDetailNew/js?v=JhJG5MdT9wDoAQX8-xy-bc9qho_6DU5Ailv07PYCEEg1"
try:
    j = session.get(js_url, timeout=(20, 90))
    print("JS", j.status_code, j.headers.get("content-type"), len(j.content), flush=True)
    jt = j.text
    for needle in ["NewContent", "newContentUrl", "ncid", "ajax", "download", "DownLoad"]:
        positions = [m.start() for m in re.finditer(needle, jt, flags=re.I)]
        print("JS_NEEDLE", needle, positions[:20], flush=True)
        for p in positions[:5]:
            print("JS_SNIPPET", needle, jt[max(0, p-600):p+1200], flush=True)
except Exception as exc:
    print("JS_ERROR", repr(exc), flush=True)
