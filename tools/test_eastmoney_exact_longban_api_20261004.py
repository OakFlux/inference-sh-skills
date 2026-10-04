from __future__ import annotations

import json
import re
from pathlib import Path

import requests

OUT = Path('eastmoney_exact_longban_api.json')
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.7',
    'Referer': 'https://data.eastmoney.com/report/605577.html',
}


def parse(text: str):
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.match(r'^[^(]*\((.*)\)\s*;?$', text, re.S)
        return json.loads(m.group(1)) if m else None


def rows(payload):
    if not isinstance(payload, dict):
        return []
    value = payload.get('data')
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ('data','list','rows'):
            if isinstance(value.get(key), list):
                return value[key]
    for key in ('result','list','rows'):
        v = payload.get(key)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            for k in ('data','list','rows'):
                if isinstance(v.get(k), list):
                    return v[k]
    return []

session = requests.Session(); session.headers.update(HEADERS)
base = 'https://reportapi.eastmoney.com/report/list'
records = []
all_rows = {}
for code in ['605577','SH605577','sh605577','605577.SH']:
  for begin,end in [
      ('2023-01-01','2023-12-31'),
      ('2023-11-01','2023-12-31'),
      ('2023-12-01','2023-12-31'),
      ('2022-01-01','2024-12-31'),
      ('2020-01-01','2026-10-04'),
  ]:
    for p in ['1','2','0','']:
      for fields in ['', '[]', '*']:
        for callback_key in ['cb','callback','']:
          params = {
              'pageSize':'100','beginTime':begin,'endTime':end,'pageNo':'1',
              'fields':fields,'qType':'0','code':code,'p':p,'pageNum':'1',
          }
          if callback_key:
              params[callback_key] = 'datatable123456789'
          try:
              r=session.get(base,params=params,timeout=60)
              payload=parse(r.text)
              found=rows(payload)
              rec={
                  'url':r.url,'status':r.status_code,'bytes':len(r.content),
                  'content_type':r.headers.get('content-type'),'code':code,'begin':begin,'end':end,
                  'p':p,'fields':fields,'callback_key':callback_key,'row_count':len(found),
                  'payload_keys':list(payload.keys()) if isinstance(payload,dict) else None,
                  'payload_summary':payload if isinstance(payload,dict) and len(r.content)<3000 else None,
                  'prefix':r.text[:800],
              }
              records.append(rec)
              if found:
                  print('HIT',json.dumps(rec,ensure_ascii=False),flush=True)
                  for row in found:
                      key=str(row.get('infoCode') or row.get('reportId') or row.get('id') or row)
                      all_rows[key]=row
              elif len(records)<=20:
                  print('MISS',json.dumps(rec,ensure_ascii=False),flush=True)
          except Exception as exc:
              records.append({'code':code,'begin':begin,'end':end,'p':p,'fields':fields,'callback_key':callback_key,'error':repr(exc)})
              print('ERROR',code,begin,end,p,fields,callback_key,repr(exc),flush=True)
          if all_rows:
              break
        if all_rows: break
      if all_rows: break
    if all_rows: break
  if all_rows: break

result={'attempts':records,'rows':list(all_rows.values())}
OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('DONE rows=',len(all_rows),flush=True)
for row in all_rows.values(): print('ROW',json.dumps(row,ensure_ascii=False),flush=True)
