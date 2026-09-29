from __future__ import annotations

import re
from urllib.parse import urljoin

import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36"
s = requests.Session(); s.trust_env = False
headers = {"User-Agent": UA, "Accept": "text/javascript,application/javascript,text/html,*/*"}
base = "https://www.fxbaogao.com/rp?keywords=%E6%97%B6%E4%BB%A3%E4%B8%87%E6%81%92&order=2&nop=-1"
r = s.get(base, headers=headers, timeout=60)
text = r.content.decode(r.encoding or r.apparent_encoding or "utf-8", errors="replace")
scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', text, flags=re.I)
print("SCRIPTS", scripts, flush=True)
for src in scripts:
    full = urljoin(r.url, src)
    try:
        x = s.get(full, headers=headers, timeout=90)
        xt = x.content.decode(x.encoding or x.apparent_encoding or "utf-8", errors="replace")
        print("SCRIPT", full, x.status_code, len(x.content), flush=True)
        if not any(k in xt for k in ("api.fxbaogao.com", "mofoun", "keywords", "docId", "report")):
            continue
        urls = sorted(set(re.findall(r'https?://[^"\'` ]+', xt)))
        print("URLS", urls[:200], flush=True)
        for keyword in ("api.fxbaogao.com", "mofoun", "keywords", "docId", "/rp", "report/list", "search"):
            positions = [m.start() for m in re.finditer(re.escape(keyword), xt, flags=re.I)]
            for p in positions[:30]:
                ctx = re.sub(r"\s+", " ", xt[max(0,p-1500):p+4000])
                print("CONTEXT", keyword, ctx, flush=True)
    except Exception as exc:
        print("ERROR", full, repr(exc), flush=True)
