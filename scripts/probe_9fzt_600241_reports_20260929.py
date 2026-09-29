from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urljoin

import requests

URL = "https://stock.9fzt.com/list/sh_600241_3.html"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36"
s = requests.Session()
s.trust_env = False
headers = {"User-Agent": UA, "Accept": "text/html,application/json,*/*;q=0.8", "Accept-Language": "zh-CN,zh;q=0.9"}

r = s.get(URL, headers=headers, timeout=60, allow_redirects=True)
print("STATUS", r.status_code, "FINAL", r.url, "CT", r.headers.get("content-type"), "BYTES", len(r.content), flush=True)
r.raise_for_status()
text = r.content.decode(r.encoding or r.apparent_encoding or "utf-8", errors="replace")
print("HTML_HEAD", re.sub(r"\s+", " ", text[:30000]), flush=True)

keywords = [
    "毛利率提升促业绩较快增长",
    "业绩持续下滑",
    "收入减少 利润增加",
    "主营业务未来增长缓慢",
    "迎接新周期 收获高成长",
]

for kw in keywords:
    for m in re.finditer(re.escape(kw), text, flags=re.I):
        print("CONTEXT", kw, re.sub(r"\s+", " ", text[max(0, m.start()-1500):m.end()+2500]), flush=True)

links = []
for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, flags=re.I | re.S):
    href = unescape(m.group(1))
    title = re.sub(r"<[^>]+>", "", unescape(m.group(2)))
    title = re.sub(r"\s+", " ", title).strip()
    if any(kw in title for kw in keywords) or "时代万恒" in title or "600241" in title:
        links.append({"title": title, "url": urljoin(r.url, href)})
print("LINKS", json.dumps(links, ensure_ascii=False, indent=2), flush=True)

# All script sources and inline JSON contexts.
scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', text, flags=re.I)
print("SCRIPTS", scripts, flush=True)
for src in scripts:
    full = urljoin(r.url, src)
    try:
        x = s.get(full, headers=headers, timeout=60, allow_redirects=True)
        xt = x.content.decode(x.encoding or x.apparent_encoding or "utf-8", errors="replace")
        if any(k in xt for k in ("600241", "research", "report", "研报")):
            print("SCRIPT", full, "STATUS", x.status_code, "BYTES", len(x.content), flush=True)
            for term in ("600241", "report", "research"):
                positions = [m.start() for m in re.finditer(term, xt, flags=re.I)]
                for p in positions[:10]:
                    print("SCRIPT_CONTEXT", term, re.sub(r"\s+", " ", xt[max(0,p-800):p+1800]), flush=True)
    except Exception as exc:
        print("SCRIPT_ERROR", full, repr(exc), flush=True)
