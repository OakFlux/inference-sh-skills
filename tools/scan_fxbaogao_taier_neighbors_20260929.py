from __future__ import annotations

import concurrent.futures
import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

START = 1531750
END = 1532200
OUT = Path("fxbaogao_taier_neighbor_matches.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def fetch(doc_id: int):
    url = f"https://www.fxbaogao.com/detail/{doc_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        if r.status_code != 200 or len(r.content) < 5000:
            return None
        r.encoding = r.apparent_encoding or "utf-8"
        text = r.text
        if "泰尔重工" not in text and "泰尔股份" not in text and "002347" not in text:
            return None
        soup = BeautifulSoup(text, "html.parser")
        title = compact(soup.title.get_text(" ", strip=True) if soup.title else "")
        h1 = soup.find("h1")
        h1_text = compact(h1.get_text(" ", strip=True) if h1 else "")
        body = compact(soup.get_text(" ", strip=True))
        return {
            "doc_id": doc_id,
            "url": url,
            "title": title,
            "h1": h1_text,
            "excerpt": body[:1500],
            "bytes": len(r.content),
        }
    except Exception as exc:
        return {"doc_id": doc_id, "url": url, "error": repr(exc)} if doc_id == 1531967 else None


def main():
    matches = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_map = {executor.submit(fetch, doc_id): doc_id for doc_id in range(START, END + 1)}
        for future in concurrent.futures.as_completed(future_map):
            result = future.result()
            if result:
                matches.append(result)
                print("MATCH", json.dumps(result, ensure_ascii=False), flush=True)
    matches.sort(key=lambda x: x["doc_id"])
    OUT.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
    print("MATCH_COUNT", len(matches), flush=True)


if __name__ == "__main__":
    main()
