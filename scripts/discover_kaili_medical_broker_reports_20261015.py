#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
import requests

CODE = "300633"
BASE = "https://reportapi.eastmoney.com/report/list"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Referer": f"https://data.eastmoney.com/report/stock.jshtml?stockCode={CODE}",
}

session = requests.Session()
session.headers.update(HEADERS)

for qtype in [0, 1, 2, 3, 4, 5]:
    params = {
        "cb": "datatable",
        "pageSize": "200",
        "beginTime": "2017-01-01",
        "endTime": "2026-10-15",
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
    response = session.get(BASE, params=params, timeout=60)
    print("QTYPE", qtype, "STATUS", response.status_code, "BYTES", len(response.content), response.url)
    response.raise_for_status()
    text = response.text.strip()
    if text.startswith("datatable(") and text.endswith(")"):
        text = text[len("datatable("):-1]
    else:
        match = re.search(r"^[^(]+\((.*)\)\s*;?$", text, re.S)
        if match:
            text = match.group(1)
    try:
        data = json.loads(text)
    except Exception as exc:
        print("JSON_ERROR", repr(exc), text[:1000])
        continue
    records = data.get("data") or []
    print("HITS", data.get("hits"), "SIZE", len(records), "TOTALPAGE", data.get("TotalPage"))
    for idx, record in enumerate(records, 1):
        print("RECORD", json.dumps({
            "idx": idx,
            "title": record.get("title"),
            "stockName": record.get("stockName"),
            "stockCode": record.get("stockCode"),
            "orgName": record.get("orgName"),
            "orgSName": record.get("orgSName"),
            "publishDate": record.get("publishDate"),
            "infoCode": record.get("infoCode"),
            "attachPages": record.get("attachPages"),
            "attachSize": record.get("attachSize"),
            "reportType": record.get("reportType"),
            "researcher": record.get("researcher"),
            "ratingName": record.get("emRatingName") or record.get("sRatingName"),
            "encodeUrl": record.get("encodeUrl"),
        }, ensure_ascii=False))
