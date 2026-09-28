from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

URL = "https://www.fxbaogao.com/detail/3392613"
OUT = Path("fxbaogao_guoxin_health_inspection.json")
HTML = Path("fxbaogao_guoxin_health_page.html")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}


def scan(text: str, base: str):
    decoded = html.unescape(text).replace("\\/", "/")
    urls = set()
    patterns = [
        r"https?://[^\s\"'<>]+",
        r"//[^\s\"'<>]+",
        r"[\"'](/[^\"']+(?:pdf|download|file|report|api|preview|image)[^\"']*)[\"']",
    ]
    for pattern in patterns:
        for found in re.findall(pattern, decoded, re.I):
            url = found
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = urljoin(base, url)
            url = url.rstrip("\\,;)]}")
            if any(key in url.lower() for key in ("pdf", "download", "file", "report", "api", "preview", "image", "3392613")):
                urls.add(url)
    soup = BeautifulSoup(text, "html.parser")
    scripts = [urljoin(base, tag.get("src")) for tag in soup.find_all("script") if tag.get("src")]
    next_data = ""
    nd = soup.find("script", id="__NEXT_DATA__")
    if nd:
        next_data = nd.get_text()
    excerpts = {}
    for token in ["3392613", "pdf", "download", "fileUrl", "pdfUrl", "reportId", "attachment", "preview", "api", "pages"]:
        vals = []
        for m in re.finditer(re.escape(token), decoded, re.I):
            vals.append(decoded[max(0, m.start() - 500): m.start() + 1600])
            if len(vals) >= 12:
                break
        if vals:
            excerpts[token] = vals
    return {"urls": sorted(urls), "scripts": scripts, "next_data": next_data, "excerpts": excerpts}


def main():
    session = requests.Session()
    session.headers.update(HEADERS)
    response = session.get(URL, timeout=120, allow_redirects=True)
    print("PAGE", response.status_code, response.url, len(response.content), response.headers.get("content-type"), flush=True)
    response.raise_for_status()
    HTML.write_bytes(response.content)
    record = {
        "url": URL,
        "final_url": response.url,
        "status": response.status_code,
        "bytes": len(response.content),
        "content_type": response.headers.get("content-type"),
        "headers": dict(response.headers),
        "scan": scan(response.text, response.url),
    }
    print("URLS", json.dumps(record["scan"]["urls"], ensure_ascii=False), flush=True)
    print("NEXT_DATA", record["scan"]["next_data"][:10000], flush=True)
    for token, excerpts in record["scan"]["excerpts"].items():
        for excerpt in excerpts:
            print("EXCERPT", token, json.dumps(excerpt, ensure_ascii=False), flush=True)
    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
