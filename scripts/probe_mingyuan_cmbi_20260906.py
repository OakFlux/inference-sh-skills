#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.cmbi.com.hk"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"})

MATCH_TERMS = [
    "Ming Yuan Cloud", "Mingyuan Cloud", "Ming Yuan", "明源云", "明源雲", "909 HK", "0909 HK"
]
results = []
seen_articles = set()

for page in range(250, 551):
    url = f"{BASE}/market-stockreview?lang=en&page={page}"
    try:
        r = S.get(url, timeout=(20, 120))
        if r.status_code != 200:
            print("ARCHIVE STATUS", page, r.status_code, flush=True)
            continue
        text = r.text
        if not any(term.lower() in text.lower() for term in MATCH_TERMS):
            if page % 25 == 0:
                print("SCANNED", page, flush=True)
            continue
        soup = BeautifulSoup(text, "html.parser")
        for a in soup.find_all("a", href=True):
            label = " ".join(a.get_text(" ", strip=True).split())
            href = urljoin(r.url, a["href"])
            if not re.search(r"/article/\d+\.html", href):
                continue
            hay = (label + " " + href).lower()
            if not any(term.lower() in hay for term in MATCH_TERMS):
                continue
            m = re.search(r"/article/(\d+)\.html", href)
            if not m:
                continue
            article_id = int(m.group(1))
            if article_id in seen_articles:
                continue
            seen_articles.add(article_id)
            item = {"archive_page": page, "archive_title": label, "article_id": article_id, "article_url": href}
            print("ARCHIVE MATCH", json.dumps(item, ensure_ascii=False), flush=True)
            results.append(item)
    except Exception as exc:
        print("ARCHIVE ERROR", page, repr(exc), flush=True)
    time.sleep(0.08)

for item in results:
    article_id = item["article_id"]
    pdfs = []
    titles = []
    bodies = []
    for lang in ("en", "tc", "cn"):
        url = f"{BASE}/article/{article_id}.html?lang={lang}"
        try:
            r = S.get(url, timeout=(20, 120))
            print("ARTICLE", article_id, lang, r.status_code, len(r.content), r.url, flush=True)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            if soup.title:
                titles.append(soup.title.get_text(" ", strip=True))
            bodies.append(" ".join(soup.get_text(" ", strip=True).split())[:5000])
            candidates = set()
            for tag in soup.find_all(True):
                for attr in ("href", "src", "data-src", "data-url"):
                    value = tag.get(attr)
                    if isinstance(value, str) and ".pdf" in value.lower():
                        candidates.add(urljoin(r.url, value.strip()))
            for match in re.findall(r"(?:https?:)?//[^\s\"'<>]+?\.pdf(?:\?[^\s\"'<>]*)?|/[^\s\"'<>]+?\.pdf(?:\?[^\s\"'<>]*)?", r.text, flags=re.I):
                candidates.add(urljoin(r.url, match.replace("\\/", "/")))
            for candidate in candidates:
                candidate = candidate.rstrip(")]};,\"")
                if candidate not in pdfs:
                    pdfs.append(candidate)
        except Exception as exc:
            print("ARTICLE ERROR", article_id, lang, repr(exc), flush=True)
    item["html_titles"] = titles
    item["pdf_candidates"] = pdfs
    item["body_samples"] = bodies
    print("ARTICLE RESULT", json.dumps(item, ensure_ascii=False), flush=True)

out = Path("mingyuan-cmbi-probe.json")
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print("TOTAL ARTICLES", len(results), flush=True)
