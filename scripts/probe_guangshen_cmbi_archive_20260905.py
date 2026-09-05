#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
BASE = "https://www.cmbi.com.hk"
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,zh;q=0.7"}
KEYS = ["guangshen", "guang shen", "railway (525", "525 hk", "00525", "广深铁路", "廣深鐵路"]


def fetch_page(page: int):
    url = f"{BASE}/market-stockreview?lang=en&page={page}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=(15, 60))
        if r.status_code != 200:
            return page, [], f"status {r.status_code}"
        soup = BeautifulSoup(r.text, "html.parser")
        found = []
        for a in soup.find_all("a", href=True):
            text = " ".join(a.get_text(" ", strip=True).split())
            href = urljoin(r.url, a["href"])
            hay = (text + " " + href).lower()
            if any(k.lower() in hay for k in KEYS):
                m = re.search(r"/article/(\d+)", href)
                found.append({"archive_page": page, "title": text, "article_url": href, "article_id": int(m.group(1)) if m else None})
        # Also search the raw page, then preserve nearby links.
        raw_lower = r.text.lower()
        if any(k.lower() in raw_lower for k in KEYS):
            for a in soup.find_all("a", href=True):
                text = " ".join(a.get_text(" ", strip=True).split())
                href = urljoin(r.url, a["href"])
                if re.search(r"/article/\d+", href) and any(k.lower() in (text + " " + href).lower() for k in KEYS):
                    m = re.search(r"/article/(\d+)", href)
                    found.append({"archive_page": page, "title": text, "article_url": href, "article_id": int(m.group(1)) if m else None})
        return page, found, None
    except Exception as exc:
        return page, [], repr(exc)


matches = []
errors = []
with ThreadPoolExecutor(max_workers=24) as pool:
    futures = [pool.submit(fetch_page, page) for page in range(1, 701)]
    for i, fut in enumerate(as_completed(futures), 1):
        page, found, error = fut.result()
        if found:
            matches.extend(found)
            for item in found:
                print("ARCHIVE MATCH", json.dumps(item, ensure_ascii=False), flush=True)
        if error:
            errors.append({"page": page, "error": error})
        if i % 100 == 0:
            print("SCANNED", i, "matches", len(matches), "errors", len(errors), flush=True)

# Deduplicate by article URL.
unique = {}
for item in matches:
    unique[item["article_url"]] = item
matches = list(unique.values())

def article_details(item):
    details = dict(item)
    candidates = []
    titles = []
    for lang in ("en", "tc", "cn"):
        url = re.sub(r"\?lang=.*$", "", item["article_url"]) + f"?lang={lang}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=(15, 60))
            print("ARTICLE", item.get("article_id"), lang, r.status_code, len(r.content), r.url, flush=True)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            if soup.title:
                titles.append(soup.title.get_text(" ", strip=True))
            for tag in soup.find_all(True):
                for attr in ("href", "src", "content", "data-url", "data-src"):
                    value = tag.get(attr)
                    if not isinstance(value, str):
                        continue
                    u = urljoin(r.url, value.strip())
                    if u.lower().split("?")[0].endswith(".pdf"):
                        candidates.append(u)
            for u in re.findall(r"https?://[^\s\"'<>]+\.pdf(?:\?[^\s\"'<>]*)?", r.text, flags=re.I):
                candidates.append(u)
        except Exception as exc:
            print("ARTICLE ERROR", item.get("article_id"), lang, repr(exc), flush=True)
    details["html_titles"] = list(dict.fromkeys(titles))
    details["pdf_candidates"] = list(dict.fromkeys(candidates))
    return details

with ThreadPoolExecutor(max_workers=8) as pool:
    detailed = list(pool.map(article_details, matches))

Path("guangshen-cmbi-probe.json").write_text(json.dumps({"matches": detailed, "errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
print("DONE", len(detailed), "errors", len(errors), flush=True)
for item in detailed:
    print("DETAIL", json.dumps(item, ensure_ascii=False), flush=True)
