import json
import requests

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://data.eastmoney.com/report/stock.jshtml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
params = {
    "pageSize": "100",
    "pageNo": "2",
    "code": "002557",
    "qType": "0",
    "industryCode": "*",
    "industry": "*",
    "rating": "*",
    "ratingChange": "*",
    "beginTime": "2010-01-01",
    "endTime": "2026-10-15",
    "orgCode": "",
    "rcode": "",
    "fields": "",
}
response = session.get(
    "https://reportapi.eastmoney.com/report/list",
    params=params,
    headers=headers,
    timeout=90,
)
print("STATUS", response.status_code, response.headers.get("content-type"), len(response.content), response.url, flush=True)
response.raise_for_status()
rows = response.json().get("data") or []
print("COUNT", len(rows), flush=True)
for row in rows:
    output = {
        key: row.get(key)
        for key in [
            "title",
            "stockName",
            "stockCode",
            "orgName",
            "orgSName",
            "publishDate",
            "infoCode",
            "attachPages",
            "attachSize",
            "researcher",
            "emRatingName",
            "sRatingName",
        ]
    }
    print("ROW", json.dumps(output, ensure_ascii=False), flush=True)
