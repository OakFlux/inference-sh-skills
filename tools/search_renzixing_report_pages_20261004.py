from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests
from bs4 import BeautifulSoup

OUT = Path("renzixing_public_report_search.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}
QUERIES = [
    '"任子行" 券商 报告 PDF',
    '"任子行" 新股 研报',
    '"任子行" 公司研究 券商',
    'site:fxbaogao.com/detail "任子行"',
    'site:9fzt.com/detail "任子行"',
    'site:stock.finance.sina.com.cn/stock/go.php/vReport_Show "任子行"',
    '"任子行" "中信建投" 2012',
    '"任子行" "安信证券" 2012',
    '"任子行" "平安证券" 2012',
    '"任子行" "国泰君安" 2012',
]


def clean_url(url: str) -> str:
    url = html.unescape(url)
    if url.startswith("//"):
        url = "https:" + url
    if "bing.com/ck/a" in url:
        return url
    if "duckduckgo.com/l/?" in url:
        q = parse_qs(urlparse(url).query)
        if q.get("uddg"):
            return unquote(q["uddg"][0])
    return url


def extract_links(text: str, base: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(text, "html.parser")
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = clean_url(a.get("href", ""))
        label = " ".join(a.get_text(" ", strip=True).split())
        if not href.startswith("http"):
            continue
        if any(domain in href for domain in ("fxbaogao.com", "9fzt.com", "sina.com.cn", "eastmoney.com", "p5w.net", "cninfo.com.cn", "stockstar.com")):
            key = href.split("#", 1)[0]
            if key in seen:
                continue
            seen.add(key)
            results.append({"url": key, "text": label})
    return results


def main() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)
    records = []
    for query in QUERIES:
        encoded = quote_plus(query)
        urls = [
            ("bing", f"https://www.bing.com/search?q={encoded}&count=50"),
            ("duckduckgo", f"https://html.duckduckgo.com/html/?q={encoded}"),
        ]
        for engine, url in urls:
            try:
                response = session.get(url, timeout=90, allow_redirects=True)
                links = extract_links(response.text, str(response.url))
                rec = {
                    "query": query,
                    "engine": engine,
                    "status": response.status_code,
                    "bytes": len(response.content),
                    "final_url": str(response.url),
                    "links": links,
                }
                records.append(rec)
                print("SEARCH", json.dumps(rec, ensure_ascii=False), flush=True)
            except Exception as exc:
                rec = {"query": query, "engine": engine, "error": repr(exc)}
                records.append(rec)
                print("SEARCH_ERROR", json.dumps(rec, ensure_ascii=False), flush=True)
    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
