from __future__ import annotations
import json, re
import requests

s=requests.Session(); s.trust_env=False
H={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36','Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8'}

def req(method,url,**kw):
    try:
        r=s.request(method,url,headers={**H,**kw.pop('headers',{})},timeout=(8,20),allow_redirects=True,**kw)
        print('\n###',method,url,'STATUS',r.status_code,'FINAL',r.url,'TYPE',r.headers.get('content-type'),'LEN',len(r.content),flush=True)
        t=r.text
        print(t[:30000],flush=True)
        return r
    except Exception as e:
        print('\n### ERROR',method,url,repr(e),flush=True)
        return None

# Eastmoney report API exact variants
p={'pageSize':100,'beginTime':'2020-01-01','endTime':'2026-10-04','code':'605577','qType':'0','pageNo':'1'}
req('GET','https://reportapi.eastmoney.com/report/list',params=p,headers={'Referer':'https://data.eastmoney.com/report/605577.html'})
req('GET','https://reportapi.eastmoney.com/report/list',params={**p,'cb':'datatable','fields':'','p':'1','pageNum':'1','pageNumber':'1'},headers={'Referer':'https://data.eastmoney.com/report/605577.html'})

# Nxny stock report list
req('GET','https://www.nxny.com/stock/stock_605577/')

# Sina list
req('GET','https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml',params={'symbol':'sh605577','t1':'all'})
req('GET','https://vip.stock.finance.sina.com.cn/q/go.php/vReport_List/kind/search/index.phtml',params={'symbol':'sh605577'})

# sdyanbao public search API
for payload in [
 {'keyword':'龙版传媒','page':1,'pageSize':100},
 {'keyword':'605577','page':1,'pageSize':100},
 {'keyword':'龙版传媒','page':1,'pageSize':100,'order':0,'recommend':0,'hideTrader':0,'quanwen':True,'dateRange':0,'startTime':'','endTime':'','typeIds':'','industryIds':''},
]:
    req('POST','https://www.sdyanbao.com/api/file/search',json=payload,headers={'Content-Type':'application/json','Referer':'https://www.sdyanbao.com/report?keyword=龙版传媒'})

# fxbaogao and Bing public result HTML
req('GET','https://www.fxbaogao.com/search',params={'keyword':'龙版传媒'})
req('GET','https://www.bing.com/search',params={'q':'"龙版传媒" 券商 研报 PDF'})
