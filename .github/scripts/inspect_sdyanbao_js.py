from __future__ import annotations

import re

import requests

BASE = "https://www.sdyanbao.com"
ASSETS = [
    "/_nuxt/0bec462.js",
    "/_nuxt/7ff3a18.js",
    "/_nuxt/359ac1f.js",
    "/_nuxt/a94fdf1.js",
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Referer": BASE + "/detail/886501",
})

for asset in ASSETS:
    url = BASE + asset
    response = session.get(url, timeout=(20, 120))
    print("ASSET", url, "STATUS", response.status_code, "BYTES", len(response.content))
    response.raise_for_status()
    text = response.text
    print("HEAD", text[:500])
    for keyword in ("download", "online_url", "api/file", "original_id", "page_url", "unlock", "file/download", "fileDownload"):
        positions = [match.start() for match in re.finditer(re.escape(keyword), text, flags=re.I)]
        if positions:
            print("KEY", keyword, "COUNT", len(positions))
        for pos in positions[:30]:
            snippet = re.sub(r"\s+", " ", text[max(0, pos - 700):pos + 1400])
            print("CTX", snippet[:2300])
    urls = re.findall(r'["\']([^"\']*(?:download|/api/file|online)[^"\']*)["\']', text, flags=re.I)
    for value in dict.fromkeys(urls):
        print("STR", value[:1000])
