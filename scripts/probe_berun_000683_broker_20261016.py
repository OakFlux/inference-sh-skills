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
seen = set()
selected = []
for page in range(1, 6):
    params = {
        "pageSize": "100",
        "pageNo": str(page),
        "code": "000683",
        "qType": "0",
        "industryCode": "*",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": "2010-01-01",
        "endTime": "2026-10-16",
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
        info = str(row.get("infoCode") or "")
        if not info or info in seen:
            continue
        seen.add(info)
        title = str(row.get("title") or "")
        pages = int(row.get("attachPages") or 0)
        if any(word in title for word in ("深度", "首次覆盖", "公司研究报告", "公司研究", "价值分析")) or pages >= 15:
            selected.append(row)

print("TOTAL_UNIQUE", len(seen), "SELECTED", len(selected), flush=True)
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
