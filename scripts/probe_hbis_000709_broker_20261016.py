import json
import requests

CODE = "000709"
END_DATE = "2026-10-16"

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://data.eastmoney.com/report/stock.jshtml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

all_rows = []
seen = set()
for page in range(1, 8):
    params = {
        "pageSize": "100",
        "pageNo": str(page),
        "code": CODE,
        "qType": "0",
        "industryCode": "*",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": "2010-01-01",
        "endTime": END_DATE,
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
    print("STATUS", page, response.status_code, response.headers.get("content-type"), len(response.content), response.url, flush=True)
    response.raise_for_status()
    rows = response.json().get("data") or []
    print("PAGE_COUNT", page, len(rows), flush=True)
    if not rows:
        break
    for row in rows:
        key = str(row.get("infoCode") or "")
        if key and key not in seen:
            seen.add(key)
            all_rows.append(row)

keywords = ("深度", "首次覆盖", "首次", "价值", "龙头", "研究报告", "公司研究")
selected = []
for row in all_rows:
    title = str(row.get("title") or "")
    pages = int(row.get("attachPages") or 0)
    if pages >= 15 or any(k in title for k in keywords):
        selected.append(row)

print("TOTAL_UNIQUE", len(all_rows), "SELECTED", len(selected), flush=True)
selected.sort(key=lambda r: str(r.get("publishDate") or ""), reverse=True)
for row in selected:
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
