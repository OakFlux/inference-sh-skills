from __future__ import annotations

import concurrent.futures
import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

START = 78500
END = 79600
OUT = Path("fxbaogao_renzixing_huajin_scan.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}
TARGETS = ("任子行", "快速成长的网络审计专家")


def inspect(doc_id: int):
    url = f"https://www.fxbaogao.com/detail/{doc_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        if r.status_code != 200 or len(r.content) < 10000:
            return None
        r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        h1 = soup.find("h1")
        h1_text = h1.get_text(" ", strip=True) if h1 else ""
        text = " ".join(soup.get_text(" ", strip=True).split())
        if any(t in title or t in h1_text or t in text[:10000] for t in TARGETS):
            return {"doc_id": doc_id, "url": url, "title": title, "h1": h1_text, "bytes": len(r.content), "excerpt": text[:3000]}
    except Exception:
        return None
    return None


def main():
    matches = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as ex:
        futures = {ex.submit(inspect, i): i for i in range(START, END + 1)}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                matches.append(result)
                print("MATCH", json.dumps(result, ensure_ascii=False), flush=True)
    matches.sort(key=lambda x: x["doc_id"])
    OUT.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
    print("MATCH_COUNT", len(matches), flush=True)


if __name__ == "__main__":
    main()
