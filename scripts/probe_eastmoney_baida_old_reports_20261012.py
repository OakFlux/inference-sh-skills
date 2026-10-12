from __future__ import annotations
import json
import requests

session=requests.Session()
session.headers.update({"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36","Referer":"https://data.eastmoney.com/report/stock.jshtml?encodeUrl="})
base="https://reportapi.eastmoney.com/report/list"
variants=[]
for qtype in ["0","1","2"]:
  for code_key in ["code","stockCode"]:
    params={"pageSize":200,"pageNo":1,"beginTime":"2014-01-01","endTime":"2018-12-31","qType":qtype,"industry":"*","industryCode":"*","rating":"*","ratingChange":"*","orgCode":"","rcode":"",code_key:"600865"}
    variants.append((f"GET_list_q{qtype}_{code_key}","GET",base,params,None))
# list2 GET and POST form/json variants
base2="https://reportapi.eastmoney.com/report/list2"
params={"pageSize":200,"pageNo":1,"beginTime":"2014-01-01","endTime":"2018-12-31","qType":"1","code":"600865","industryCode":"*","rating":"*","ratingChange":"*","orgCode":"","rcode":""}
variants.append(("GET_list2","GET",base2,params,None))
variants.append(("POST_form_list2","POST",base2,None,params))
variants.append(("POST_json_list2","POST",base2,None,params))
# search exact titles via query parameters
for title in ["筹建医疗中心转型大健康产业","打造高端肿瘤医院","主业稳健经营医疗健康持续推进","百大集团"]:
  params={"pageSize":200,"pageNo":1,"beginTime":"2014-01-01","endTime":"2018-12-31","qType":"0","industry":"*","industryCode":"*","rating":"*","ratingChange":"*","orgCode":"","rcode":"","title":title}
  variants.append(("TITLE_"+title,"GET",base,params,None))

for name,method,url,params,data in variants:
  try:
    if name=="POST_json_list2":
      r=session.post(url,json=data,timeout=(20,120))
    elif method=="POST":
      r=session.post(url,data=data,timeout=(20,120))
    else:
      r=session.get(url,params=params,timeout=(20,120))
    print("===",name,"STATUS",r.status_code,"TYPE",r.headers.get("content-type"),"BYTES",len(r.content),"URL",r.url,flush=True)
    print("PREFIX",r.text[:500],flush=True)
    try:
      obj=r.json()
    except Exception:
      continue
    rows=obj.get("data") or []
    if isinstance(rows,dict): rows=rows.get("list") or rows.get("data") or []
    print("HITS",obj.get("hits"),"SIZE",obj.get("size"),"ROWS",len(rows),flush=True)
    for row in rows[:50]:
      title=str(row.get("title") or "")
      if "百大" in title or str(row.get("stockCode"))=="600865" or str(row.get("stockName"))=="百大集团":
        compact={k:row.get(k) for k in ["title","stockName","stockCode","orgSName","publishDate","infoCode","attachPages","attachSize","researcher","emRatingName","encodeUrl","column"]}
        print("MATCH",json.dumps(compact,ensure_ascii=False),flush=True)
  except Exception as e:
    print("ERROR",name,repr(e),flush=True)
