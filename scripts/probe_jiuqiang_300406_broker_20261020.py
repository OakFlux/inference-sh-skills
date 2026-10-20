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
all_rows = []
for page_no in range(1, 4):
    params = {
        "pageSize": "100",
        "pageNo": str(page_no),
        "code": "300406",
        "qType": "0",
        "industryCode": "*",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": "2010-01-01",
        "endTime": "2026-10-20",
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
    print("STATUS", page_no, response.status_code, response.headers.get("content-type"), len(response.content), response.url, flush=True)
    response.raise_for_status()
    rows = response.json().get("data") or []
    print("PAGE_COUNT", page_no, len(rows), flush=True)
    all_rows.extend(rows)
    if len(rows) < 100:
        break

seen = set()
unique = []
for row in all_rows:
    code = str(row.get("infoCode") or "")
    if not code or code in seen:
        continue
    seen.add(code)
    unique.append(row)

selected = []
for row in unique:
    title = str(row.get("title") or "")
    pages = int(row.get("attachPages") or 0)
    if pages >= 12 or any(k in title for k in ("深度", "首次覆盖", "公司研究", "专题研究", "价值分析")):
        selected.append(row)

print("TOTAL_UNIQUE", len(unique), "SELECTED", len(selected), flush=True)
for row in selected:
    output = {key: row.get(key) for key in [
        "title", "stockName", "stockCode", "orgName", "orgSName", "publishDate",
        "infoCode", "attachPages", "attachSize", "researcher", "emRatingName", "sRatingName"
    ]}
    print("ROW", json.dumps(output, ensure_ascii=False), flush=True)
