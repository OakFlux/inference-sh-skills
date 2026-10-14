from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT = Path("solex_source_probe")
OUT.mkdir(exist_ok=True)

URLS = [
    "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/lastest/rptid/819909852011/index.phtml",
    "https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=603992&t1=2",
    "https://finance.sina.cn/2024-03-29/detail-inapytuq4454540.d.html",
    "https://bg.sgpjbg.com/yanbaokulist.html?bglx=%2C76956%2C&djwzth=&esp=100&gpdm=&gsrmgn1=0&gsrmgn2=&gsrmgn3=&gsrmgn4=&gsrmgn5=&gsrmgn6=&hyfl1=&hyfl2=&khj=1&mls=0&page=91&px=2&q=&qws=0&rmgn1=&rmgn2=&sc=&sj=&tsbq=%2C7_1%2C&type=0&ym=",
    "https://www.sgpjbg.com/yanbaokulist.html?keyword=%E6%9D%BE%E9%9C%96%E7%A7%91%E6%8A%80",
    "https://299sucai.com/hybg/12648/",
    "https://www.yixiuqixie.com/doc/7561.html",
    "https://www.djyanbao.cc/reports/cmmucq5dv0jo597zoslqmuwfk",
    "https://www.fxbaogao.com/detail/5201086",
    "https://quote.cfi.cn/ybyl/76887/603992.html",
]

KEYWORDS = (
    "松霖", "603992", "pdf", "download", "下载", "report", "yanbao", "baogao",
    "机器人", "idm", "厨卫", "美容", "819909852011",
)

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

results = []
for idx, url in enumerate(URLS, 1):
    rec = {"input_url": url}
    try:
        r = session.get(url, headers=headers, timeout=(20, 120), allow_redirects=True)
        rec.update({
            "status": r.status_code,
            "final_url": r.url,
            "content_type": r.headers.get("content-type"),
            "bytes": len(r.content),
            "headers": dict(r.headers),
        })
        ext = ".html"
        if "json" in (r.headers.get("content-type") or ""):
            ext = ".json"
        raw_path = OUT / f"{idx:02d}_{urlparse(url).netloc.replace(':','_')}{ext}"
        raw_path.write_bytes(r.content)
        text = r.text
        soup = BeautifulSoup(text, "lxml")
        links = []
        for tag in soup.find_all(True):
            for attr in ("href", "src", "data-url", "data-href", "data-download", "data-file", "value"):
                val = tag.get(attr)
                if not val or not isinstance(val, str):
                    continue
                absolute = urljoin(r.url, val)
                label = " ".join(tag.get_text(" ", strip=True).split())[:300]
                combined = f"{val} {absolute} {label}".lower()
                if any(k.lower() in combined for k in KEYWORDS):
                    links.append({"tag": tag.name, "attr": attr, "value": val, "absolute": absolute, "text": label})
        # Also capture URL-like strings embedded in scripts.
        embedded = sorted(set(re.findall(r"https?://[^\"'<>\\\s]+", text)))
        embedded = [x for x in embedded if any(k.lower() in x.lower() for k in KEYWORDS)]
        rec["title"] = soup.title.get_text(" ", strip=True) if soup.title else ""
        rec["links"] = links[:1000]
        rec["embedded_urls"] = embedded[:1000]
        rec["text_matches"] = []
        clean = soup.get_text("\n", strip=True)
        for keyword in KEYWORDS:
            pos = clean.lower().find(keyword.lower())
            if pos >= 0:
                rec["text_matches"].append({"keyword": keyword, "context": clean[max(0,pos-500):pos+1500]})
        print("FETCH", idx, r.status_code, len(r.content), r.url, rec["title"], flush=True)
        for link in links[:80]:
            print("LINK", idx, json.dumps(link, ensure_ascii=False), flush=True)
        for embedded_url in embedded[:80]:
            print("EMBED", idx, embedded_url, flush=True)
    except Exception as exc:  # noqa: BLE001
        rec["error"] = repr(exc)
        print("ERROR", idx, url, repr(exc), flush=True)
    results.append(rec)

(OUT / "probe_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
