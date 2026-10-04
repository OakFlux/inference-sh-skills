from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

URL = "https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=sz300311&t1=all"
OUT = Path("sina_renzixing_report_list.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}


def main() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)
    records = []
    for page in range(1, 8):
        url = URL + f"&p={page}"
        response = session.get(url, timeout=90, allow_redirects=True)
        response.encoding = response.apparent_encoding or "utf-8"
        print("PAGE", page, response.status_code, len(response.content), response.url, flush=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = urljoin(str(response.url), a.get("href", ""))
            label = " ".join(a.get_text(" ", strip=True).split())
            if "vReport_Show" in href or "rptid" in href:
                links.append({"url": href, "text": label})
        # Also extract report-like table rows.
        rows = []
        for tr in soup.find_all("tr"):
            txt = " ".join(tr.get_text(" ", strip=True).split())
            if "任子行" in txt or any(k in txt for k in ("证券", "研究员", "评级")):
                hrefs = [urljoin(str(response.url), a.get("href", "")) for a in tr.find_all("a", href=True)]
                rows.append({"text": txt, "links": hrefs})
        item = {"page": page, "url": str(response.url), "title": soup.title.get_text(" ", strip=True) if soup.title else "", "links": links, "rows": rows}
        records.append(item)
        print("LINKS", page, json.dumps(links, ensure_ascii=False), flush=True)
        print("ROWS", page, json.dumps(rows, ensure_ascii=False), flush=True)
        if not links and page > 1:
            break
    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
