import json
import requests

s = requests.Session()
s.trust_env = False
headers = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36',
    'Accept': 'application/json,text/plain,*/*',
    'Referer': 'https://data.eastmoney.com/report/stock.jshtml',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}
for begin, end in [
    ('2026-04-29','2026-05-01'),
    ('2025-04-14','2025-04-16'),
    ('2019-06-17','2019-06-19'),
]:
    print('\nWINDOW', begin, end, flush=True)
    for qtype in ['0','1','2']:
        total = 0
        for page in range(1, 16):
            params = {
                'pageSize':'100', 'pageNo':str(page), 'code':'', 'qType':qtype,
                'industryCode':'*', 'industry':'*', 'rating':'*', 'ratingChange':'*',
                'beginTime':begin, 'endTime':end, 'orgCode':'', 'rcode':'', 'fields':''
            }
            try:
                r = s.get('https://reportapi.eastmoney.com/report/list', params=params, headers=headers, timeout=120)
                rows = r.json().get('data') or []
                total += len(rows)
                print('PAGE', qtype, page, r.status_code, len(rows), flush=True)
                for row in rows:
                    text = ' '.join(str(row.get(k) or '') for k in ['title','stockName','stockCode'])
                    if '河钢股份' in text or '000709' in text or '穿越周期谷底' in text or '钢铁向材料' in text or '河北龙头钢企' in text:
                        out={k:row.get(k) for k in ['title','stockName','stockCode','orgName','orgSName','publishDate','infoCode','attachPages','attachSize','researcher','emRatingName','sRatingName']}
                        print('MATCH', json.dumps(out, ensure_ascii=False), flush=True)
                if not rows:
                    break
            except Exception as exc:
                print('ERROR', qtype, page, repr(exc), flush=True)
                break
        print('TOTAL', qtype, total, flush=True)
