from __future__ import annotations

import html
import json
import re
import time
from urllib.parse import quote, unquote, urlparse, parse_qs

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36"
)
session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})

TITLES = [
    "平台型医美新星 盈利有望释放",
    "跨越制药边界 成就美与创新",
    "始于乐提葆 医美平台化",
    "医美和创新药双轮驱动 业绩逐步进入兑现期",
]


def compact(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def match_record(row: dict) -> bool:
    text = compact(json.dumps(row, ensure_ascii=False))
    return any(
        marker in text
        for marker in (
            "四环医药", "四環醫藥", "平台型医美新星", "跨越制药边界",
            "始于乐提葆", "医美和创新药双轮驱动",
        )
    )


def show_rows(label: str, payload: object) -> None:
    print("\n=====", label, "=====")
    if not isinstance(payload, dict):
        print("PAYLOAD", repr(payload)[:2000])
        return
    rows = payload.get("data") or payload.get("Data") or []
    print("META", {k: payload.get(k) for k in ("hits", "size", "TotalPage", "pageNo", "total", "TotalCount") if k in payload})
    print("ROWS", len(rows))
    for row in rows:
        if match_record(row):
            print("MATCH", json.dumps(row, ensure_ascii=False)[:10000])


WINDOWS = [
    ("2026-05-25", "2026-06-06"),
    ("2026-08-20", "2026-09-02"),
    ("2025-06-01", "2025-06-15"),
    ("2023-07-01", "2023-07-12"),
]

for begin, end in WINDOWS:
    for page in range(1, 6):
        params = {
            "industryCode": "*",
            "pageSize": 500,
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": begin,
            "endTime": end,
            "pageNo": page,
            "fields": "",
            "qType": 0,
            "orgCode": "",
            "rcode": "",
            "_": int(time.time() * 1000),
        }
        try:
            response = session.get("https://reportapi.eastmoney.com/report/list", params=params, timeout=(20, 180))
            print("GET list", begin, end, page, response.status_code, len(response.content), response.url)
            response.raise_for_status()
            payload = response.json()
            show_rows(f"GET {begin}..{end} page {page}", payload)
            rows = payload.get("data") or []
            if not rows or len(rows) < 500:
                break
        except Exception as exc:
            print("ERROR GET list", begin, end, page, repr(exc))
            break

    for code in ("", "*", "00460", "116.00460"):
        body = {
            "pageSize": 500,
            "pageNo": 1,
            "p": 1,
            "pageNum": 1,
            "pageNumber": 1,
            "beginTime": begin,
            "endTime": end,
            "code": code,
            "industryCode": "*",
            "rating": None,
            "ratingChange": None,
            "orgCode": None,
            "rcode": "",
        }
        try:
            response = session.post(
                "https://reportapi.eastmoney.com/report/list2",
                json=body,
                headers={"Content-Type": "application/json", "Referer": "https://data.eastmoney.com/report/stock.jshtml"},
                timeout=(20, 180),
            )
            print("POST list2", begin, end, repr(code), response.status_code, len(response.content))
            response.raise_for_status()
            show_rows(f"POST {begin}..{end} code={code!r}", response.json())
        except Exception as exc:
            print("ERROR POST list2", begin, end, repr(code), repr(exc))


print("\n\n================ SEARCH ENGINES ================")
queries = []
for title in TITLES:
    queries.extend(
        [
            f'"{title}" pdf',
            f'"{title}" filetype:pdf',
            f'"{title}" site:pdf.dfcfw.com',
            f'"{title}" 四环医药',
        ]
    )

for query in queries:
    print("\nQUERY", query)
    engines = [
        ("bing", "https://www.bing.com/search?q=" + quote(query)),
        ("baidu", "https://www.baidu.com/s?wd=" + quote(query)),
        ("so", "https://www.so.com/s?q=" + quote(query)),
    ]
    for name, url in engines:
        try:
            response = session.get(url, timeout=(20, 120), allow_redirects=True)
            print(name, response.status_code, len(response.content), response.url)
            response.raise_for_status()
            text = html.unescape(response.text).replace("\\/", "/")
            links: list[str] = []
            for raw in re.findall(r'https?://[^\"\'<>\s]+', text, flags=re.I):
                candidate = raw.rstrip("),;]}")
                if "baidu.com/link?url=" in candidate:
                    pass
                if any(
                    marker in candidate.lower()
                    for marker in (
                        ".pdf", "dfcfw", "report", "yanbao", "fxbaogao", "nxny",
                        "hfzq", "gtja", "tpyzq", "tebon", "firstshanghai", "static",
                    )
                ):
                    links.append(candidate)
            for candidate in dict.fromkeys(links):
                print("LINK", candidate[:2000])
            # Search contexts for AP info codes and pdf domains.
            for pattern in (
                r"AP\d{15,24}",
                r"https?://[^\"\'<>\s]+?\.pdf(?:\?[^\"\'<>\s]*)?",
                r"pdf\.dfcfw\.com[^\"\'<>\s]+",
            ):
                for match in dict.fromkeys(re.findall(pattern, text, flags=re.I)):
                    print("FOUND", match[:2000])
        except Exception as exc:
            print("ERROR", name, repr(exc))
