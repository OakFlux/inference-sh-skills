from __future__ import annotations

import html
import re
import time
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
        "Referer": "https://www.sdyanbao.com/detail/886501",
    }
)

DETAIL_URL = "https://www.sdyanbao.com/detail/886501"
PAGE_BASE = "https://oss.sdyanbao.com/page/2025/5/7/1192119"


def get(url: str, *, timeout: tuple[int, int] = (30, 150)) -> requests.Response:
    errors: list[str] = []
    for attempt in range(1, 6):
        try:
            response = session.get(url, timeout=timeout, allow_redirects=True)
            print("GET", attempt, response.status_code, len(response.content), response.url)
            return response
        except Exception as exc:
            errors.append(f"attempt {attempt}: {exc}")
            time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to fetch {url}: {' | '.join(errors)}")


print("=== PROBE KNOWN PAGE DIRECTORY ===")
patterns = [
    "{n}.png",
    "{n}.jpg",
    "{n}.jpeg",
    "{n}.webp",
    "page-{n}.png",
    "{n}/index.png",
]
for pattern in patterns:
    print("\nPATTERN", pattern)
    valid_count = 0
    for page_no in range(0, 14):
        url = f"{PAGE_BASE}/{pattern.format(n=page_no)}"
        try:
            response = session.get(
                url,
                headers={"Range": "bytes=0-255", "Referer": DETAIL_URL},
                timeout=(12, 60),
                allow_redirects=True,
            )
            content_type = response.headers.get("Content-Type", "")
            magic = response.content[:16]
            valid = (
                response.status_code in (200, 206)
                and "image" in content_type.lower()
                and magic.startswith((b"\x89PNG", b"\xff\xd8\xff", b"RIFF"))
            )
            print(
                page_no,
                response.status_code,
                content_type,
                response.headers.get("Content-Length"),
                repr(magic),
                "VALID", valid,
            )
            if valid:
                valid_count += 1
        except Exception as exc:
            print(page_no, "ERROR", repr(exc))
    print("VALID_COUNT", valid_count)

print("\n=== FETCH DETAIL PAGE ROBUSTLY ===")
try:
    response = get(DETAIL_URL, timeout=(60, 240))
    response.raise_for_status()
    text = html.unescape(response.text).replace("\\/", "/")
    soup = BeautifulSoup(text, "html.parser")
    print("TITLE", soup.title.get_text(" ", strip=True) if soup.title else "")
    print("HTML_BYTES", len(text.encode("utf-8")))

    script_urls: list[str] = []
    for script in soup.find_all("script", src=True):
        script_urls.append(urljoin(response.url, script["src"]))
    print("SCRIPT_URLS", script_urls)

    for keyword in (
        "page_url",
        "online_url",
        "share_url",
        "original_id",
        "page_count",
        "1192119",
        "886501",
        "download",
    ):
        positions = [m.start() for m in re.finditer(re.escape(keyword), text, flags=re.I)]
        print("HTML_KEY", keyword, "COUNT", len(positions))
        for pos in positions[:10]:
            print(re.sub(r"\s+", " ", text[max(0, pos - 500):pos + 1500])[:2200])

    for script_url in script_urls:
        try:
            js_response = get(script_url, timeout=(30, 180))
            if js_response.status_code != 200 or len(js_response.content) < 500:
                continue
            js = js_response.text
            hit = False
            for keyword in (
                "page_url",
                "online_url",
                "share_url",
                "original_id",
                "page_count",
                "/download",
                "downloadReport",
                "report/download",
                "oss.sdyanbao.com/page",
            ):
                positions = [m.start() for m in re.finditer(re.escape(keyword), js, flags=re.I)]
                if positions:
                    hit = True
                    print("JS", script_url, "KEY", keyword, "COUNT", len(positions))
                    for pos in positions[:20]:
                        print(re.sub(r"\s+", " ", js[max(0, pos - 700):pos + 1800])[:2600])
            if hit:
                print("JS_HIT_FILE", script_url, "SIZE", len(js))
        except Exception as exc:
            print("JS_ERROR", script_url, repr(exc))
except Exception as exc:
    print("DETAIL_ERROR", repr(exc))

print("\n=== DIRECT KNOWN NUXT BUNDLES ===")
for js_path in (
    "/_nuxt/a94fdf1.js",
    "/_nuxt/359ac1f.js",
    "/_nuxt/7ff3a18.js",
    "/_nuxt/0bec462.js",
):
    js_url = "https://www.sdyanbao.com" + js_path
    try:
        response = get(js_url, timeout=(30, 180))
        if response.status_code != 200:
            continue
        js = response.text
        print("BUNDLE", js_url, "SIZE", len(js))
        for keyword in (
            "page_url",
            "online_url",
            "share_url",
            "original_id",
            "page_count",
            "/download",
            "downloadReport",
            "report/download",
            "oss.sdyanbao.com/page",
        ):
            positions = [m.start() for m in re.finditer(re.escape(keyword), js, flags=re.I)]
            if positions:
                print("KEY", keyword, "COUNT", len(positions))
                for pos in positions[:25]:
                    print(re.sub(r"\s+", " ", js[max(0, pos - 700):pos + 1800])[:2600])
    except Exception as exc:
        print("BUNDLE_ERROR", js_url, repr(exc))
