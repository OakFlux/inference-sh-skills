from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

TITLE = "国货航(001391)：跨境电商方兴未艾 航空货运龙头顺势而为"
VIEWER = (
    "https://www.9fzt.com/others/report.html?pushChannel=9fztgw&contentType=article"
    "&page=view_the_article&contentId=820515916583&content=" + quote(TITLE)
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}
OUT = Path("inspect_9fzt_report_viewer.json")


def scan(text: str, base: str) -> dict:
    soup = BeautifulSoup(text, "html.parser")
    scripts = [urljoin(base, x.get("src")) for x in soup.find_all("script") if x.get("src")]
    urls = set()
    decoded = text.replace("\\/", "/")
    for pat in [r'https?://[^\s"\'<>]+', r'//[^\s"\'<>]+']:
        for u in re.findall(pat, decoded):
            if u.startswith("//"):
                u = "https:" + u
            u = u.rstrip(",);]}\\")
            if any(t in u.lower() for t in ("api", "report", "article", "pdf", "file", "download", "content")):
                urls.add(u)
    tokens = ["contentId", "820515916583", "view_the_article", "pdf", "download", "article", "report", "api", "fileUrl", "pdfUrl"]
    excerpts = {}
    for token in tokens:
        found = []
        for m in re.finditer(re.escape(token), text, re.I):
            found.append(text[max(0, m.start()-600):m.start()+1500])
            if len(found) >= 10:
                break
        if found:
            excerpts[token] = found
    return {"scripts": scripts, "urls": sorted(urls), "excerpts": excerpts}


def main() -> None:
    s=requests.Session(); s.headers.update(HEADERS)
    records=[]
    r=s.get(VIEWER, timeout=120, allow_redirects=True)
    rec={"kind":"viewer","url":VIEWER,"final_url":r.url,"status":r.status_code,"bytes":len(r.content),"content_type":r.headers.get("content-type"),"title":"","scan":scan(r.text,r.url),"prefix":r.text[:5000]}
    soup=BeautifulSoup(r.text,"html.parser")
    if soup.title: rec["title"]=soup.title.get_text(" ",strip=True)
    records.append(rec)
    print("VIEWER", json.dumps({k:rec[k] for k in ("url","final_url","status","bytes","content_type","title")}, ensure_ascii=False), flush=True)
    print("SCRIPTS", json.dumps(rec["scan"]["scripts"], ensure_ascii=False), flush=True)
    print("URLS", json.dumps(rec["scan"]["urls"], ensure_ascii=False), flush=True)
    for token, excerpts in rec["scan"]["excerpts"].items():
        for ex in excerpts:
            print("VIEWER_EXCERPT", token, json.dumps(ex, ensure_ascii=False), flush=True)
    # Fetch scripts from viewer and the detail page's known JS.
    script_urls = rec["scan"]["scripts"] + [
        "https://www.9fzt.com/js/detailArticle.js",
        "https://www.9fzt.com/others/report.js",
    ]
    seen=set()
    for u in script_urls:
        if u in seen: continue
        seen.add(u)
        try:
            sr=s.get(u, timeout=120, allow_redirects=True)
            srec={"kind":"script","url":u,"final_url":sr.url,"status":sr.status_code,"bytes":len(sr.content),"content_type":sr.headers.get("content-type"),"scan":scan(sr.text,sr.url),"prefix":sr.text[:5000]}
            records.append(srec)
            print("SCRIPT", json.dumps({k:srec[k] for k in ("url","final_url","status","bytes","content_type")}, ensure_ascii=False), flush=True)
            print("SCRIPT_URLS", u, json.dumps(srec["scan"]["urls"], ensure_ascii=False), flush=True)
            for token, excerpts in srec["scan"]["excerpts"].items():
                for ex in excerpts:
                    print("SCRIPT_EXCERPT", u, token, json.dumps(ex, ensure_ascii=False), flush=True)
        except Exception as e:
            records.append({"kind":"script","url":u,"error":repr(e)})
            print("SCRIPT_ERROR", u, repr(e), flush=True)
    OUT.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding="utf-8")
    print("WROTE",OUT,OUT.stat().st_size,flush=True)

if __name__ == "__main__": main()
