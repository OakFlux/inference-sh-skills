from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT = Path("yanbaoke_solex_probe")
OUT.mkdir(exist_ok=True)
PAGES = {
    "2024_zhejiang_6p": "https://www.yanbaoke.com/info/3zV9WkYpM4k9PRQ823SEvB",
    "2021_dongbei_4p": "https://www.yanbaoke.com/info/Fknh9UjELxpRo4Qi69wBGZ",
    "2026_tianfeng_5p": "https://www.yanbaoke.com/info/GJXz6zgx8ovCAyVxTt4nGo",
    "search_solex": "https://www.yanbaoke.com/search?q=%E6%9D%BE%E9%9C%96%E7%A7%91%E6%8A%80",
}

session = requests.Session(); session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/155 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

records=[]
for tag,url in PAGES.items():
    rec={"tag":tag,"url":url}
    try:
        r=session.get(url,headers=headers,timeout=(20,120),allow_redirects=True)
        rec.update({"status":r.status_code,"final_url":r.url,"content_type":r.headers.get("content-type"),"bytes":len(r.content),"headers":dict(r.headers)})
        (OUT/f"{tag}.html").write_bytes(r.content)
        soup=BeautifulSoup(r.text,"lxml")
        rec["title"]=soup.title.get_text(" ",strip=True) if soup.title else ""
        links=[]
        for el in soup.find_all(True):
            for attr in ("href","src","data-url","data-href","data-download","data-file","action"):
                v=el.get(attr)
                if not v or not isinstance(v,str): continue
                absolute=urljoin(r.url,v)
                txt=" ".join(el.get_text(" ",strip=True).split())[:300]
                combined=(v+" "+absolute+" "+txt).lower()
                if any(k in combined for k in ["pdf","download","下载","doc","ppt","api","report","3zv9","fknh","gjxz"]):
                    links.append({"tag":el.name,"attr":attr,"value":v,"absolute":absolute,"text":txt})
        embedded=sorted(set(re.findall(r"https?://[^\"'<>\\\s]+",r.text)))
        embedded=[x for x in embedded if any(k in x.lower() for k in ["pdf","download","api","report","yanbaoke","oss","cos","s3"])]
        strings=sorted(set(re.findall(r"[\"'`]([^\"'`\n]{3,300})[\"'`]",r.text)))
        strings=[x for x in strings if any(k in x.lower() for k in ["pdf","download","fileurl","reporturl","docx","pptx","资源","下载"])]
        rec["links"]=links[:2000]; rec["embedded"]=embedded[:2000]; rec["strings"]=strings[:3000]
        print("FETCH",tag,r.status_code,len(r.content),r.url,rec["title"],flush=True)
        for x in links[:300]: print("LINK",tag,json.dumps(x,ensure_ascii=False),flush=True)
        for x in embedded[:300]: print("EMBED",tag,x,flush=True)
        for x in strings[:300]: print("STR",tag,x[:500],flush=True)
    except Exception as exc:
        rec["error"]=repr(exc); print("ERROR",tag,repr(exc),flush=True)
    records.append(rec)
(OUT/"records.json").write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding="utf-8")
