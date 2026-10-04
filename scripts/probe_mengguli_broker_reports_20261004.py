from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests

URLS = [
    "https://wap.hibor.com.cn/repinfodetail_4884517.html",
    "https://www.sdyanbao.com/detail/943276",
    "https://www.sdyanbao.com/detail/970423",
    "https://www.nxny.com/report/view_6345192.html",
    "https://www.baogaobox.com/reports/251112000082838.html",
    "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/lastest/rptid/835629288440/index.phtml",
]

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

URL_RE = re.compile(r'''(?:https?:)?//[^\s"'<>]+|(?:src|href|data-src|data-original|url|file|pdfUrl|downloadUrl)\s*[:=]\s*["']([^"']+)["']''', re.I)


def fetch(url: str) -> None:
    print("\n" + "=" * 100)
    print("FETCH", url)
    try:
        r = session.get(url, headers=headers, timeout=40, allow_redirects=True)
        print("STATUS", r.status_code, "FINAL", r.url, "TYPE", r.headers.get("content-type"), "LEN", len(r.content))
        print("HEADERS", json.dumps(dict(r.headers), ensure_ascii=False, indent=2)[:4000])
        text = r.text
        print("TEXT_HEAD", text[:3000].replace("\n", " "))
        print("TEXT_TAIL", text[-3000:].replace("\n", " "))
        links = set()
        for match in URL_RE.finditer(text):
            raw = match.group(1) or match.group(0)
            raw = raw.strip('"\' )};,')
            if raw.startswith("//"):
                raw = "https:" + raw
            elif raw.startswith("/"):
                raw = urljoin(r.url, raw)
            if any(k in raw.lower() for k in ("pdf", "gif", "jpg", "jpeg", "png", "download", "checkmd5", "report", "file", "preview", "viewer", "img")):
                links.add(raw)
        print("INTERESTING_LINKS")
        for item in sorted(links):
            print(item)
        for pattern in [r"2026\d{14,}", r"repinfodetail_\d+", r"view_\d+", r"rptid/\d+"]:
            print("PATTERN", pattern, sorted(set(re.findall(pattern, text)))[:100])
    except Exception as exc:
        print("ERROR", repr(exc))


for u in URLS:
    fetch(u)
