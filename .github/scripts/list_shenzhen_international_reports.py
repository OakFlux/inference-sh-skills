from __future__ import annotations

import json
from typing import Any

import requests

BASE = "https://api.sdyanbao.com"
MARKERS = (
    "深圳国际",
    "深圳國際",
    "掌握湾区优质资产",
    "土地转性贡献弹性",
    "国企优质资源禀赋",
    "多项目REITs",
    "华南物流园增值添利",
)

session = requests.Session()
session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://www.sdyanbao.com",
        "Referer": "https://www.sdyanbao.com/report?keyword=%E6%B7%B1%E5%9C%B3%E5%9B%BD%E9%99%85",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "X-Token": "",
        "Device": "1",
    }
)


def post(path: str, body: dict[str, Any]) -> Any:
    payload = {**body, "opFrom": 1}
    response = session.post(BASE + path, json=payload, timeout=(20, 120))
    print("CALL", path, json.dumps(payload, ensure_ascii=False), "STATUS", response.status_code)
    response.raise_for_status()
    return response.json()


def iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_dicts(child)


def compact_record(record: dict[str, Any]) -> dict[str, Any]:
    preferred = (
        "id", "file_id", "original_id", "title", "name", "file_name",
        "organization", "organization_name", "author", "publish_time",
        "publish_date", "release_time", "page_count", "pages", "page_url",
        "online_url", "share_url", "source_url", "pdf_url", "download_url",
        "report_date", "created_at", "updated_at",
    )
    output = {key: record.get(key) for key in preferred if key in record}
    if not output:
        output = {key: value for key, value in record.items() if not isinstance(value, (dict, list))}
    return output


def print_matches(label: str, payload: Any) -> None:
    matches: dict[str, dict[str, Any]] = {}
    for record in iter_dicts(payload):
        serialized = json.dumps(record, ensure_ascii=False)
        if any(marker in serialized for marker in MARKERS):
            compact = compact_record(record)
            signature = json.dumps(compact, ensure_ascii=False, sort_keys=True)
            matches[signature] = compact
    print("RESULT", label, "MATCH_COUNT", len(matches))
    for compact in matches.values():
        print("MATCH", json.dumps(compact, ensure_ascii=False, sort_keys=True))


# Known report detail verifies schema and gives the full public page directory.
for report_id in (886501, 265012):
    try:
        payload = post("/api/file/detail", {"id": report_id})
        print_matches(f"detail_{report_id}", payload)
    except Exception as exc:
        print("ERROR detail", report_id, repr(exc))

# Use only the most plausible request schemas so the log stays compact.
for keyword in (
    "深圳国际",
    "掌握湾区优质资产",
    "土地转性贡献弹性",
    "国企优质资源禀赋",
    "多项目REITs",
):
    bodies = (
        {"page": 1, "pageSize": 100, "keyword": keyword},
        {"page": 1, "pageSize": 100, "search_key": keyword},
        {"pageNo": 1, "pageSize": 100, "keyword": keyword},
    )
    for index, body in enumerate(bodies, 1):
        try:
            payload = post("/api/file/search", body)
            print_matches(f"search_{keyword}_{index}", payload)
        except Exception as exc:
            print("ERROR search", keyword, index, repr(exc))

for path in ("/api/file/similarlist", "/api/file/sameOrganizationlist"):
    try:
        payload = post(path, {"id": 886501, "page": 1, "pageSize": 100})
        print_matches(path, payload)
    except Exception as exc:
        print("ERROR related", path, repr(exc))
