from __future__ import annotations
import json
import time
import requests

session=requests.Session()
session.headers.update({"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36","Referer":"https://data.eastmoney.com/report/stock.jshtml"})
URL="https://reportapi.eastmoney.com/report/list"
WINDOWS=[
 ("2015-10-20","2015-11-05"),
 ("2015-11-20","2015-12-05"),
 ("2016-03-25","2016-04-05"),
]

def fetch_page(begin,end,page):
 params={"pageSize":100,"pageNo":page,"beginTime":begin,"endTime":end,"qType":"0","industry":"*","industryCode":"*","rating":"*","ratingChange":"*","orgCode":"","rcode":""}
 for attempt in range(1,6):
  try:
   r=session.get(URL,params=params,timeout=(20,120))
   r.raise_for_status(); return r.json()
  except Exception as e:
   print("RETRY",begin,end,page,attempt,repr(e),flush=True); time.sleep(attempt)
 raise RuntimeError("failed")

all_matches=[]
for begin,end in WINDOWS:
 first=fetch_page(begin,end,1)
 total=int(first.get("TotalPage") or 1)
 hits=first.get("hits")
 print("WINDOW",begin,end,"HITS",hits,"PAGES",total,flush=True)
 for page in range(1,total+1):
  obj=first if page==1 else fetch_page(begin,end,page)
  rows=obj.get("data") or []
  print("PAGE",begin,end,page,"ROWS",len(rows),flush=True)
  for row in rows:
   if str(row.get("stockCode") or "")=="600865" or str(row.get("stockName") or "")=="百大集团" or "百大集团" in str(row.get("title") or ""):
    compact={k:row.get(k) for k in ["title","stockName","stockCode","orgSName","orgName","publishDate","infoCode","attachPages","attachSize","researcher","emRatingName","sRatingName","encodeUrl","column"]}
    print("MATCH",json.dumps(compact,ensure_ascii=False),flush=True)
    all_matches.append(compact)
print("ALL_MATCHES",json.dumps(all_matches,ensure_ascii=False,indent=2),flush=True)
