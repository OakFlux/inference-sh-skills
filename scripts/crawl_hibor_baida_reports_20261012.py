from __future__ import annotations

import concurrent.futures
import re
from datetime import date

import requests

KEYWORDS = ("百大集团", "600865")
HOST_PATTERNS = [
    "https://www.hibor.com.cn/archiver_houtai/{ym}.html",
    "https://p.hibor.com.cn/Archiver/{ym}.html",
    "https://p.hibor.com.cn/archiver/{ym}.html",
]
YEARS = range(2004, 2027)
MONTHS = range(1, 13)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})


def fetch(url: str) -> tuple[str, int, str]:
    try:
        response = session.get(url, timeout=(10, 30), allow_redirects=True)
        text = response.text if response.status_code == 200 else ""
        return url, response.status_code, text
    except Exception as exc:
        return url, -1, repr(exc)

urls = [pattern.format(ym=f"{year}{month:02d}") for year in YEARS for month in MONTHS for pattern in HOST_PATTERNS]

matches: list[tuple[str, str]] = []
with concurrent.futures.ThreadPoolExecutor(max_workers=18) as executor:
    for url, status, text in executor.map(fetch, urls):
        if status != 200:
            continue
        normalized = re.sub(r"\s+", " ", text)
        if not any(keyword in normalized for keyword in KEYWORDS):
            continue
        print("MATCH_PAGE", url, "bytes", len(text.encode('utf-8')), flush=True)
        for keyword in KEYWORDS:
            start = 0
            while True:
                index = normalized.find(keyword, start)
                if index < 0:
                    break
                snippet = normalized[max(0, index - 350): index + 500]
                print("SNIPPET", keyword, snippet, flush=True)
                matches.append((url, snippet))
                start = index + len(keyword)

print("TOTAL_MATCH_SNIPPETS", len(matches), flush=True)
