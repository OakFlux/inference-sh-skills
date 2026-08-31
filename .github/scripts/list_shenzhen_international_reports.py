from __future__ import annotations

import html
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

PAGE_URL = "https://www.sdyanbao.com/detail/886501"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36"
)

session = requests.Session()
session.headers.update(
    {
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
)

response = session.get(PAGE_URL, timeout=(30, 180), allow_redirects=True)
print("PAGE", response.status_code, len(response.content), response.url)
response.raise_for_status()
text = html.unescape(response.text).replace("\\/", "/")
soup = BeautifulSoup(text, "html.parser")

script_urls = [urljoin(response.url, tag["src"]) for tag in soup.find_all("script", src=True)]
print("SCRIPT_COUNT", len(script_urls))
for url in script_urls:
    print("SCRIPT_URL", url)

needles = (
    "baseURL",
    "baseUrl",
    "api.sdyanbao.com",
    "/report/detail/",
    "report/detail",
    "/report/search",
    "/report/list",
    "/report/index",
    "/search",
    "page_url",
    "original_id",
)

all_paths: set[str] = set()
for url in script_urls:
    try:
        js_response = session.get(url, timeout=(30, 180), allow_redirects=True)
        print("FETCH_JS", js_response.status_code, len(js_response.content), js_response.url)
        js_response.raise_for_status()
        js = js_response.text
    except Exception as exc:
        print("JS_ERROR", url, repr(exc))
        continue

    matched = False
    for needle in needles:
        positions = [m.start() for m in re.finditer(re.escape(needle), js, flags=re.I)]
        if not positions:
            continue
        matched = True
        print("\nFILE", url, "NEEDLE", needle, "COUNT", len(positions))
        for pos in positions[:30]:
            snippet = re.sub(r"\s+", " ", js[max(0, pos - 1000):pos + 2500])
            print("SNIPPET", snippet[:3800])

    # Extract likely relative API paths and full API URLs.
    for match in re.findall(r'["\'](/[^"\']{1,160})["\']', js):
        if any(token in match.lower() for token in ("report", "search", "download", "user", "category", "keyword")):
            all_paths.add(match)
    for match in re.findall(r'https?://[^"\'<>\s]{1,300}', js, flags=re.I):
        if "sdyanbao" in match.lower() or "api" in match.lower():
            all_paths.add(match)
    if matched:
        print("MATCHED_BUNDLE", url)

print("\n=== UNIQUE LIKELY ROUTES ===")
for path in sorted(all_paths):
    print(path)

# Inspect Nuxt state and config embedded in HTML itself.
for needle in needles:
    positions = [m.start() for m in re.finditer(re.escape(needle), text, flags=re.I)]
    if positions:
        print("\nHTML NEEDLE", needle, "COUNT", len(positions))
        for pos in positions[:20]:
            print(re.sub(r"\s+", " ", text[max(0, pos - 800):pos + 2200])[:3200])
