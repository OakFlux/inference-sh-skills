from __future__ import annotations

import json
import requests

TARGETS = [
    ("2024-06-01", "2024-06-10"),
    ("2024-12-01", "2024-12-15"),
    ("2022-11-01", "2022-11-15"),
    ("2025-05-01", "2025-05-10"),
]
KEYWORDS = [
    "国网信通",
    "电力数字化行业龙头",
    "算力集群电能需求",
    "电网数字化建设核心受益",
    "能源互联网打造第二增长极",
    "国网系信息通信服务商",
    "云网融合优势突出",
    "收购释放协同效应",
]

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Referer": "https://data.eastmoney.com/",
})

for begin, end in TARGETS:
    page = 1
    while True:
        params = {
            "industryCode": "*",
            "pageSize": 100,
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": begin,
            "endTime": end,
            "pageNo": page,
            "fields": "",
            "qType": 0,
            "orgCode": "",
            "code": "",
            "rcode": "",
            "p": page,
            "pageNum": page,
            "pageNumber": page,
        }
        r = s.get("https://reportapi.eastmoney.com/report/list", params=params, timeout=(20, 120))
        print("CALL", begin, end, page, r.status_code, len(r.content), r.url, flush=True)
        r.raise_for_status()
        data = r.json()
        rows = data.get("data") or []
        if isinstance(rows, dict):
            rows = rows.get("data") or rows.get("list") or []
        for row in rows:
            blob = " ".join(str(row.get(k) or "") for k in ["title", "stockName", "stockCode", "orgSName", "researcher"])
            if any(keyword in blob for keyword in KEYWORDS):
                print("MATCH", json.dumps(row, ensure_ascii=False), flush=True)
        total_pages = int(data.get("TotalPage") or data.get("totalPage") or 1)
        if page >= total_pages:
            break
        page += 1
        if page > 50:
            break
