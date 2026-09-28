from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

URL = "https://www.fxbaogao.com/view?id=3392613"
OUT = Path("fxbaogao_view_guoxin_health_inspection.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Referer": "https://www.fxbaogao.com/detail/3392613",
}
TOKENS = ["3392613", "report-image", "pdf", "download", "fileUrl", "pdfUrl", "reportId", "docId", "attachment", "preview", "api", "pages", "pageCount", "oss"]


def scan(text: str, base: str):
    decoded = html.unescape(text).replace("\\/", "/")
    urls = set()
    patterns = [
        r"https?://[^\s\"'<>]+",
        r"//[^\s\"'<>]+",
        r"[\"'](/[^\"']+(?:pdf|download|file|report|api|preview|image|view)[^\"']*)[\"']",
    ]
    for pattern in patterns:
        for found in re.findall(pattern, decoded, re.I):
            url = found
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = urljoin(base, url)
            url = url.rstrip("\\,;)]}")
            if any(key in url.lower() for key in ("pdf", "download", "file", "report", "api", "preview", "image", "view", "3392613")):
                urls.add(url)
    soup = BeautifulSoup(text, "html.parser")
    scripts = [urljoin(base, tag.get("src")) for tag in soup.find_all("script") if tag.get("src")]
    excerpts = {}
    for token in TOKENS:
        vals = []
        for m in re.finditer(re.escape(token), decoded, re.I):
            vals.append(decoded[max(0, m.start() - 800): m.start() + 2400])
            if len(vals) >= 20:
                break
        if vals:
            excerpts[token] = vals
    return {"urls": sorted(urls), "scripts": scripts, "excerpts": excerpts}


def main():
    session = requests.Session()
    session.headers.update(HEADERS)
    records = []
    response = session.get(URL, timeout=120, allow_redirects=True)
    print("PAGE", response.status_code, response.url, len(response.content), response.headers.get("content-type"), flush=True)
    response.raise_for_status()
    page_scan = scan(response.text, response.url)
    records.append({"kind": "page", "url": URL, "final_url": response.url, "status": response.status_code, "bytes": len(response.content), "headers": dict(response.headers), "scan": page_scan})
    print("PAGE_URLS", json.dumps(page_scan["urls"], ensure_ascii=False), flush=True)
    for token, vals in page_scan["excerpts"].items():
        for val in vals:
            print("PAGE_EXCERPT", token, json.dumps(val, ensure_ascii=False), flush=True)
    for script_url in page_scan["scripts"]:
        try:
            script = session.get(script_url, timeout=120, allow_redirects=True)
            print("SCRIPT", script.status_code, script_url, len(script.content), script.headers.get("content-type"), flush=True)
            script_scan = scan(script.text, script.url)
            records.append({"kind": "script", "url": script_url, "status": script.status_code, "bytes": len(script.content), "scan": script_scan})
            if any(token in script.text for token in ("3392613", "report-image", "download", "fileUrl", "pdfUrl", "pageCount")):
                print("SCRIPT_URLS", script_url, json.dumps(script_scan["urls"], ensure_ascii=False), flush=True)
                for token, vals in script_scan["excerpts"].items():
                    for val in vals[:8]:
                        print("SCRIPT_EXCERPT", script_url, token, json.dumps(val, ensure_ascii=False), flush=True)
        except Exception as exc:
            print("SCRIPT_ERROR", script_url, repr(exc), flush=True)
            records.append({"kind": "script", "url": script_url, "error": repr(exc)})
    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
