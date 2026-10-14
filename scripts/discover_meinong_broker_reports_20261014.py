#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
import requests

CODE = "301156"
BASE = "https://reportapi.eastmoney.com/report/list"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Referer": f"https://data.eastmoney.com/report/stock.jshtml?stockCode={CODE}",
}

session = requests.Session()
session.headers.update(HEADERS)

params_list = [
    {
        "cb": "datatable",
        "pageSize": "100",
        "beginTime": "2021-01-01",
        "endTime": "2026-10-14",
        "pageNo": "1",
        "fields": "",
        "qType": "0",
        "orgCode": "",
        "author": "",
        "code": CODE,
        "rcode": "",
        "p": "1",
        "pageNum": "1",
        "pageNumber": "1",
    },
    {
        "pageSize": "100",
        "beginTime": "2021-01-01",
        "endTime": "2026-10-14",
        "pageNo": "1",
        "qType": "0",
        "code": CODE,
        "p": "1",
        "pageNum": "1",
        "pageNumber": "1",
    },
]

for idx, params in enumerate(params_list, 1):
    try:
        r = session.get(BASE, params=params, timeout=60)
        print("REQUEST", idx, r.url)
        print("STATUS", r.status_code, r.headers.get("content-type"), len(r.content))
        print("HEAD", r.text[:800].replace("\n", " "))
        text = r.text.strip()
        if text.startswith("datatable(") and text.endswith(")"):
            text = text[len("datatable("):-1]
        elif text.startswith("datatable"):
            m = re.search(r"^[^(]+\((.*)\)\s*;?$", text, re.S)
            if m:
                text = m.group(1)
        try:
            data = json.loads(text)
        except Exception as exc:
            print("JSON_ERROR", repr(exc))
            continue
        print("TOP_KEYS", list(data) if isinstance(data, dict) else type(data).__name__)
        print("JSON", json.dumps(data, ensure_ascii=False)[:20000])
    except Exception as exc:
        print("ERROR", idx, repr(exc))
