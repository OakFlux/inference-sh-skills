from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urljoin

import requests

BASE = "https://www.hibor.com.cn"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36"
s = requests.Session()
s.trust_env = False
headers = {
    "User-Agent": UA,
    "Accept": "text/html,application/json,text/javascript,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
}


def decode(r: requests.Response) -> str:
    for enc in (r.encoding, r.apparent_encoding, "utf-8", "gb18030"):
        if not enc:
            continue
        try:
            return r.content.decode(enc)
        except Exception:
            pass
    return r.content.decode("utf-8", errors="replace")


def show(label: str, r: requests.Response, limit: int = 12000) -> str:
    text = decode(r)
    print(label, "STATUS", r.status_code, "FINAL", r.url, "CT", r.headers.get("content-type"), "BYTES", len(r.content), flush=True)
    print(label + "_HEAD", re.sub(r"\s+", " ", text[:limit]), flush=True)
    return text

# 1) Internal search page probes.
search_variants = [
    ("GET", BASE + "/newweb/HuiSou/s", {"gjc": "时代万恒", "sslb": "1"}),
    ("GET", BASE + "/newweb/HuiSou/s", {"gjc": "600241", "sslb": "1"}),
    ("POST", BASE + "/newweb/HuiSou/s", {"gjc": "时代万恒", "sslb": "1"}),
]
for method, url, data in search_variants:
    try:
        if method == "GET":
            r = s.get(url, params=data, headers=headers, timeout=60, allow_redirects=True)
        else:
            r = s.post(url, data=data, headers=headers, timeout=60, allow_redirects=True)
        text = show("SEARCH_" + method + "_" + data["gjc"], r)
        hits = []
        for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, flags=re.I | re.S):
            href = unescape(m.group(1))
            title = re.sub(r"<[^>]+>", "", unescape(m.group(2)))
            title = re.sub(r"\s+", " ", title).strip()
            if any(k in title for k in ("时代万恒", "辽宁时代", "600241")):
                hits.append((title, urljoin(r.url, href)))
        print("SEARCH_HITS", hits[:50], flush=True)
    except Exception as exc:
        print("SEARCH_ERROR", method, data, repr(exc), flush=True)

# 2) Known detail and NewContent endpoint probes.
detail_url = BASE + "/docdetail_420890.html"
try:
    r = s.get(detail_url, headers=headers, timeout=60, allow_redirects=True)
    detail_text = show("DETAIL", r, limit=20000)
    ncids = re.findall(r"ncid\s*=\s*['\"]([^'\"]+)['\"]", detail_text, flags=re.I)
    print("NCIDS", ncids, flush=True)
    scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', detail_text, flags=re.I)
    print("SCRIPTS", scripts, flush=True)

    for ncid in ncids[:3]:
        endpoint = BASE + "/hiborweb/DocDetail/NewContent"
        attempts = [
            ("GET", {"ncid": ncid}),
            ("POST", {"ncid": ncid}),
            ("POST", {"id": ncid}),
            ("POST", {"ncid": ncid, "page": "1"}),
        ]
        for method, payload in attempts:
            try:
                h = dict(headers)
                h["Referer"] = r.url
                if method == "GET":
                    x = s.get(endpoint, params=payload, headers=h, timeout=60, allow_redirects=True)
                else:
                    x = s.post(endpoint, data=payload, headers=h, timeout=60, allow_redirects=True)
                xt = show("NEWCONTENT_" + method + "_" + json.dumps(payload, ensure_ascii=False), x, limit=30000)
                for pat in (
                    r'https?://[^"\'<> ]+\.pdf[^"\'<> ]*',
                    r'https?://[^"\'<> ]+(?:download|downfile)[^"\'<> ]*',
                    r'["\']([^"\']+\.pdf[^"\']*)["\']',
                    r'["\']([^"\']*(?:download|downfile)[^"\']*)["\']',
                ):
                    vals = re.findall(pat, xt, flags=re.I)
                    print("NEWCONTENT_PATTERN", pat, vals[:50], flush=True)
            except Exception as exc:
                print("NEWCONTENT_ERROR", method, payload, repr(exc), flush=True)

    # Fetch JS bundles to identify request schema and download endpoint.
    for src in scripts:
        full = urljoin(r.url, src)
        if "DocDetail" not in full and "docdetail" not in full:
            continue
        try:
            j = s.get(full, headers=headers, timeout=60, allow_redirects=True)
            jt = show("SCRIPT", j, limit=100000)
            for keyword in ("NewContent", "Download", "download", "ncid", "DocDetail"):
                positions = [m.start() for m in re.finditer(keyword, jt, flags=re.I)]
                for p in positions[:10]:
                    print("SCRIPT_CONTEXT", keyword, re.sub(r"\s+", " ", jt[max(0,p-500):p+1000]), flush=True)
        except Exception as exc:
            print("SCRIPT_ERROR", full, repr(exc), flush=True)
except Exception as exc:
    print("DETAIL_ERROR", repr(exc), flush=True)
