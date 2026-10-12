from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests

DOC_ID = "4653227"
S = requests.Session()
S.trust_env = False
H = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/155 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
view_url = f"https://www.fxbaogao.com/view?id={DOC_ID}"
r = S.get(view_url, headers=H, timeout=90, allow_redirects=True)
r.encoding = r.apparent_encoding or "utf-8"
html = r.text
scripts = [urljoin(r.url, x) for x in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, re.I)]
print("VIEW", r.status_code, len(r.content), r.url, flush=True)
print("SCRIPTS", json.dumps(scripts, ensure_ascii=False), flush=True)

needles = [
    "report-image", "pageCount", "totalPage", "imageList", "download",
    "pdf", "/api/", "docId", "reportId", "view?id", "fxbaogao.com/api",
    "getReport", "report/detail", "report/view", "document",
]
for script_url in scripts:
    sr = S.get(script_url, headers={**H, "Referer": view_url}, timeout=120)
    text = sr.text
    found = {}
    for needle in needles:
        positions = [m.start() for m in re.finditer(re.escape(needle), text, re.I)]
        if positions:
            found[needle] = [
                re.sub(r"\s+", " ", text[max(0, pos-400):pos+1100])[:1500]
                for pos in positions[:5]
            ]
    if found:
        print("SCRIPT_RESULT", json.dumps({
            "url": script_url,
            "status": sr.status_code,
            "bytes": len(sr.content),
            "found": found,
        }, ensure_ascii=False), flush=True)
