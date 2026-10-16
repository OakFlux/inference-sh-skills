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
windows = [
    ('2024-05-12','2024-05-14'),
    ('2022-11-12','2022-11-14'),
    ('2023-05-05','2023-05-08'),
]
needles = ['河钢股份','000709','钢铁毛利率提升','新基地建设稳步推进','钒产品']
for begin,end in windows:
    print('\nWINDOW',begin,end,flush=True)
    for qtype in ['0','1','2']:
        for page in range(1,20):
            params={
                'pageSize':'100','pageNo':str(page),'code':'','qType':qtype,
                'industryCode':'*','industry':'*','rating':'*','ratingChange':'*',
                'beginTime':begin,'endTime':end,'orgCode':'','rcode':'','fields':''
            }
            r=s.get('https://reportapi.eastmoney.com/report/list',params=params,headers=headers,timeout=120)
            r.raise_for_status()
            rows=r.json().get('data') or []
            print('PAGE',qtype,page,len(rows),flush=True)
            for row in rows:
                text=' '.join(str(row.get(k) or '') for k in ['title','stockName','stockCode','orgName'])
                if any(n in text for n in needles):
                    out={k:row.get(k) for k in ['title','stockName','stockCode','orgName','orgSName','publishDate','infoCode','attachPages','attachSize','researcher','emRatingName','sRatingName']}
                    print('MATCH',json.dumps(out,ensure_ascii=False),flush=True)
            if not rows:
                break
