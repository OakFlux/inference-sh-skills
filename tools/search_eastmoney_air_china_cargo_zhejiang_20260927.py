from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests

OUT = Path("eastmoney_air_china_cargo_search.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/report/stock.jshtml",
    "Accept": "application/json,text/plain,*/*",
}


def decode(text: str) -> Any:
    text = text.strip().lstrip("\ufeff")
    try:
        return json.loads(text)
    except Exception:
        m = re.match(r"^[^(]+\((.*)\)\s*;?$", text, re.S)
        if not m:
            raise
        return json.loads(m.group(1))


def rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            for key in ("list", "records", "items"):
                v = data.get(key)
                if isinstance(v, list):
                    return [x for x in v if isinstance(x, dict)]
    return []


def main() -> None:
    s = requests.Session(); s.headers.update(HEADERS)
    attempts = []
    variants = []
    for qtype in (0, 1, 2, 3):
        for code in ("001391", "SZ001391", "", "1391"):
            variants.append((f"q{qtype}_code_{code or 'none'}", {
                "cb":"datatable123456", "industryCode":"*", "pageSize":"500", "industry":"*",
                "rating":"*", "ratingChange":"*", "beginTime":"2025-12-01", "endTime":"2026-01-31",
                "pageNo":"1", "fields":"", "qType":str(qtype), "orgCode":"", "code":code,
                "rcode":"", "p":"1", "pageNum":"1", "pageNumber":"1"
            }))
    variants += [
        ("broad_2025", {"cb":"datatable123456", "industryCode":"*", "pageSize":"500", "industry":"*", "rating":"*", "ratingChange":"*", "beginTime":"2025-01-01", "endTime":"2026-09-27", "pageNo":"1", "fields":"", "qType":"0", "orgCode":"", "code":"", "rcode":"", "p":"1", "pageNum":"1", "pageNumber":"1"}),
        ("broad_dec_jan", {"cb":"datatable123456", "industryCode":"*", "pageSize":"1000", "industry":"*", "rating":"*", "ratingChange":"*", "beginTime":"2025-12-20", "endTime":"2026-01-10", "pageNo":"1", "fields":"", "qType":"0", "orgCode":"", "code":"", "rcode":"", "p":"1", "pageNum":"1", "pageNumber":"1"}),
    ]
    for label, params in variants:
        try:
            r=s.get("https://reportapi.eastmoney.com/report/list", params=params, timeout=120)
            p=decode(r.text); rs=rows(p)
            matches=[]
            for x in rs:
                blob=json.dumps(x, ensure_ascii=False)
                if any(t in blob for t in ("国货航", "001391", "跨境电商方兴未艾", "航空货运龙头顺势而为", "李丹", "李逸")):
                    matches.append(x)
            rec={"label":label,"status":r.status_code,"bytes":len(r.content),"url":r.url,"hits":p.get("hits") if isinstance(p,dict) else None,"row_count":len(rs),"matches":matches}
            attempts.append(rec)
            print("ATTEMPT", json.dumps({k:rec[k] for k in ("label","status","bytes","hits","row_count")}, ensure_ascii=False), flush=True)
            for m in matches: print("MATCH", json.dumps(m, ensure_ascii=False), flush=True)
        except Exception as e:
            attempts.append({"label":label,"error":repr(e)})
            print("ERROR", label, repr(e), flush=True)
    OUT.write_text(json.dumps(attempts, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__": main()
