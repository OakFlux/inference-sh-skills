from __future__ import annotations

import json
from pathlib import Path

import requests

BASE = "https://www.cninfo.com.cn"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Referer": "https://www.cninfo.com.cn/new/disclosure/stock?stockCode=000503&orgId=gssz0000503",
    "X-Requested-With": "XMLHttpRequest",
}


def show(label: str, response: requests.Response) -> None:
    print(label, response.status_code, response.url, response.headers.get("content-type"), len(response.content), flush=True)
    print(response.text[:5000], flush=True)


def main() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)
    output: dict[str, object] = {}

    # Search company metadata / orgId.
    for endpoint, params in [
        ("/new/information/topSearch/query", {"keyWord": "000503", "maxSecNum": "10"}),
        ("/new/information/topSearch/query", {"keyWord": "国新健康", "maxSecNum": "10"}),
    ]:
        try:
            r = session.get(BASE + endpoint, params=params, timeout=60)
            show("TOP_SEARCH", r)
            output[f"top_{params['keyWord']}"] = {"status": r.status_code, "url": r.url, "text": r.text[:20000]}
        except Exception as exc:
            print("TOP_SEARCH_ERROR", params, repr(exc), flush=True)

    queries = [
        {"stock": "000503", "category": "category_ndbg_szsh", "label": "annual_stock_only"},
        {"stock": "000503", "category": "category_yjdbg_szsh", "label": "quarter_stock_only"},
        {"stock": "000503", "category": "", "label": "all_stock_only"},
        {"stock": "000503,gssz0000503", "category": "category_ndbg_szsh", "label": "annual_stock_org"},
        {"stock": "000503,gssz0000503", "category": "category_yjdbg_szsh", "label": "quarter_stock_org"},
        {"stock": "000503,gssz0000503", "category": "", "label": "all_stock_org"},
    ]
    for q in queries:
        data = {
            "pageNum": "1",
            "pageSize": "100",
            "column": "szse",
            "tabName": "fulltext",
            "plate": "sz",
            "stock": q["stock"],
            "searchkey": "",
            "secid": "",
            "category": q["category"],
            "trade": "",
            "seDate": "2020-01-01~2026-09-29",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        try:
            r = session.post(BASE + "/new/hisAnnouncement/query", data=data, timeout=90)
            show("QUERY_" + q["label"], r)
            try:
                parsed = r.json()
            except Exception:
                parsed = {"raw": r.text[:20000]}
            output[q["label"]] = parsed
        except Exception as exc:
            print("QUERY_ERROR", q, repr(exc), flush=True)

    Path("guoxin_health_filings_inspection.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
