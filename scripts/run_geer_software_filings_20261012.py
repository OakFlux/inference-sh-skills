from pathlib import Path

source_path = Path("scripts/run_tianrongxin_filings_20261012.py")
wrapper = source_path.read_text(encoding="utf-8")

replacements = {
    '\'CODE = "301301"\': \'CODE = "002212"\'': '\'CODE = "301301"\': \'CODE = "603232"\'',
    '\'COMPANY = "川宁生物"\': \'COMPANY = "天融信"\'': '\'COMPANY = "川宁生物"\': \'COMPANY = "格尔软件"\'',
    '\'FULL_COMPANY = "伊犁川宁生物技术股份有限公司"\': \'FULL_COMPANY = "天融信科技集团股份有限公司"\'': '\'FULL_COMPANY = "伊犁川宁生物技术股份有限公司"\': \'FULL_COMPANY = "格尔软件股份有限公司"\'',
    '\'LISTING_YEAR = 2022\': \'LISTING_YEAR = 2008\'': '\'LISTING_YEAR = 2022\': \'LISTING_YEAR = 2017\'',
    '\'VERIFY_DIR = Path("_verify_chuanning")\': \'VERIFY_DIR = Path("_verify_tianrongxin")\'': '\'VERIFY_DIR = Path("_verify_chuanning")\': \'VERIFY_DIR = Path("_verify_geer_software")\'',
    '\'ZIP_NAME = f"{COMPANY}_{CODE}_2022-2025全部年报_招股说明书_2026最新季报.zip"\': \'ZIP_NAME = f"{COMPANY}_{CODE}_2020-2025年报_最新季报_截至20261012.zip"\'': '\'ZIP_NAME = f"{COMPANY}_{CODE}_2022-2025全部年报_招股说明书_2026最新季报.zip"\': \'ZIP_NAME = f"{COMPANY}_{CODE}_2020-2025年报_最新季报_截至20261012.zip"\'',
    '\'identity_terms = ("川宁", "301301", "yili chuanning", "chuanning")\': \'identity_terms = ("天融信", "002212", "南洋股份", "topsec")\'': '\'identity_terms = ("川宁", "301301", "yili chuanning", "chuanning")\': \'identity_terms = ("格尔软件", "603232", "Koal", "格尔")\'',
}
for old, new in replacements.items():
    if old not in wrapper:
        raise RuntimeError(f"Expected wrapper fragment not found: {old}")
    wrapper = wrapper.replace(old, new, 1)

resolver_start = wrapper.index("resolver = r'''def find_org_id() -> str:")
resolver_end = wrapper.index("\n'''\nsource = source[:resolver_start]", resolver_start) + len("\n'''")
resolver_body = r"""def find_org_id() -> str:
    for warm_url in ("https://www.cninfo.com.cn/new/disclosure", "https://www.cninfo.com.cn/"):
        try:
            response = SESSION.get(warm_url, timeout=(20, 60))
            print("WARM", response.status_code, response.url, len(response.content), flush=True)
        except Exception as exc:
            print("WARM_FAILED", warm_url, repr(exc), flush=True)

    map_urls = (
        "https://www.cninfo.com.cn/new/data/sse_stock.json",
        "https://www.cninfo.com.cn/new/data/shse_stock.json",
        "https://www.cninfo.com.cn/new/data/sh_stock.json",
    )
    for map_url in map_urls:
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
                    code = str(item.get("code") or item.get("secCode") or "")
                    name = str(item.get("zwjc") or item.get("secName") or item.get("name") or "")
                    org_id = str(item.get("orgId") or item.get("orgid") or item.get("org_id") or "")
                    if org_id and (code == CODE or COMPANY in name or "格尔" in name):
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
                if any(key in value for key in ("orgId", "orgid", "org_id")):
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
                if org_id and (code == CODE or COMPANY in name or "格尔" in name):
                    print("ORG_ID_FROM_SEARCH", org_id, item, flush=True)
                    return org_id
        except Exception as exc:
            print("ORG_RESOLVER_FAILED", url, repr(exc), flush=True)

    raise RuntimeError(f"Unable to resolve CNINFO orgId for {CODE}")
"""
resolver_literal = "resolver = r'''" + resolver_body + "'''"
wrapper = wrapper[:resolver_start] + resolver_literal + wrapper[resolver_end:]

pagination_hook = 'source = source.replace("if page > 20:", "if page > 60:")'
if pagination_hook not in wrapper:
    raise RuntimeError("Unable to locate pagination hook")
wrapper = wrapper.replace(
    pagination_hook,
    pagination_hook
    + '\nsource = source.replace(\'"column": "szse"\', \'"column": "sse"\')'
    + '\nsource = source.replace(\'"plate": "sz"\', \'"plate": "sh"\')',
    1,
)

exec(compile(wrapper, str(source_path), "exec"), {"__name__": "__main__", "__file__": str(source_path)})
