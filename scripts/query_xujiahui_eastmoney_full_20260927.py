from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

OUT = Path("xujiahui_exact_history_search.json")
SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.fxbaogao.com",
    "Referer": "https://www.fxbaogao.com/",
}
API = "https://api.fxbaogao.com/mofoun/report/searchReport/searchNoAuth"
PUBLIC = "https://public.fxbaogao.com/"
SEARCHES = [
    "徐家汇 优质商圈 高盈利能力 高分红",
    "优质商圈 高盈利能力 高分红",
    "徐家汇 主业经营稳健 持续深化全渠道布局",
    "主业经营稳健 持续深化全渠道布局",
    "徐家汇 经营稳健 加速推进全渠道融合",
    "经营稳健 加速推进全渠道融合",
    "徐家汇 新股价值分析 自有物业比重高",
    "徐家汇 上海老牌百货 厚积薄发",
    "徐家汇 百货零售企业",
]


def post(payload: dict) -> dict:
    errors = []
    for attempt in range(1, 6):
        try:
            response = SESSION.post(API, json=payload, headers=HEADERS, timeout=(20, 120))
            print("POST", attempt, response.status_code, len(response.content), json.dumps(payload, ensure_ascii=False), flush=True)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            errors.append(repr(exc))
            time.sleep(min(attempt * 2, 8))
    raise RuntimeError(errors)


def clean(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")

results = []
for keyword in SEARCHES:
    for order in ("1", "0", "2"):
        payload = {
            "order": order,
            "pdfPage": "-1",
            "pageNum": 1,
            "pageSize": 20,
            "paragraphSize": 3,
            "keywords": keyword,
        }
        obj = post(payload)
        data = obj.get("data") or {}
        rows = data.get("dataList") or []
        summary = {
            "keyword": keyword,
            "order": order,
            "count": data.get("count"),
            "pageCount": data.get("pageCount"),
            "rows": rows,
        }
        results.append(summary)
        print("QUERY", keyword, "order", order, "count", data.get("count"), "rows", len(rows), flush=True)
        for row in rows:
            title = clean(str(row.get("title") or ""))
            info = {
                "docId": row.get("docId"),
                "title": title,
                "orgName": row.get("orgName"),
                "authors": row.get("authors"),
                "pubTimeStr": row.get("pubTimeStr"),
                "pageNum": row.get("pageNum"),
                "pdfPath": row.get("pdfPath"),
                "fileUrl": row.get("fileUrl"),
                "publicUrl": PUBLIC + str(row.get("pdfPath") or "").lstrip("/"),
                "isDeep": row.get("isDeep"),
                "reportType": row.get("reportType"),
            }
            if "徐家汇" in title or any(term in title for term in ("优质商圈", "主业经营稳健", "经营稳健", "上海老牌百货", "自有物业比重高")):
                print("MATCH", json.dumps(info, ensure_ascii=False), flush=True)

OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
