from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urljoin

import requests

URL = "https://www.fxbaogao.com/detail/1623958"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36"
s = requests.Session()
s.trust_env = False
headers = {"User-Agent": UA, "Accept": "text/html,application/json,*/*;q=0.8", "Accept-Language": "zh-CN,zh;q=0.9"}

r = s.get(URL, headers=headers, timeout=90, allow_redirects=True)
print("STATUS", r.status_code, "FINAL", r.url, "CT", r.headers.get("content-type"), "BYTES", len(r.content), flush=True)
r.raise_for_status()
text = r.content.decode(r.encoding or r.apparent_encoding or "utf-8", errors="replace")
print("HEAD", re.sub(r"\s+", " ", text[:50000]), flush=True)

for pat in [
    r'https?://[^"\'<> ]+\.pdf[^"\'<> ]*',
    r'["\']([^"\']+\.pdf[^"\']*)["\']',
    r'(?:pdfUrl|fileUrl|downloadUrl|attachmentUrl|sourceUrl|reportUrl)["\']?\s*[:=]\s*["\']([^"\']+)["\']',
    r'https?://[^"\'<> ]+(?:download|file|attachment)[^"\'<> ]*',
]:
    print("PATTERN", pat, re.findall(pat, text, flags=re.I)[:100], flush=True)

next_match = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', text, flags=re.I | re.S)
if next_match:
    try:
        data = json.loads(unescape(next_match.group(1)))
        print("NEXT_DATA", json.dumps(data, ensure_ascii=False, indent=2)[:100000], flush=True)
    except Exception as exc:
        print("NEXT_ERROR", repr(exc), flush=True)

scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', text, flags=re.I)
print("SCRIPTS", scripts, flush=True)
for src in scripts:
    full = urljoin(r.url, src)
    try:
        x = s.get(full, headers=headers, timeout=90, allow_redirects=True)
        xt = x.content.decode(x.encoding or x.apparent_encoding or "utf-8", errors="replace")
        if not any(term.lower() in xt.lower() for term in ("pdf", "download", "detail", "report", "attachment", "fileurl")):
            continue
        print("SCRIPT", full, "STATUS", x.status_code, "BYTES", len(x.content), flush=True)
        for term in ("pdf", "download", "attachment", "fileUrl", "reportUrl", "detail"):
            for m in list(re.finditer(term, xt, flags=re.I))[:20]:
                print("SCRIPT_CONTEXT", term, re.sub(r"\s+", " ", xt[max(0,m.start()-1000):m.start()+3000]), flush=True)
    except Exception as exc:
        print("SCRIPT_ERROR", full, repr(exc), flush=True)
