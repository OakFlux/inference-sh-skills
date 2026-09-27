from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

SEARCH = "https://www1.hkexnews.hk/search/titlesearch.xhtml"
STOCK_ID = "224837"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_rows(html: str, base: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("tr"):
        link = tr.select_one("a[href*='.pdf'],a[href*='.PDF']")
        if not link:
            continue
        text = compact(tr.get_text(" ", strip=True))
        href = urljoin(base, link.get("href", ""))
        if "ANNUAL REPORT" in text.upper() or "INTERIM REPORT" in text.upper():
            rows.append({"text": text, "url": href})
    return rows


with httpx.Client(headers=HEADERS, follow_redirects=True, http2=True, timeout=120) as client:
    warm = client.get(SEARCH, params={"lang": "EN", "category": "0", "market": "SEHK", "stockId": STOCK_ID})
    print("WARM", warm.status_code, len(warm.content), str(warm.url), flush=True)

    tests = []
    for fiscal_year in range(2020, 2024):
        release_year = fiscal_year + 1
        title = f"ANNUAL REPORT {fiscal_year}"
        variants = [
            {
                "name": f"post-title-{fiscal_year}",
                "method": "POST",
                "data": {
                    "lang": "EN", "stockId": STOCK_ID, "sortDir": "desc", "sortByOptions": "DateTime",
                    "category": "0", "market": "SEHK", "from": f"{release_year}0101", "to": f"{release_year}1231",
                    "page": "1", "searchType": "1", "documentType": "-1", "title": title,
                    "t1code": "-2", "t2Gcode": "-2", "t2code": "-2", "rowRange": "500", "MB-Daterange": "0",
                },
            },
            {
                "name": f"get-title-{fiscal_year}",
                "method": "GET",
                "params": {
                    "lang": "EN", "stockId": STOCK_ID, "category": "0", "market": "SEHK",
                    "from": f"{release_year}0101", "to": f"{release_year}1231", "title": title,
                    "searchType": "1", "documentType": "-1", "rowRange": "500",
                },
            },
            {
                "name": f"post-narrow-{fiscal_year}",
                "method": "POST",
                "data": {
                    "lang": "EN", "stockId": STOCK_ID, "sortDir": "desc", "sortByOptions": "DateTime",
                    "category": "0", "market": "SEHK", "from": f"{release_year}0301", "to": f"{release_year}0630",
                    "page": "1", "searchType": "1", "documentType": "-1", "title": "ANNUAL REPORT",
                    "t1code": "-2", "t2Gcode": "-2", "t2code": "-2", "rowRange": "500", "MB-Daterange": "0",
                },
            },
        ]
        tests.extend(variants)

    for test in tests:
        try:
            if test["method"] == "POST":
                response = client.post(SEARCH, data=test["data"])
            else:
                response = client.get(SEARCH, params=test["params"])
            rows = parse_rows(response.text, str(response.url))
            print("TEST", json.dumps({
                "name": test["name"], "status": response.status_code, "bytes": len(response.content),
                "url": str(response.url), "rows": rows[:20], "count": len(rows)
            }, ensure_ascii=False), flush=True)
        except Exception as exc:
            print("ERROR", test["name"], repr(exc), flush=True)
