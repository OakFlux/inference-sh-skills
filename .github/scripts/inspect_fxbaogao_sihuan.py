from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from urllib.parse import urljoin

import requests

IDS = [5653263, 5454571, 5259212]
URLS = []
for rid in IDS:
    URLS.extend(
        [
            f"https://www.fxbaogao.com/detail/{rid}",
            f"https://www.fxbaogao.com/view?id={rid}",
            f"https://m.fxbaogao.com/detail/{rid}",
            f"https://m.fxbaogao.com/view?id={rid}",
        ]
    )

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


def walk(value, path="root") -> Iterable[tuple[str, object]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")
    else:
        yield path, value


script_urls: set[str] = set()

for url in URLS:
    print("\n\n================", url, "================")
    try:
        response = session.get(url, timeout=(20, 180), allow_redirects=True)
        print(
            "STATUS", response.status_code,
            "FINAL", response.url,
            "BYTES", len(response.content),
            "TYPE", response.headers.get("content-type"),
        )
        response.raise_for_status()
        text = html.unescape(response.text).replace("\\/", "/")
        print("HEAD", re.sub(r"\s+", " ", text[:500]))

        for match in re.findall(r"https?://[^\"'<>\\\s]+", text, flags=re.I):
            cleaned = match.rstrip("),;]}")
            if any(
                marker in cleaned.lower()
                for marker in (
                    ".pdf", "download", "file", "report", "oss", "source", "origin",
                    "api/", "api.", "viewer", "attachment", "doc", "static",
                )
            ):
                print("URL", cleaned[:1200])

        for match in re.findall(r"(?:href|src)=[\"']([^\"']+)[\"']", text, flags=re.I):
            absolute = urljoin(response.url, match)
            if absolute.endswith(".js") or "/_next/static/" in absolute:
                script_urls.add(absolute)
                print("SCRIPT_URL", absolute)
            if any(
                marker in absolute.lower()
                for marker in ("download", ".pdf", "/api/", "file", "view", "report")
            ):
                print("ATTR_URL", absolute[:1200])

        next_match = re.search(
            r'<script[^>]+id=[\"\']__NEXT_DATA__[\"\'][^>]*>(.*?)</script>',
            response.text,
            flags=re.S | re.I,
        )
        if next_match:
            print("NEXT_DATA_FOUND", len(next_match.group(1)))
            try:
                payload = json.loads(html.unescape(next_match.group(1)))
                for path, value in walk(payload):
                    value_text = str(value)
                    low = value_text.lower()
                    if any(
                        marker in low
                        for marker in (
                            ".pdf", "download", "file", "report", "oss", "source", "origin",
                            "5653263", "5454571", "5259212", "online_url", "url", "path",
                        )
                    ):
                        print("NEXT", path, repr(value)[:3000])
            except Exception as exc:
                print("NEXT_DATA_ERROR", repr(exc))

        for keyword in (
            "download", "pdf", "fileUrl", "file_url", "online_url", "originUrl",
            "sourceUrl", "oss", "report-image", "detailId", "reportId", "api/",
        ):
            positions = [m.start() for m in re.finditer(re.escape(keyword), text, flags=re.I)]
            if positions:
                print("KEY", keyword, "COUNT", len(positions))
            for pos in positions[:12]:
                snippet = re.sub(r"\s+", " ", text[max(0, pos - 500): pos + 1400])
                print("CTX", snippet[:2000])
    except Exception as exc:
        print("ERROR", repr(exc))

print("\n\n================ JS ASSETS ================")
for url in sorted(script_urls):
    print("\nASSET", url)
    try:
        response = session.get(url, timeout=(20, 180), allow_redirects=True)
        print("STATUS", response.status_code, "BYTES", len(response.content), "FINAL", response.url)
        response.raise_for_status()
        text = response.text.replace("\\/", "/")
        if len(text) > 2_500_000:
            print("SKIP_LARGE_ASSET")
            continue
        interesting = False
        for keyword in (
            "download", "report-image", ".pdf", "api/", "fileUrl", "online_url",
            "original", "source", "oss", "detail", "view?id", "report/detail",
        ):
            positions = [m.start() for m in re.finditer(re.escape(keyword), text, flags=re.I)]
            if positions:
                interesting = True
                print("KEY", keyword, "COUNT", len(positions))
            for pos in positions[:20]:
                snippet = re.sub(r"\s+", " ", text[max(0, pos - 700): pos + 1800])
                print("CTX", snippet[:2600])
        if not interesting:
            print("NO_INTERESTING_KEYS")
    except Exception as exc:
        print("ERROR", repr(exc))
