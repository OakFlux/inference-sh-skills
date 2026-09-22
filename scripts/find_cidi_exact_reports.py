import json, time, requests
from pathlib import Path
s=requests.Session(); s.trust_env=False
headers={'User-Agent':'Mozilla/5.0','Accept':'application/json, text/plain, */*','Content-Type':'application/json;charset=UTF-8','Origin':'https://www.sdyanbao.com','Referer':'https://www.sdyanbao.com/report','Device':'1','X-Token':''}
base={'device':1,'hideTrader':0,'order':0,'pageSize':100,'pageCount':0,'dateRange':0,'startTime':'','endTime':'','typeIds':'','industryIds':'','opFrom':1}
rows=[]; log=[]
queries=['希迪智驾','03881','03881.HK','开拓无人驾驶矿卡新蓝海','无人矿卡拓疆域','商业化进程迈阶跃升','智能驾驶平台型企业']
for query in queries:
    for only_title in (0,1):
        payload=dict(base,page=1,keyword=query,onlyTitle=only_title)
        try:
            response=s.post('https://api.sdyanbao.com/api/file/search',json=payload,headers=headers,timeout=(8,30))
            response.raise_for_status(); data=response.json().get('data') or {}; found=data.get('files') or []
            rows.extend(found); log.append({'query':query,'onlyTitle':only_title,'count':len(found),'total':data.get('total')})
            print(query,only_title,len(found),data.get('total'),flush=True)
        except Exception as exc:
            log.append({'query':query,'onlyTitle':only_title,'error':repr(exc)})
        time.sleep(.2)
for page in range(1,11):
    payload=dict(base,page=page,keyword='希迪智驾',onlyTitle=0)
    try:
        response=s.post('https://api.sdyanbao.com/api/file/search',json=payload,headers=headers,timeout=(8,30))
        response.raise_for_status(); found=(response.json().get('data') or {}).get('files') or []
        rows.extend(found); print('page',page,len(found),flush=True)
        if not found: break
    except Exception as exc:
        log.append({'page':page,'error':repr(exc)}); break
    time.sleep(.2)
unique={str(item.get('id') or item.get('page_url')):item for item in rows if item.get('id') or item.get('page_url')}
exact=[]
for item in unique.values():
    name=item.get('name',''); content=item.get('content','')[:5000]
    if any(term in name for term in ('希迪智驾','03881','3881.HK')) or any(term in content for term in ('希迪智驾（03881','希迪智驾(03881','希迪智驾（3881','希迪智驾(3881')):
        exact.append(item)
exact.sort(key=lambda item:(item.get('time_text',''),item.get('page_count',0)),reverse=True)
Path('cidi_exact_search').mkdir(exist_ok=True)
Path('cidi_exact_search/results.json').write_text(json.dumps({'log':log,'unique_count':len(unique),'exact':exact},ensure_ascii=False,indent=2),encoding='utf-8')
for item in exact:
    print(item.get('id'),item.get('time_text'),(item.get('organization') or {}).get('name'),item.get('page_count'),item.get('name'),item.get('page_url'),flush=True)
