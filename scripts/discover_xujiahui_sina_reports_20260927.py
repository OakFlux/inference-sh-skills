from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

OUT = Path("xujiahui_sina_discovery")
OUT.mkdir(exist_ok=True)
SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def get(url: str):
    errors=[]
    for attempt in range(1,6):
        try:
            r=SESSION.get(url,headers=HEADERS,timeout=(20,120),allow_redirects=True)
            print("HTTP",r.status_code,r.url,r.headers.get("content-type"),len(r.content),flush=True)
            r.raise_for_status()
            return r
        except Exception as exc:
            errors.append(repr(exc)); time.sleep(min(2*attempt,8))
    raise RuntimeError(errors)

candidates=[]
for host in ["https://stock.finance.sina.com.cn", "https://vip.stock.finance.sina.com.cn"]:
    for path in [
        "/stock/go.php/vReport_List/kind/search/index.phtml?symbol=002561&t1=all",
        "/q/go.php/vReport_List/kind/search/index.phtml?symbol=002561&t1=all",
        "/stock/go.php/vReport_List/kind/search/index.phtml?symbol=002561",
        "/q/go.php/vReport_List/kind/search/index.phtml?symbol=002561",
    ]:
        candidates.append(host+path)

summary={}
report_links={}
for idx,url in enumerate(candidates,1):
    try:
        r=get(url); body=r.content; text=body.decode(r.encoding or "utf-8",errors="replace")
        (OUT/f"candidate_{idx}.html").write_bytes(body)
        soup=BeautifulSoup(text,"html.parser")
        links=[]
        for a in soup.find_all("a",href=True):
            href=urljoin(r.url,a["href"])
            title=" ".join(a.get_text(" ",strip=True).split())
            if "vReport_Show" in href or "rptid" in href:
                links.append({"title":title,"url":href})
                report_links[href]=title
        summary[url]={"status":r.status_code,"final_url":r.url,"bytes":len(body),"title":soup.title.get_text(" ",strip=True) if soup.title else "","links":links}
        print("LIST",idx,"links",len(links),json.dumps(links[:20],ensure_ascii=False),flush=True)
    except Exception as exc:
        summary[url]={"error":repr(exc)}; print("LIST_ERROR",url,repr(exc),flush=True)

# Try pagination on the best route and extract all unique report links.
base="https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=002561&t1=all"
for page in range(1,21):
    url=base+f"&p={page}"
    try:
        r=get(url); text=r.content.decode(r.encoding or "utf-8",errors="replace")
        soup=BeautifulSoup(text,"html.parser"); found=0
        for a in soup.find_all("a",href=True):
            href=urljoin(r.url,a["href"]); title=" ".join(a.get_text(" ",strip=True).split())
            if "vReport_Show" in href or "rptid" in href:
                report_links[href]=title; found+=1
        print("PAGE",page,"found",found,flush=True)
        if page>1 and found==0: break
    except Exception as exc:
        print("PAGE_ERROR",page,repr(exc),flush=True); break

# Search engine-like Sina endpoint variations.
search_urls=[
    "https://vip.stock.finance.sina.com.cn/q/go.php/vReport_List/kind/search/index.phtml?symbol=002561&t1=all&p=1",
    "https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=002561&t1=all&p=1",
]
for url in search_urls:
    try:
        r=get(url); print("SEARCH_ROUTE",url,r.url,len(r.content),flush=True)
    except Exception as exc: print("SEARCH_ROUTE_ERROR",url,repr(exc),flush=True)

# Fetch each detail page to capture metadata, text length, and any PDF/file links.
records=[]
for i,(url,anchor) in enumerate(report_links.items(),1):
    try:
        r=get(url); text=r.content.decode(r.encoding or "utf-8",errors="replace"); soup=BeautifulSoup(text,"html.parser")
        fulltext="\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
        interesting=[]
        for tag in soup.find_all(True):
            for attr in ("href","src","data-url","data-file","content"):
                val=tag.get(attr)
                if isinstance(val,str) and val.strip():
                    u=urljoin(r.url,val.strip())
                    if any(x in u.lower() for x in (".pdf","download","file","attach","report")):
                        interesting.append(u)
        rptid=re.search(r"rptid/(\d+)",r.url)
        rec={
            "rptid":rptid.group(1) if rptid else "",
            "anchor_title":anchor,
            "page_title":soup.title.get_text(" ",strip=True) if soup.title else "",
            "url":r.url,
            "text_chars":len(fulltext),
            "text_head":fulltext[:1200],
            "interesting_urls":list(dict.fromkeys(interesting)),
        }
        records.append(rec)
        print("REPORT",i,json.dumps(rec,ensure_ascii=False),flush=True)
    except Exception as exc:
        print("REPORT_ERROR",url,repr(exc),flush=True)

(OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
(OUT/"reports.json").write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding="utf-8")
print("TOTAL_UNIQUE_REPORTS",len(records),flush=True)
