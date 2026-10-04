from pathlib import Path

base_path = Path("scripts/build_chuanning_filings_20260928.py")
source = base_path.read_text(encoding="utf-8")

replacements = {
    'CODE = "301301"': 'CODE = "301257"',
    'COMPANY = "川宁生物"': 'COMPANY = "普蕊斯"',
    'FULL_COMPANY = "伊犁川宁生物技术股份有限公司"': 'FULL_COMPANY = "普蕊斯（上海）医药科技开发股份有限公司"',
    'AS_OF = "2026-09-28"': 'AS_OF = "2026-10-04"',
    'identity_terms = ("川宁", "301301", "yili chuanning", "chuanning")': 'identity_terms = ("普蕊斯", "301257", "Puruisi", "Puris")',
}
for old, new in replacements.items():
    if old not in source:
        raise RuntimeError(f"Expected source fragment not found: {old}")
    source = source.replace(old, new, 1)

# Replace the older CNINFO orgId resolver with the resilient stock-map/form resolver.
start = source.index("def find_org_id() -> str:")
end = source.index("\ndef query_announcements(org_id: str)", start)
resolver = r'''def find_org_id() -> str:
    for warm_url in (
        "https://www.cninfo.com.cn/new/disclosure",
        "https://www.cninfo.com.cn/",
    ):
        try:
            response = SESSION.get(warm_url, timeout=(20, 60))
            print("WARM", response.status_code, response.url, len(response.content), flush=True)
        except Exception as exc:
            print("WARM_FAILED", warm_url, repr(exc), flush=True)

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
                    if org_id and (code == CODE or COMPANY in name or "普蕊斯" in name):
                        print("ORG_ID_FROM_MAP", org_id, item, flush=True)
                        return org_id
        except Exception as exc:
            print("STOCK_MAP_FAILED", map_url, repr(exc), flush=True)

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
                if org_id and (code == CODE or COMPANY in name or "普蕊斯" in name):
                    print("ORG_ID_FROM_SEARCH", org_id, item, flush=True)
                    return org_id
        except Exception as exc:
            print("ORG_RESOLVER_FAILED", url, repr(exc), flush=True)

    fallback = f"gssz0{CODE}"
    print("ORG_ID_LEGACY_FALLBACK", fallback, flush=True)
    return fallback
'''
source = source[:start] + resolver + source[end:]

# CNINFO caps responses at 30 rows even when a larger page size is requested.
source = source.replace('"pageSize": "100"', '"pageSize": "30"')
source = source.replace("if page * 100 >= total:", "if page * 30 >= total:")
source = source.replace("if page > 20:", "if page > 60:")

# Support both long and short quarterly-report title forms.
source = source.replace("(?:第一|第三)季度报告", "(?:第一|第三|一|三)季度报告")
source = source.replace("(第一|第三)季度报告", "(第一|第三|一|三)季度报告")
source = source.replace(
    'q = "Q1" if zh_quarter == "第一" else "Q3"',
    'q = "Q1" if zh_quarter in ("第一", "一") else "Q3"',
)

exec(compile(source, str(base_path), "exec"), {"__name__": "__main__", "__file__": str(base_path)})
