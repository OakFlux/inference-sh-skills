from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

session = requests.Session()
session.trust_env = False
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})

sina_ids = [
    "563614109620",
    "500649915467",
    "500554488921",
    "381918492631",
    "343815550875",
    "343811261281",
    "343323551082",
]

nxny_ids = ["3378640", "3336413", "3333978", "3248060", "3183162", "3132216"]


def fetch(url: str) -> requests.Response:
    response = session.get(url, timeout=(20, 120), allow_redirects=True)
    print("HTTP", response.status_code, len(response.content), response.headers.get("content-type"), url, "=>", response.url)
    response.raise_for_status()
    return response


def decode(response: requests.Response) -> str:
    raw = response.content
    candidates = [response.encoding, response.apparent_encoding, "utf-8", "gb18030", "gbk"]
    best = ""
    best_score = -1_000_000
    for encoding in candidates:
        if not encoding:
            continue
        try:
            text = raw.decode(encoding, errors="replace")
        except Exception:
            continue
        score = sum(text.count(word) for word in ["蓝丰", "证券", "报告", "作者", "页数", "投资"])
        score -= 20 * text.count("�")
        if score > best_score:
            best = text
            best_score = score
    return best


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def report_links(base: str, soup: BeautifulSoup):
    found = []
    for tag in soup.find_all(True):
        for key in ("href", "src", "action"):
            value = tag.get(key)
            if not value:
                continue
            absolute = urljoin(base, value)
            lower = absolute.lower()
            if any(term in lower for term in ["pdf", "download", "down", "file", "report", "viewer", "attach"]):
                found.append({
                    "tag": tag.name,
                    "url": absolute,
                    "text": clean(tag.get_text(" ", strip=True))[:160],
                    "onclick": tag.get("onclick"),
                })
    unique = []
    seen = set()
    for item in found:
        key = (item["tag"], item["url"], str(item["onclick"]))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def inspect_sina(report_id: str):
    url = f"https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/{report_id}/index.phtml"
    response = fetch(url)
    text = decode(response)
    soup = BeautifulSoup(text, "html.parser")
    print("\nSINA", report_id)
    print("TITLE", clean(soup.title.get_text() if soup.title else ""))
    print("BODY", clean(soup.get_text(" ", strip=True))[:10000])
    for row in soup.find_all("tr"):
        cells = [clean(cell.get_text(" ", strip=True)) for cell in row.find_all(["td", "th"])]
        if cells:
            print("ROW", " | ".join(cells)[:2500])
    print("LINKS", json.dumps(report_links(response.url, soup), ensure_ascii=False, indent=2)[:30000])
    hidden = sorted(set(re.findall(r"https?://[^\s'\"<>]+", text)))
    print("URLS", json.dumps([x for x in hidden if any(k in x.lower() for k in ["pdf", "download", "file", "report"])], ensure_ascii=False, indent=2)[:20000])


def inspect_nxny(report_id: str):
    url = f"https://www.nxny.com/report/view_{report_id}.html"
    response = fetch(url)
    text = decode(response)
    soup = BeautifulSoup(text, "html.parser")
    print("\nNXNY", report_id)
    print("TITLE", clean(soup.title.get_text() if soup.title else ""))
    print("BODY", clean(soup.get_text(" ", strip=True))[:8000])
    for row in soup.find_all("tr"):
        cells = [clean(cell.get_text(" ", strip=True)) for cell in row.find_all(["td", "th"])]
        if cells:
            print("ROW", " | ".join(cells)[:2500])
    for tag in soup.find_all(True):
        attrs = {key: tag.get(key) for key in ["onclick", "href", "src", "value", "id", "name", "action"] if tag.get(key) is not None}
        blob = json.dumps(attrs, ensure_ascii=False)
        if any(term in blob.lower() for term in ["down", "rnd", "pdf", "file", "report"]):
            print("TAG", tag.name, blob[:2200], clean(tag.get_text(" ", strip=True))[:300])
    print("LINKS", json.dumps(report_links(response.url, soup), ensure_ascii=False, indent=2)[:30000])
    print("DOWNFILE", re.findall(r"downfile\((.*?)\)", text, flags=re.I | re.S)[:100])


for report_id in sina_ids:
    try:
        inspect_sina(report_id)
    except Exception as error:
        print("SINA_ERROR", report_id, repr(error))

for report_id in nxny_ids:
    try:
        inspect_nxny(report_id)
    except Exception as error:
        print("NXNY_ERROR", report_id, repr(error))
