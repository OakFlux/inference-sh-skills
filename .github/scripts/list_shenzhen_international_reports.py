from __future__ import annotations

import html
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

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


def fetch_text(url: str) -> tuple[str, str]:
    response = session.get(url, timeout=(20, 120), allow_redirects=True)
    print("FETCH", response.status_code, len(response.content), response.url)
    response.raise_for_status()
    return html.unescape(response.text).replace("\\/", "/"), response.url


print("=== SDYANBAO PAGE AND JS ===")
page, final = fetch_text("https://www.sdyanbao.com/detail/886501")
soup = BeautifulSoup(page, "html.parser")
for tag in soup.find_all("script", src=True):
    js_url = urljoin(final, tag["src"])
    try:
        js, js_final = fetch_text(js_url)
    except Exception as exc:
        print("JS_ERROR", js_url, repr(exc))
        continue
    for keyword in ("download", "online_url", "original_id", "unlock", "page_url", "report/download", "/download"):
        positions = [m.start() for m in re.finditer(re.escape(keyword), js, flags=re.I)]
        if positions:
            print("JS", js_final, "KEY", keyword, "COUNT", len(positions))
            for pos in positions[:20]:
                print(re.sub(r"\s+", " ", js[max(0, pos - 500):pos + 1000])[:1600])

print("\n=== SDYANBAO PUBLIC FILE CANDIDATES ===")
candidates = [
    "https://oss.sdyanbao.com/page/2025/5/7/1192119.pdf",
    "https://oss.sdyanbao.com/page/2025/5/7/1192119/1192119.pdf",
    "https://oss.sdyanbao.com/pdf/2025/5/7/1192119.pdf",
    "https://oss.sdyanbao.com/file/2025/5/7/1192119.pdf",
    "https://oss.sdyanbao.com/report/2025/5/7/1192119.pdf",
    "https://oss.sdyanbao.com/pdf/1192119.pdf",
    "https://oss.sdyanbao.com/file/1192119.pdf",
    "https://oss.sdyanbao.com/2025/5/7/1192119.pdf",
]
for url in candidates:
    try:
        response = session.get(url, headers={"Range": "bytes=0-31"}, timeout=(15, 60), allow_redirects=True)
        print(url, response.status_code, response.headers.get("Content-Type"), response.headers.get("Content-Length"), response.content[:16])
    except Exception as exc:
        print(url, "ERROR", repr(exc))

print("\n=== FXBAOGAO DETAIL/VIEW ===")
for url in (
    "https://www.fxbaogao.com/detail/4788440",
    "https://www.fxbaogao.com/view?id=4788440",
    "https://m.fxbaogao.com/detail/4788440",
    "https://m.fxbaogao.com/view?id=4788440",
):
    try:
        text, final_url = fetch_text(url)
    except Exception as exc:
        print("PAGE_ERROR", url, repr(exc))
        continue
    print("PAGE", final_url)
    for keyword in ("4788440", "report-image", "download", "fileUrl", "pdfUrl", "sourceUrl", "__NEXT_DATA__"):
        positions = [m.start() for m in re.finditer(re.escape(keyword), text, flags=re.I)]
        print("KEY", keyword, len(positions))
        for pos in positions[:15]:
            print(re.sub(r"\s+", " ", text[max(0, pos - 500):pos + 1200])[:1800])
    for match in re.findall(r'https?://[^\"\'<>\s]+', text, flags=re.I):
        lower = match.lower()
        if any(k in lower for k in ("4788440", ".pdf", "report-image", "download")):
            print("URL", match[:1000])

print("\n=== FXBAOGAO PAGE IMAGES ===")
for page_no in range(1, 15):
    url = f"https://public.fxbaogao.com/report-image/2025/04/17/4788440-{page_no}.png"
    try:
        response = session.get(url, headers={"Range": "bytes=0-31"}, timeout=(15, 60), allow_redirects=True)
        print(page_no, response.status_code, response.headers.get("Content-Type"), response.headers.get("Content-Length"), response.content[:16])
    except Exception as exc:
        print(page_no, "ERROR", repr(exc))
