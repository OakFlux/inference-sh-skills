from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

REPORTS = [
    {
        "rptid": "617160447124",
        "institution": "华金证券",
        "date": "2016-08-17",
        "expected": "快速成长的网络审计专家",
    },
    {
        "rptid": "617386628499",
        "institution": "太平洋证券",
        "date": "2016-04-21",
        "expected": "行业景气外延助力",
    },
    {
        "rptid": "507309959252",
        "institution": "平安证券",
        "date": "2016-01-28",
        "expected": "互联网内容和行为审计迎来新增市场空间",
    },
]
OUT = Path("renzixing_sina_show_pages.json")
ARCHIVE = Path("_renzixing_sina_pages")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


def main() -> None:
    ARCHIVE.mkdir(exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)
    records = []
    for report in REPORTS:
        url = f"https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/{report['rptid']}/index.phtml"
        response = session.get(url, timeout=120, allow_redirects=True)
        response.encoding = response.apparent_encoding or "utf-8"
        response.raise_for_status()
        text = response.text
        soup = BeautifulSoup(text, "html.parser")
        title = norm(soup.title.get_text(" ", strip=True) if soup.title else "")
        body_text = norm(soup.get_text(" ", strip=True))
        links = []
        for a in soup.find_all("a", href=True):
            href = urljoin(str(response.url), a.get("href", ""))
            label = norm(a.get_text(" ", strip=True))
            if any(k in href.lower() for k in ("pdf", "download", "attach", "file", "report")) or any(k in label for k in ("下载", "PDF", "原文")):
                links.append({"url": href, "text": label})
        images = []
        for img in soup.find_all("img", src=True):
            src = urljoin(str(response.url), img.get("src", ""))
            if "report" in src.lower() or "pdf" in src.lower():
                images.append(src)
        scripts = []
        for script in soup.find_all("script"):
            content = script.get_text(" ", strip=True)
            if any(k in content.lower() for k in ("pdf", "download", "rptid", "report")):
                scripts.append(content[:8000])
        selectors = {}
        for sel in ["#content", ".content", ".report_content", ".blk_container", ".article", "td"]:
            matches = []
            for node in soup.select(sel):
                t = norm(node.get_text(" ", strip=True))
                if len(t) > 300 and ("任子行" in t or report["expected"] in t):
                    matches.append(t)
            if matches:
                selectors[sel] = sorted(matches, key=len, reverse=True)[:3]
        record = {
            **report,
            "url": url,
            "final_url": str(response.url),
            "status": response.status_code,
            "bytes": len(response.content),
            "encoding": response.encoding,
            "title": title,
            "body_text": body_text,
            "links": links,
            "images": images,
            "scripts": scripts,
            "selectors": selectors,
        }
        records.append(record)
        (ARCHIVE / f"{report['rptid']}.html").write_text(text, encoding="utf-8")
        (ARCHIVE / f"{report['rptid']}.txt").write_text(body_text, encoding="utf-8")
        print("REPORT", json.dumps({k: record[k] for k in ("rptid", "title", "bytes", "links", "images", "selectors")}, ensure_ascii=False), flush=True)
    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
