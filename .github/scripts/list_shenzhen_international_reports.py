from __future__ import annotations

import json

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
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://www.sdyanbao.com",
        "Referer": "https://www.sdyanbao.com/report?keyword=%E6%B7%B1%E5%9C%B3%E5%9B%BD%E9%99%85",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "X-Token": "",
        "Device": "1",
    }
)

MARKERS = (
    "深圳国际",
    "深圳國際",
    "掌握湾区优质资产",
    "土地转性贡献弹性",
    "国企优质资源禀赋",
    "多项目REITs",
    "华南物流园增值添利",
)


def post(path: str, body: dict) -> object:
    payload = dict(body)
    payload.setdefault("opFrom", 1)
    url = BASE + path
    response = session.post(url, json=payload, timeout=(20, 120), allow_redirects=True)
    print("\nPOST", url, "BODY", json.dumps(payload, ensure_ascii=False))
    print("STATUS", response.status_code, "TYPE", response.headers.get("Content-Type"), "BYTES", len(response.content))
    print("HEAD", response.text[:1200].replace("\n", " "))
    response.raise_for_status()
    try:
        result = response.json()
    except Exception:
        return response.text
    pretty = json.dumps(result, ensure_ascii=False, indent=2)
    print("JSON_HEAD", pretty[:30000])
    for marker in MARKERS:
        count = pretty.count(marker)
        if count:
            print("MARKER", marker, "COUNT", count)
    return result


# Verify the endpoint and response schema using the known complete Southwest report.
for body in ({"id": 886501}, {"id": "886501"}):
    try:
        post("/api/file/detail", body)
    except Exception as exc:
        print("DETAIL_ERROR", repr(exc))

# Search with payload variants observed across the Nuxt listing/search components.
search_bodies: list[dict] = []
for keyword in (
    "深圳国际",
    "掌握湾区优质资产",
    "土地转性贡献弹性",
    "国企优质资源禀赋",
    "多项目REITs",
):
    for page_key in ("page", "pageNo", "currentPage"):
        body = {page_key: 1, "pageSize": 100, "keyword": keyword}
        search_bodies.append(body)
    search_bodies.extend(
        [
            {"page": 1, "pageSize": 100, "search_key": keyword},
            {"page": 1, "pageSize": 100, "searchKey": keyword},
            {"page": 1, "pageSize": 100, "keyWord": keyword},
            {"page": 1, "pageSize": 100, "title": keyword},
        ]
    )

seen_payloads: set[str] = set()
for body in search_bodies:
    signature = json.dumps(body, ensure_ascii=False, sort_keys=True)
    if signature in seen_payloads:
        continue
    seen_payloads.add(signature)
    try:
        post("/api/file/search", body)
    except Exception as exc:
        print("SEARCH_ERROR", repr(exc))

# Related lists may expose older company reports even when free-text search behaves differently.
for path in ("/api/file/similarlist", "/api/file/sameOrganizationlist"):
    for body in (
        {"id": 886501, "pageSize": 100},
        {"id": 886501, "page": 1, "pageSize": 100},
    ):
        try:
            post(path, body)
        except Exception as exc:
            print("RELATED_ERROR", path, repr(exc))
