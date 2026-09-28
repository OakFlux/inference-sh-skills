from pathlib import Path

source_path = Path('scripts/build_chuanning_filings_20260928.py')
source = source_path.read_text(encoding='utf-8')
start = source.index('def find_org_id() -> str:')
end = source.index('\ndef query_announcements(org_id: str)', start)

replacement = r'''def find_org_id() -> str:
    # Warm the session first so CNINFO can set any routing/session cookies.
    for warm_url in (
        "https://www.cninfo.com.cn/new/disclosure",
        "https://www.cninfo.com.cn/",
    ):
        try:
            response = SESSION.get(warm_url, timeout=(20, 60))
            print("WARM", response.status_code, response.url, len(response.content), flush=True)
        except Exception as exc:
            print("WARM_FAILED", warm_url, repr(exc), flush=True)

    # Primary resolver: the official CNINFO Shenzhen stock/orgId mapping table.
    for map_url in (
        "https://www.cninfo.com.cn/new/data/szse_stock.json",
        "http://www.cninfo.com.cn/new/data/szse_stock.json",
    ):
        try:
            response = SESSION.get(
                map_url,
                headers={
                    "Accept": "application/json,text/plain,*/*",
                    "Referer": "https://www.cninfo.com.cn/new/disclosure",
                },
                timeout=(20, 120),
                allow_redirects=True,
            )
            print(
                "STOCK_MAP",
                response.status_code,
                response.headers.get("content-type"),
                len(response.content),
                response.url,
                flush=True,
            )
            if response.ok:
                data = response.json()
                stock_list = data.get("stockList") if isinstance(data, dict) else data
                for item in stock_list or []:
                    code = str(item.get("code") or "")
                    name = str(item.get("zwjc") or item.get("name") or "")
                    org_id = str(item.get("orgId") or item.get("orgid") or "")
                    if org_id and (code == CODE or COMPANY in name or "川宁" in name):
                        print("ORG_ID_FROM_MAP", org_id, item, flush=True)
                        return org_id
        except Exception as exc:
            print("STOCK_MAP_FAILED", map_url, repr(exc), flush=True)

    # Secondary resolver: both currently observed official form endpoints.
    resolver_calls = [
        (
            "https://www.cninfo.com.cn/new/information/topSearch/detailOfQuery",
            {"keyWord": CODE, "maxSecNum": "20", "maxListNum": "10"},
        ),
        (
            "https://www.cninfo.com.cn/new/information/topSearch/query",
            {"keyWord": CODE, "maxNum": "20"},
        ),
        (
            "https://www.cninfo.com.cn/new/information/topSearch/detailOfQuery",
            {"keyWord": COMPANY, "maxSecNum": "20", "maxListNum": "10"},
        ),
    ]

    def candidate_dicts(obj):
        found = []
        def walk(value):
            if isinstance(value, dict):
                if any(k in value for k in ("orgId", "orgid", "org_id")):
                    found.append(value)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(obj)
        return found

    for url, payload in resolver_calls:
        try:
            response = request_with_retry(
                "POST",
                url,
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Accept": "application/json,text/plain,*/*",
                    "Referer": "https://www.cninfo.com.cn/new/disclosure",
                },
            )
            data = response.json()
            print("ORG_RESOLVER", url, json.dumps(data, ensure_ascii=False)[:4000], flush=True)
            for item in candidate_dicts(data):
                code = str(item.get("code") or item.get("secCode") or item.get("stockCode") or "")
                name = str(item.get("zwjc") or item.get("secName") or item.get("name") or "")
                org_id = str(item.get("orgId") or item.get("orgid") or item.get("org_id") or "")
                if org_id and (code == CODE or COMPANY in name or "川宁" in name):
                    print("ORG_ID_FROM_SEARCH", org_id, item, flush=True)
                    return org_id
        except Exception as exc:
            print("ORG_RESOLVER_FAILED", url, repr(exc), flush=True)

    # Last-resort legacy Shenzhen pattern. The subsequent announcement query is
    # required to return matching company rows, so a bad fallback cannot silently pass.
    fallback = f"gssz0{CODE}"
    print("ORG_ID_LEGACY_FALLBACK", fallback, flush=True)
    return fallback
'''

patched = source[:start] + replacement + source[end:]
exec(compile(patched, str(source_path), 'exec'), {'__name__': '__main__', '__file__': str(source_path)})
