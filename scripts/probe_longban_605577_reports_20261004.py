from __future__ import annotations

import json
import re
import time
from urllib.parse import urlencode

import requests

S = requests.Session()
S.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://data.eastmoney.com/",
}


def show(label: str, r: requests.Response, limit: int = 18000) -> None:
    print("\n===", label, "===", flush=True)
    print("STATUS", r.status_code, "URL", r.url, "TYPE", r.headers.get("content-type"), "LEN", len(r.content), flush=True)
    text = r.text
    print(text[:limit], flush=True)


def get(label: str, url: str, params=None, headers=None, limit=18000):
    try:
        r = S.get(url, params=params, headers={**HEADERS, **(headers or {})}, timeout=(20, 120), allow_redirects=True)
        show(label, r, limit)
        return r
    except Exception as e:
        print("\n===", label, "ERROR ===", repr(e), flush=True)
        return None


def post(label: str, url: str, data=None, json_data=None, headers=None, limit=18000):
    try:
        r = S.post(url, data=data, json=json_data, headers={**HEADERS, **(headers or {})}, timeout=(20, 120), allow_redirects=True)
        show(label, r, limit)
        return r
    except Exception as e:
        print("\n===", label, "ERROR ===", repr(e), flush=True)
        return None


# Eastmoney report API variants
base_params = {
    "pageSize": 100,
    "beginTime": "2020-01-01",
    "endTime": "2026-10-04",
    "code": "605577",
    "qType": "0",
    "pageNo": "1",
}
get("EASTMONEY_REPORT_API_JSON", "https://reportapi.eastmoney.com/report/list", params=base_params)
get("EASTMONEY_REPORT_API_JSONP", "https://reportapi.eastmoney.com/report/list", params={**base_params, "cb": "datatable", "fields": "", "p": 1, "pageNum": 1, "pageNumber": 1})
get("EASTMONEY_STOCK_REPORT_PAGE", "https://data.eastmoney.com/report/605577.html")
get("EASTMONEY_REPORT_SEARCH", "https://data.eastmoney.com/report/stock.jshtml", params={"stockCode":"605577"})

# Sina report list variants
get("SINA_REPORT_LIST_1", "https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml", params={"symbol":"sh605577","t1":"all"})
get("SINA_REPORT_LIST_2", "https://vip.stock.finance.sina.com.cn/q/go.php/vReport_List/kind/search/index.phtml", params={"symbol":"sh605577"})
get("SINA_REPORT_LIST_3", "https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml", params={"symbol":"605577"})

# 10jqka / stockstar pages
get("THS_WORTH", "https://basic.10jqka.com.cn/605577/worth.html")
get("STOCKSTAR_REPORT", "https://stock.quote.stockstar.com/report/605577.shtml")

# Nxny company report list and search
get("NXNY_STOCK", "https://www.nxny.com/stock/stock_605577/")
get("NXNY_SEARCH", "https://www.nxny.com/Search.aspx", params={"keyword":"龙版传媒"})

# Hibor public search variants
get("HIBOR_SEARCH", "https://www.hibor.com.cn/search.aspx", params={"keyword":"龙版传媒"})
get("HIBOR_WAP_SEARCH", "https://wap.hibor.com.cn/search.aspx", params={"keyword":"龙版传媒"})

# Sdyanbao API variants inferred from public JS
payloads = [
    {"keyword":"龙版传媒","page":1,"pageSize":100},
    {"keyword":"605577","page":1,"pageSize":100},
    {"keyword":"龙版传媒","page":1,"pageSize":100,"order":0,"recommend":0,"hideTrader":0,"quanwen":True,"dateRange":0,"startTime":"","endTime":"","typeIds":"","industryIds":""},
    {"keyword":"龙版传媒","page":1,"pageSize":100,"order":0,"recommend":0,"hideTrader":0,"isAll":1},
]
for i, payload in enumerate(payloads, start=1):
    post(f"SDYANBAO_API_JSON_{i}", "https://www.sdyanbao.com/api/file/search", json_data=payload, headers={"Content-Type":"application/json"})
    post(f"SDYANBAO_API_FORM_{i}", "https://www.sdyanbao.com/api/file/search", data=payload, headers={"Content-Type":"application/x-www-form-urlencoded"})
get("SDYANBAO_SEARCH_PAGE", "https://www.sdyanbao.com/report", params={"keyword":"龙版传媒"})

# FX report public search page
get("FXBAOGAO_SEARCH", "https://www.fxbaogao.com/search", params={"keyword":"龙版传媒"})
get("FXBAOGAO_SEARCH_2", "https://www.fxbaogao.com/search", params={"q":"龙版传媒"})

# General Bing HTML endpoint (may or may not work)
get("BING_HTML", "https://www.bing.com/search", params={"q":"\"龙版传媒\" 研报 PDF"}, limit=12000)
