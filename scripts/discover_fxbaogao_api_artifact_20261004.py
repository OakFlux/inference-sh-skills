from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

OUT = Path("out/fxbaogao_api_discovery")
OUT.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.trust_env = False
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})

seed_urls = [
    "https://www.fxbaogao.com/detail/966932",
    "https://www.fxbaogao.com/view?id=966932",
    "https://static.fxbaogao.com/pub/js/config/production.js",
]

assets: list[str] = []
raw_files: list[dict] = []


def safe_name(url: str, index: int) -> str:
    tail = re.sub(r"[^A-Za-z0-9._-]+", "_", url.rsplit("/", 1)[-1].split("?", 1)[0])
    if not tail:
        tail = "index.html"
    return f"{index:03d}_{tail}"


def fetch(url: str) -> tuple[requests.Response | None, str]:
    try:
        response = session.get(url, timeout=(20, 180), allow_redirects=True)
        text = response.text
        print("HTTP", response.status_code, len(response.content), response.headers.get("content-type"), url, "=>", response.url)
        return response, text
    except Exception as exc:
        print("ERROR", url, repr(exc))
        return None, ""

for seed in seed_urls[:2]:
    response, text = fetch(seed)
    if response is None:
        continue
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup.find_all(["script", "link"]):
        loc = tag.get("src") or tag.get("href")
        if not loc:
            continue
        full = urljoin(response.url, loc)
        if full.endswith(".js") or ".js?" in full:
            assets.append(full)

assets.extend(seed_urls[2:])
assets = list(dict.fromkeys(assets))

# Include known app chunks even if lazy-loaded references are not visible in shell.
assets.extend([
    "https://www.fxbaogao.com/_fxbg/2609291744/js/runtime.f40e62a59d16c7ce3dad.js",
    "https://www.fxbaogao.com/_fxbg/2609291744/js/vendors~app-pages-fxbg-main-js.3e614d4b195978fb4799.chunk.js",
    "https://www.fxbaogao.com/_fxbg/2609291744/js/app-pages-fxbg-main-js.4e85af91191f3f7c70f1.chunk.js",
])
assets = list(dict.fromkeys(assets))

for index, url in enumerate(assets, 1):
    response, text = fetch(url)
    if response is None:
        continue
    filename = safe_name(response.url, index)
    path = OUT / filename
    path.write_bytes(response.content)
    raw_files.append({
        "url": url,
        "final_url": response.url,
        "status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "bytes": len(response.content),
        "path": str(path),
    })

patterns = {
    "absolute_urls": r"https?://[^\\\"'<>\s]+",
    "api_paths": r"[\\\"']((?:/|https?://)[^\\\"']*(?:api|report|detail|download|preview|view|file|image|pdf)[^\\\"']*)[\\\"']",
    "quoted_paths": r"[\\\"']([^\\\"']{1,220})[\\\"']",
}
keywords = [
    "report-image", "docId", "reportId", "pageCount", "page_count", "download",
    "preview", "detail", "view", "pdf", "fileUrl", "file_url", "original",
    "mofoun", "api.fxbaogao", "static.fxbaogao", "getReport", "reportDetail",
]

found_urls: set[str] = set()
found_paths: set[str] = set()
contexts: list[dict] = []

for meta in raw_files:
    path = Path(meta["path"])
    text = path.read_text("utf-8", errors="replace")
    for match in re.findall(patterns["absolute_urls"], text, flags=re.I):
        if any(key.lower() in match.lower() for key in ["fxbaogao", "api", "report", "pdf", "image", "file"]):
            found_urls.add(match.rstrip("),.;"))
    for match in re.findall(patterns["api_paths"], text, flags=re.I):
        found_paths.add(match)
    for match in re.findall(patterns["quoted_paths"], text, flags=re.I):
        if any(key.lower() in match.lower() for key in ["api", "report", "detail", "download", "preview", "view", "pdf", "file", "image"]):
            if len(match) <= 220:
                found_paths.add(match)
    lower = text.lower()
    for keyword in keywords:
        start = 0
        count = 0
        while count < 25:
            idx = lower.find(keyword.lower(), start)
            if idx < 0:
                break
            snippet = text[max(0, idx - 800): idx + 1800]
            contexts.append({
                "file": path.name,
                "keyword": keyword,
                "offset": idx,
                "snippet": snippet,
            })
            start = idx + len(keyword)
            count += 1

result = {
    "raw_files": raw_files,
    "absolute_urls": sorted(found_urls),
    "candidate_paths": sorted(found_paths),
    "contexts": contexts,
}
(OUT / "discovery.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

with (OUT / "discovery.txt").open("w", encoding="utf-8") as handle:
    handle.write("ABSOLUTE URLS\n")
    for item in sorted(found_urls):
        handle.write(item + "\n")
    handle.write("\nCANDIDATE PATHS\n")
    for item in sorted(found_paths):
        handle.write(item + "\n")
    handle.write("\nCONTEXTS\n")
    for item in contexts:
        handle.write(f"\n### {item['file']} | {item['keyword']} | {item['offset']}\n")
        handle.write(item["snippet"] + "\n")

print("DISCOVERY_FILES", len(raw_files), "URLS", len(found_urls), "PATHS", len(found_paths), "CONTEXTS", len(contexts))
