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

def parse_payload(text: str):
    text = text.strip()
    m = re.search(r"^[^(]+\((.*)\)\s*;?$", text, re.S)
    if m:
        text = m.group(1)
    return json.loads(text)

for qtype in range(0, 8):
    params = {
        "cb": "datatable",
        "pageSize": "100",
        "beginTime": "2019-01-01",
        "endTime": "2026-10-14",
        "pageNo": "1",
        "fields": "",
        "qType": str(qtype),
        "orgCode": "",
        "author": "",
        "code": CODE,
        "rcode": "",
        "p": "1",
        "pageNum": "1",
        "pageNumber": "1",
    }
    try:
        r = session.get(BASE, params=params, timeout=60)
        print("QTYPE", qtype, "STATUS", r.status_code, "BYTES", len(r.content), "URL", r.url)
        data = parse_payload(r.text)
        print("SUMMARY", json.dumps({k:data.get(k) for k in ("hits","size","TotalPage","pageNo")}, ensure_ascii=False))
        for item in data.get("data") or []:
            print("ITEM", json.dumps({
                "title": item.get("title"),
                "orgName": item.get("orgName"),
                "publishDate": item.get("publishDate"),
                "infoCode": item.get("infoCode"),
                "attachPages": item.get("attachPages"),
                "attachSize": item.get("attachSize"),
                "reportType": item.get("reportType"),
                "researcher": item.get("researcher"),
                "encodeUrl": item.get("encodeUrl"),
            }, ensure_ascii=False))
    except Exception as exc:
        print("ERROR", qtype, repr(exc))
