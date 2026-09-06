#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import concurrent.futures
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
BASE = "https://www.cmbi.com.hk"
ARCHIVE = BASE + "/market-stockreview?lang=en&page={}"
OUT = Path("kerry-properties-cmbi-probe.json")


def get(url: str, timeout: int = 90) -> requests.Response:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.7",
        "Referer": BASE + "/market-stockreview?lang=en",
    })
    r = s.get(url, timeout=(20, timeout), allow_redirects=True)
    r.raise_for_status()
    return r


def scan_page(page: int) -> list[dict]:
    try:
        r = get(ARCHIVE.format(page), 60)
        soup = BeautifulSoup(r.text, "html.parser")
        matches: list[dict] = []
        for a in soup.find_all("a", href=True):
            text = " ".join(a.get_text(" ", strip=True).split())
            href = urljoin(r.url, a["href"])
            norm = text.lower().replace(" ", " ")
            exact = (
                "kerry properties" in norm
                or "嘉里建設" in text
                or "嘉里建设" in text
            )
            code_ok = bool(re.search(r"\b0?683\s*hk\b", norm))
            # Avoid Kerry Logistics (636 HK) false positives.
            if exact and (code_ok or "properties" in norm or "嘉里建" in text):
                article_id_match = re.search(r"/article/(\d+)\.html", href)
                item = {
                    "archive_page": page,
                    "archive_title": text,
                    "article_url": href,
                    "article_id": int(article_id_match.group(1)) if article_id_match else None,
                }
                if item not in matches:
                    matches.append(item)
        return matches
    except Exception as exc:
        return [{"archive_page": page, "error": repr(exc)}]


def article_details(item: dict) -> dict:
    article_id = item.get("article_id")
    if not article_id:
        return {**item, "article_error": "No article ID"}
    pdfs: list[str] = []
    titles: list[str] = []
    bodies: list[str] = []
    for lang in ("en", "tc", "cn"):
        url = f"{BASE}/article/{article_id}.html?lang={lang}"
        try:
            r = get(url, 90)
            soup = BeautifulSoup(r.text, "html.parser")
            titles.append(soup.title.get_text(" ", strip=True) if soup.title else "")
            bodies.append(" ".join(soup.get_text(" ", strip=True).split())[:3000])
            for tag in soup.find_all(True):
                for attr in ("href", "src", "data-url", "data-src", "data-file", "content"):
                    value = tag.get(attr)
                    if not isinstance(value, str):
                        continue
                    value = value.strip().replace("\\/", "/")
                    if ".pdf" in value.lower():
                        u = urljoin(r.url, value)
                        u = u.split("#")[0]
                        if u not in pdfs:
                            pdfs.append(u)
            for value in re.findall(r"(?:https?:)?//[^\s\"'<>\\]+\.pdf(?:\?[^\s\"'<>\\]*)?", r.text, flags=re.I):
                u = value if value.startswith("http") else "https:" + value
                if u not in pdfs:
                    pdfs.append(u)
        except Exception as exc:
            titles.append(f"ERROR {lang}: {exc!r}")
    return {**item, "html_titles": titles, "pdf_candidates": pdfs, "body_samples": bodies}


def main() -> None:
    matches: list[dict] = []
    errors = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=14) as executor:
        future_map = {executor.submit(scan_page, page): page for page in range(1, 651)}
        for i, future in enumerate(concurrent.futures.as_completed(future_map), 1):
            rows = future.result()
            for row in rows:
                if "error" in row:
                    errors += 1
                else:
                    matches.append(row)
                    print("ARCHIVE MATCH", json.dumps(row, ensure_ascii=False), flush=True)
            if i % 50 == 0:
                print("SCANNED", i, "MATCHES", len(matches), "ERRORS", errors, flush=True)

    # Deduplicate articles and remove obvious Kerry Logistics false positives.
    dedup: dict[tuple, dict] = {}
    for item in matches:
        title = item.get("archive_title", "").lower()
        if "kerry logistics" in title or "636 hk" in title:
            continue
        key = (item.get("article_id"), item.get("article_url"))
        dedup[key] = item
    matches = list(dedup.values())
    matches.sort(key=lambda x: (x.get("article_id") or 0), reverse=True)

    details: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(article_details, item) for item in matches]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            details.append(result)
            print("ARTICLE RESULT", json.dumps(result, ensure_ascii=False), flush=True)

    details.sort(key=lambda x: (x.get("article_id") or 0), reverse=True)
    OUT.write_text(json.dumps({"match_count": len(details), "errors": errors, "reports": details}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("TOTAL", len(details), "ERRORS", errors, flush=True)


if __name__ == "__main__":
    main()
