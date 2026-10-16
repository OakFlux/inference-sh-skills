from __future__ import annotations

import re
from urllib.parse import urljoin

import requests

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

urls = [
    "https://www.baogaobox.com/reports/250415000055914.html",
    "https://finance.sina.com.cn/stock/stockzmt/2025-04-16/doc-inetifie3675049.shtml",
    "https://finance.sina.cn/2025-04-16/detail-inetimre0363290.d.html",
    "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/company/rptid/830853874814/index.phtml",
    "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/721664176494/index.phtml",
    "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/737374004477/index.phtml",
]

for url in urls:
    print("\n===== URL", url, flush=True)
    try:
        r = session.get(url, headers=headers, timeout=90, allow_redirects=True)
    except Exception as exc:
        print("ERROR", repr(exc), flush=True)
        continue
    print("STATUS", r.status_code, r.url, r.headers.get("content-type"), len(r.content), flush=True)
    text = r.text
    print("TITLE", (re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S).group(1).strip() if re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S) else ""), flush=True)
    attrs = re.findall(r"(?:href|src|data-src|data-original|content)\s*=\s*[\"']([^\"']+)[\"']", text, re.I)
    seen = set()
    for value in attrs:
        full = urljoin(r.url, value)
        low = full.lower()
        if full in seen:
            continue
        seen.add(full)
        if any(key in low for key in [".pdf", "download", "upload", "report", "research", "img", "image", "attachment", "file"]):
            print("ASSET", full, flush=True)
    # Also surface useful raw strings that may be escaped in JS.
    for match in re.findall(r"https?:\\?/\\?/[^\"'<>\\s]+", text):
        full = match.replace("\\/", "/")
        low = full.lower()
        if full in seen:
            continue
        if any(key in low for key in [".pdf", "download", "upload", "report", "research", "img", "image", "attachment", "file"]):
            seen.add(full)
            print("RAW_ASSET", full, flush=True)
    print("TEXT_SNIPPET", re.sub(r"\s+", " ", text[:1500]), flush=True)
