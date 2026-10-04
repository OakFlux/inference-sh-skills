from __future__ import annotations

import json
import re
import requests

s = requests.Session()
s.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
})

# CNINFO org-id discovery attempts.
for method, url, kwargs in [
    ('GET', 'https://www.cninfo.com.cn/new/information/topSearch/query', {'params': {'keyWord':'605011','maxNum':'20'}}),
    ('POST', 'https://www.cninfo.com.cn/new/information/topSearch/query', {'data': {'keyWord':'605011','maxNum':'20'}}),
    ('POST', 'https://www.cninfo.com.cn/new/information/topSearch/detailOfQuery', {'data': {'keyWord':'605011','maxSecNum':'20','maxListNum':'10'}}),
    ('GET', 'https://www.cninfo.com.cn/new/information/topSearch/query', {'params': {'keyWord':'杭州热电','maxNum':'20'}}),
]:
    try:
        r=s.request(method,url,timeout=(15,60),headers={'Referer':'https://www.cninfo.com.cn/'},**kwargs)
        print('\nCNINFO',method,r.status_code,r.headers.get('content-type'),len(r.content),r.url,flush=True)
        print(r.text[:5000],flush=True)
    except Exception as e:
        print('CNINFO_ERR',method,url,repr(e),flush=True)

# SSE bulletin endpoint discovery.
endpoint='https://query.sse.com.cn/security/stock/queryCompanyBulletin.do'
params={
    'isPagination':'true',
    'productId':'605011',
    'keyWord':'',
    'securityType':'0101,120100,020100,020200,120200',
    'reportType2':'DQGG',
    'reportType':'ALL',
    'beginDate':'2020-01-01',
    'endDate':'2026-10-04',
    'pageHelp.pageSize':'100',
    'pageHelp.pageCount':'50',
    'pageHelp.pageNo':'1',
    'pageHelp.beginPage':'1',
    'pageHelp.cacheSize':'1',
    'pageHelp.endPage':'5',
}
try:
    r=s.get(endpoint,params=params,headers={'Referer':'https://www.sse.com.cn/'},timeout=(20,90))
    print('\nSSE',r.status_code,r.headers.get('content-type'),len(r.content),r.url,flush=True)
    print(r.text[:20000],flush=True)
except Exception as e:
    print('SSE_ERR',repr(e),flush=True)

# Broad SSE query variants.
for report_type2 in ['', 'DQGG', 'LSGG']:
    p=dict(params)
    p['reportType2']=report_type2
    p['pageHelp.pageSize']='200'
    try:
        r=s.get(endpoint,params=p,headers={'Referer':'https://www.sse.com.cn/'},timeout=(20,90))
        print('\nSSE_VARIANT',report_type2 or 'blank',r.status_code,len(r.content),flush=True)
        text=r.text
        for key in ['2025年年度报告','2024年年度报告','招股说明书','2026年第一季度报告','BULLETIN_TYPE','URL']:
            print('FIND',key,text.find(key),flush=True)
        print(text[:5000],flush=True)
    except Exception as e:
        print('SSE_VARIANT_ERR',report_type2,repr(e),flush=True)
