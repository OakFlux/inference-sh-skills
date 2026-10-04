from __future__ import annotations

import json
from typing import Any

import requests

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://data.eastmoney.com/report/",
}

matches: dict[str, dict[str, Any]] = {}
for qtype in ("0", "1", "2"):
    for page in range(1, 31):
        params = {
            "industryCode": "*",
            "pageSize": "100",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": "2020-08-01",
            "endTime": "2020-08-10",
            "pageNo": str(page),
            "fields": "",
            "qType": qtype,
            "orgCode": "",
            "code": "",
            "rcode": "",
            "p": str(page),
            "pageNum": str(page),
            "pageNumber": str(page),
        }
        response = SESSION.get(
            "https://reportapi.eastmoney.com/report/list",
            params=params,
            headers=HEADERS,
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") or []
        total_pages = int(payload.get("TotalPage") or payload.get("totalPage") or 0)
        print(
            "PAGE",
            json.dumps(
                {
                    "qType": qtype,
                    "page": page,
                    "returned": len(rows),
                    "hits": payload.get("hits"),
                    "totalPages": total_pages,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        for row in rows:
            haystack = " ".join(
                str(row.get(key) or "")
                for key in (
                    "title",
                    "stockCode",
                    "stockName",
                    "stockCodes",
                    "stockNames",
                    "secuCode",
                    "secuName",
                )
            )
            if "天普股份" not in haystack and "605255" not in haystack:
                continue
            info_code = str(row.get("infoCode") or "")
            key = info_code or json.dumps(row, ensure_ascii=False, sort_keys=True)
            matches[key] = row
        if not rows or (total_pages and page >= total_pages):
            break

simplified = []
for row in matches.values():
    simplified.append(
        {
            key: row.get(key)
            for key in (
                "title",
                "publishDate",
                "orgSName",
                "orgName",
                "researcher",
                "infoCode",
                "attachPages",
                "attachSize",
                "emRatingName",
                "ratingChange",
                "reportType",
                "stockCode",
                "stockName",
                "stockCodes",
                "stockNames",
            )
        }
    )
print("MATCHES_JSON", json.dumps(simplified, ensure_ascii=False, indent=2), flush=True)
