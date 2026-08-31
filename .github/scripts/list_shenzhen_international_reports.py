from __future__ import annotations

import json
import re
from urllib.parse import urlencode

import requests

BASE = "https://api.sdyanbao.com"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36"
)

session = requests.Session()
session.headers.update(
    {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.sdyanbao.com",
        "Referer": "https://www.sdyanbao.com/",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
)


def show(url: str, *, method: str = "GET", json_body: dict | None = None) -> None:
    print("\n================", method, url, "================")
    try:
        response = session.request(
            method,
            url,
            json=json_body,
            timeout=(20, 120),
            allow_redirects=True,
        )
        print("STATUS", response.status_code)
        print("FINAL", response.url)
        print("TYPE", response.headers.get("Content-Type"))
        print("ALLOW", response.headers.get("Allow"))
        print("BYTES", len(response.content))
        text = response.text
        print("HEAD", text[:4000])
        try:
            payload = response.json()
        except Exception:
            payload = None
        if payload is not None:
            print("JSON_TYPE", type(payload).__name__)
            pretty = json.dumps(payload, ensure_ascii=False, indent=2)
            print("JSON_PRETTY_HEAD", pretty[:20000])
            for marker in (
                "深圳国际",
                "深圳國際",
                "掌握湾区优质资产",
                "土地转性贡献弹性",
                "国企优质资源禀赋",
                "多项目REITs",
            ):
                positions = [m.start() for m in re.finditer(re.escape(marker), pretty)]
                print("MARKER", marker, "COUNT", len(positions))
                for pos in positions[:10]:
                    print(pretty[max(0, pos - 1000):pos + 2500])
    except Exception as exc:
        print("ERROR", repr(exc))


# Known report details: 886501 is the complete 11-page Southwest report;
# 265012 mentions the desired 2022 Guohai Shenzhen International deep report
# in its related-research section.
for report_id in (886501, 265012, 4438234, 4788440):
    show(f"{BASE}/report/detail/{report_id}")

# Probe likely public search/list endpoints using common parameter names.
endpoints = [
    "/report/list",
    "/report/search",
    "/report/index",
    "/report",
    "/search",
    "/search/report",
    "/reports",
]
query_sets = [
    {"keyword": "深圳国际", "page": 1, "page_size": 50},
    {"keywords": "深圳国际", "page": 1, "page_size": 50},
    {"search": "深圳国际", "page": 1, "page_size": 50},
    {"q": "深圳国际", "page": 1, "page_size": 50},
    {"title": "深圳国际", "page": 1, "page_size": 50},
    {"keyword": "掌握湾区优质资产", "page": 1, "page_size": 50},
    {"keyword": "土地转性贡献弹性", "page": 1, "page_size": 50},
]
for endpoint in endpoints:
    for params in query_sets:
        show(f"{BASE}{endpoint}?{urlencode(params)}")

# A few POST variants, because some Nuxt list pages send JSON forms.
for endpoint in ("/report/list", "/report/search", "/search"):
    for body in (
        {"keyword": "深圳国际", "page": 1, "page_size": 50},
        {"keywords": "深圳国际", "page": 1, "page_size": 50},
        {"search": "深圳国际", "page": 1, "page_size": 50},
    ):
        show(f"{BASE}{endpoint}", method="POST", json_body=body)

# Discover API documentation or route metadata if publicly exposed.
for path in (
    "/openapi.json",
    "/swagger.json",
    "/docs",
    "/redoc",
    "/api-docs",
    "/routes",
    "/",
):
    show(BASE + path)
