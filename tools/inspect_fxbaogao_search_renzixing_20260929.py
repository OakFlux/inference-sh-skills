from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

OUT = Path("fxbaogao_renzixing_search_inspection.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}
BASE = "https://www.fxbaogao.com"
KW = "任子行"

URLS = [
    f"{BASE}/search?q={quote(KW)}",
    f"{BASE}/search?keyword={quote(KW)}",
    f"{BASE}/search?keywords={quote(KW)}",
    f"{BASE}/search?key={quote(KW)}",
    f"{BASE}/search/report?q={quote(KW)}",
    f"{BASE}/search/report?keyword={quote(KW)}",
    f"{BASE}/aisearch/report?q={quote(KW)}",
    f"{BASE}/aisearch/report?keyword={quote(KW)}",
    f"{BASE}/aisearch/report?keywords={quote(KW)}",
    f"{BASE}/archives/search?q={quote(KW)}",
    f"{BASE}/archives?keyword={quote(KW)}",
    f"{BASE}/?s={quote(KW)}",
]


def inspect(text: str, final_url: str):
    soup = BeautifulSoup(text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(final_url, a["href"])
        title = " ".join(a.get_text(" ", strip=True).split())
        if "任子行" in title or "300311" in title or "任子行" in href:
            links.append({"title": title, "url": href})
    detail_ids = sorted(set(re.findall(r"/detail/(\d+)", html.unescape(text))))
    excerpts = []
    for pattern in ("任子行", "300311"):
        for m in re.finditer(pattern, text, re.I):
            excerpts.append(text[max(0, m.start()-500):m.start()+1500])
            if len(excerpts) >= 20:
                break
    return {"title": soup.title.get_text(" ", strip=True) if soup.title else "", "links": links[:100], "detail_ids": detail_ids[:500], "excerpts": excerpts}


def main():
    s = requests.Session(); s.headers.update(HEADERS)
    records = []
    for url in URLS:
        try:
            r = s.get(url, timeout=120, allow_redirects=True)
            item = {"url": url, "final_url": r.url, "status": r.status_code, "bytes": len(r.content), "content_type": r.headers.get("content-type")}
            item.update(inspect(r.text, r.url))
            records.append(item)
            print("SEARCH", json.dumps({k:item[k] for k in ("url","final_url","status","bytes","title")}, ensure_ascii=False), flush=True)
            print("LINKS", json.dumps(item["links"], ensure_ascii=False), flush=True)
            print("DETAIL_IDS", item["detail_ids"][:50], flush=True)
            for ex in item["excerpts"][:5]:
                print("EXCERPT", json.dumps(ex, ensure_ascii=False), flush=True)
        except Exception as exc:
            records.append({"url": url, "error": repr(exc)})
            print("ERROR", url, repr(exc), flush=True)
    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
