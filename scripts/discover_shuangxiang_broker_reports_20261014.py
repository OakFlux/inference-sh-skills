#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
import requests

CODE = "002395"
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
    if text.startswith("datatable(") and text.endswith(")"):
        text = text[len("datatable("):-1]
    elif text.startswith("datatable"):
        match = re.search(r"^[^(]+\((.*)\)\s*;?$", text, re.S)
        if match:
            text = match.group(1)
    return json.loads(text)


for qtype in [0, 1, 2, 3, 4, 5]:
    params = {
        "pageSize": "100",
        "beginTime": "2009-01-01",
        "endTime": "2026-10-14",
        "pageNo": "1",
        "qType": str(qtype),
        "code": CODE,
        "p": "1",
        "pageNum": "1",
        "pageNumber": "1",
    }
    try:
        response = session.get(BASE, params=params, timeout=60)
        print("QTYPE", qtype, "STATUS", response.status_code, response.headers.get("content-type"), "BYTES", len(response.content))
        print("URL", response.url)
        response.raise_for_status()
        data = parse_payload(response.text)
        records = data.get("data") or []
        print("HITS", data.get("hits"), "SIZE", data.get("size"), "PAGES", data.get("TotalPage"))
        for idx, record in enumerate(records, 1):
            normalized = {
                "index": idx,
                "title": record.get("title"),
                "stockName": record.get("stockName"),
                "stockCode": record.get("stockCode"),
                "orgName": record.get("orgName"),
                "orgSName": record.get("orgSName"),
                "publishDate": record.get("publishDate"),
                "infoCode": record.get("infoCode"),
                "researcher": record.get("researcher"),
                "author": record.get("author"),
                "attachPages": record.get("attachPages"),
                "attachSize": record.get("attachSize"),
                "reportType": record.get("reportType"),
                "ratingName": record.get("emRatingName") or record.get("sRatingName"),
                "encodeUrl": record.get("encodeUrl"),
            }
            print("RECORD", json.dumps(normalized, ensure_ascii=False))
    except Exception as exc:
        print("ERROR", qtype, repr(exc))
