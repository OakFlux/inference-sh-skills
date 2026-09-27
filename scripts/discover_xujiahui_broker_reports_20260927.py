from __future__ import annotations

import json
import random
import re
import time
from urllib.parse import urlencode

import requests

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
    "Accept": "application/json,text/javascript,*/*;q=0.8",
    "Referer": "https://data.eastmoney.com/report/002561.html",
}


def get(url: str, params: dict | None = None, timeout=(20, 120)) -> requests.Response:
    errors = []
    for attempt in range(1, 6):
        try:
            r = SESSION.get(url, params=params, headers=HEADERS, timeout=timeout, allow_redirects=True)
            print("HTTP", r.status_code, r.url, r.headers.get("content-type"), len(r.content), flush=True)
            r.raise_for_status()
            return r
        except Exception as exc:
            errors.append(repr(exc))
            time.sleep(min(attempt * 2, 8))
    raise RuntimeError(errors)


def parse_jsonp(text: str):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"^[^(]+\((.*)\)\s*;?\s*$", text, re.S)
        if not match:
            raise
        return json.loads(match.group(1))


def main():
    callback = f"datatable{random.randint(1000000, 9999999)}"
    params = {
        "cb": callback,
        "industryCode": "*",
        "pageSize": "100",
        "industry": "*",
        "rating": "*",
        "ratingchange": "*",
        "ratingChange": "*",
        "beginTime": "2010-01-01",
        "endTime": "2026-09-27",
        "pageNo": "1",
        "fields": "",
        "qType": "0",
        "orgCode": "",
        "code": "002561",
        "rcode": "",
        "_": str(int(time.time() * 1000)),
    }
    r = get("https://reportapi.eastmoney.com/report/list", params=params)
    print("RAW_HEAD", r.text[:500], flush=True)
    payload = parse_jsonp(r.text)
    print("SUMMARY", json.dumps({k: payload.get(k) for k in ("hits", "size", "TotalPage", "pageNo", "currentYear")}, ensure_ascii=False), flush=True)
    data = payload.get("data") or []
    for index, item in enumerate(data, 1):
        keep = {
            key: item.get(key)
            for key in [
                "title", "stockName", "stockCode", "orgCode", "orgName", "orgSName",
                "publishDate", "infoCode", "encodeUrl", "researcher", "researcherName",
                "sRatingName", "emRatingName", "predictThisYearEps", "predictNextYearEps",
                "indvInduName", "industryName", "attachType", "pdfUrl", "url",
            ]
            if key in item
        }
        print("REPORT", index, json.dumps(keep, ensure_ascii=False), flush=True)

    # Also inspect Eastmoney mobile detail/search pages derived from infoCode.
    for item in data[:20]:
        info = item.get("infoCode")
        if not info:
            continue
        for url in [
            f"https://wap.eastmoney.com/report/{info}.html",
            f"https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf",
            f"https://pdf.dfcfw.com/pdf/H3_{info}_01.pdf",
        ]:
            try:
                rr = get(url, timeout=(15, 60))
                print("CANDIDATE", info, rr.status_code, rr.url, rr.headers.get("content-type"), len(rr.content), rr.content[:8], flush=True)
                rr.close()
            except Exception as exc:
                print("CANDIDATE_FAIL", info, url, repr(exc), flush=True)


if __name__ == "__main__":
    main()
