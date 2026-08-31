from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

URLS = [
    "https://www.sdyanbao.com/detail/886501",
    "https://www.fxbaogao.com/detail/4788440",
    "https://max.book118.com/html/2025/0701/5104021001012234.shtm",
    "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/804068768795/index.phtml",
]

session = requests.Session()
session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
)

for url in URLS:
    print("\n\n================", url, "================")
    try:
        response = session.get(url, timeout=(20, 120), allow_redirects=True)
        print("STATUS", response.status_code, "FINAL", response.url, "BYTES", len(response.content))
        response.raise_for_status()
        text = html.unescape(response.text).replace("\\/", "/")
        soup = BeautifulSoup(text, "html.parser")

        print("TITLE", soup.title.get_text(" ", strip=True) if soup.title else "")
        print("ALL LINKS")
        for tag in soup.find_all(["a", "iframe", "embed", "source", "script"], limit=5000):
            value = tag.get("href") or tag.get("src") or tag.get("data-src") or ""
            if value:
                absolute = urljoin(response.url, value)
                lower = absolute.lower()
                if any(k in lower for k in ("pdf", "download", "file", "doc", "preview", "attachment")):
                    print(tag.name, absolute, "TEXT=", tag.get_text(" ", strip=True)[:160])

        print("REGEX URLS")
        patterns = [
            r'https?://[^\"\'<>\s]+?\.pdf(?:\?[^\"\'<>\s]*)?',
            r'https?://[^\"\'<>\s]+?(?:download|attachment|preview|file)[^\"\'<>\s]*',
            r'/(?:api|download|file|preview)[^\"\'<>\s]{1,300}',
        ]
        found: list[str] = []
        for pattern in patterns:
            found.extend(re.findall(pattern, text, flags=re.I))
        for item in dict.fromkeys(found):
            print(item[:600])

        print("KEYWORD CONTEXTS")
        for keyword in ("886501", "4788440", "5104021001012234", "download", "pdf", "fileUrl", "downUrl", "attachment"):
            starts = [m.start() for m in re.finditer(re.escape(keyword), text, flags=re.I)]
            print("KEY", keyword, "COUNT", len(starts))
            for pos in starts[:12]:
                snippet = re.sub(r"\s+", " ", text[max(0, pos - 400):pos + 800])
                print(snippet[:1300])

        # Print JSON script tags separately.
        for tag in soup.find_all("script"):
            body = tag.string or tag.get_text() or ""
            if any(k.lower() in body.lower() for k in ("886501", "4788440", "510402", "download", ".pdf", "fileurl")):
                print("SCRIPT", tag.get("id"), tag.get("type"), re.sub(r"\s+", " ", body)[:5000])
    except Exception as exc:
        print("ERROR", repr(exc))
