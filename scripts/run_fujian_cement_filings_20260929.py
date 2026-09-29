from pathlib import Path

source_path = Path('scripts/build_chuanning_filings_20260928.py')
source = source_path.read_text(encoding='utf-8')

# Re-target the validated CNINFO workflow to Fujian Cement (SSE: 600802).
source = source.replace('CODE = "301301"', 'CODE = "600802"')
source = source.replace('COMPANY = "川宁生物"', 'COMPANY = "福建水泥"')
source = source.replace(
    'FULL_COMPANY = "伊犁川宁生物技术股份有限公司"',
    'FULL_COMPANY = "福建水泥股份有限公司"'
)
source = source.replace('AS_OF = "2026-09-28"', 'AS_OF = "2026-09-29"')
source = source.replace('LISTING_YEAR = 2022', 'LISTING_YEAR = 1994')
source = source.replace(
    'EXPECTED_ANNUAL_YEARS = [2022, 2023, 2024, 2025]',
    'EXPECTED_ANNUAL_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]'
)
source = source.replace(
    'ZIP_NAME = f"{COMPANY}_{CODE}_2022-2025全部年报_招股说明书_2026最新季报.zip"',
    'ZIP_NAME = f"{COMPANY}_{CODE}_2020-2025年报_2026最新季报.zip"'
)

# Resolve the issuer from CNINFO's official Shanghai stock mapping table.
find_start = source.index('def find_org_id() -> str:')
find_end = source.index('\ndef query_announcements(org_id: str)', find_start)
find_replacement = r'''def find_org_id() -> str:
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
        "https://www.cninfo.com.cn/new/data/sse_stock.json",
        "http://www.cninfo.com.cn/new/data/sse_stock.json",
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
                    if org_id and (code == CODE or COMPANY in name or "福建水泥" in name):
                        print("ORG_ID_FROM_MAP", org_id, item, flush=True)
                        return org_id
        except Exception as exc:
            print("STOCK_MAP_FAILED", map_url, repr(exc), flush=True)

    fallback = f"gssh0{CODE}"
    print("ORG_ID_LEGACY_FALLBACK", fallback, flush=True)
    return fallback
'''
source = source[:find_start] + find_replacement + source[find_end:]

# Query the Shanghai disclosure column, extend the requested date range, and
# respect CNINFO's effective 30-row response cap.
source = source.replace('"column": "szse"', '"column": "sse"')
source = source.replace('"plate": "sz"', '"plate": "sh"')
source = source.replace(
    '("2022-01-01", "2022-12-31"),',
    '("2020-01-01", "2020-12-31"),\n        ("2021-01-01", "2021-12-31"),\n        ("2022-01-01", "2022-12-31"),'
)
source = source.replace('"pageSize": "100"', '"pageSize": "30"')
source = source.replace('if page * 100 >= total:', 'if page * 30 >= total:')
source = source.replace('(?:第一|第三)季度报告', '(?:第一|第三|一|三)季度报告')
source = source.replace('(第一|第三)季度报告', '(第一|第三|一|三)季度报告')
source = source.replace(
    'q = "Q1" if zh_quarter == "第一" else "Q3"',
    'q = "Q1" if zh_quarter in ("第一", "一") else "Q3"'
)

# Select only the six requested annual reports and the latest strict quarterly report.
choose_start = source.index('def choose_documents(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:')
choose_end = source.index('\ndef publication_date', choose_start)
choose_replacement = r'''def choose_documents(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    annual_excludes = (
        "摘要", "英文版", "取消", "关于", "提示性公告", "审计报告",
        "董事会审议", "监事会审议", "更正公告"
    )
    for year in EXPECTED_ANNUAL_YEARS:
        key = f"{year}年年度报告"
        candidates = [
            r for r in rows
            if is_pdf(r)
            and key in r["cleanTitle"]
            and not any(x in r["cleanTitle"] for x in annual_excludes)
        ]
        if not candidates:
            raise RuntimeError(f"Missing annual report candidate for {year}")
        candidates.sort(
            key=lambda r: (
                ann_time(r),
                "修订" in r["cleanTitle"] or "更正后" in r["cleanTitle"],
                int(r.get("adjunctSize") or 0),
            ),
            reverse=True,
        )
        chosen = dict(candidates[0])
        chosen["kind"] = "年度报告"
        chosen["report_year"] = year
        selected.append(chosen)
        print("SELECT_ANNUAL", year, chosen["cleanTitle"], chosen.get("adjunctUrl"), flush=True)

    quarter_excludes = (
        "提示性公告", "更正公告", "关于", "审阅报告", "英文版", "摘要"
    )
    quarters = [
        r for r in rows
        if is_pdf(r)
        and re.search(r"20\d{2}年(?:第一|第三|一|三)季度报告", r["cleanTitle"])
        and not any(x in r["cleanTitle"] for x in quarter_excludes)
    ]
    if not quarters:
        quarters = [
            r for r in rows
            if is_pdf(r)
            and "季度报告" in r["cleanTitle"]
            and not any(x in r["cleanTitle"] for x in quarter_excludes)
        ]
    if not quarters:
        raise RuntimeError("Missing quarterly report candidate")
    quarters.sort(
        key=lambda r: (
            ann_time(r),
            "全文" in r["cleanTitle"],
            "正文" not in r["cleanTitle"],
            int(r.get("adjunctSize") or 0),
        ),
        reverse=True,
    )
    quarter = dict(quarters[0])
    quarter["kind"] = "最新季报"
    selected.append(quarter)
    print("SELECT_QUARTER", quarter["cleanTitle"], quarter.get("adjunctUrl"), flush=True)
    return selected
'''
source = source[:choose_start] + choose_replacement + source[choose_end:]

# Remove prospectus-only validation inherited from the generic template.
source = source.replace(
    '    if sum(r["document_type"] == "招股说明书" for r in records) != 1:\n'
    '        raise RuntimeError("Expected exactly one final IPO prospectus")\n',
    ''
)

# Use Fujian Cement identity terms during PDF verification.
source = source.replace(
    'identity_terms = ("川宁", "301301", "yili chuanning", "chuanning")',
    'identity_terms = ("福建水泥", "600802", "fujian cement", "fjcement")'
)

# Replace package notes with the exact requested scope.
readme_start = source.index('    readme = f"""')
readme_end = source.index('    (ROOT / "00_文件清单与范围说明.txt").write_text', readme_start)
new_readme = r'''    readme = f"""{FULL_COMPANY}（证券简称：{COMPANY}；证券代码：{CODE}）官方披露文件包

资料截止日期：{AS_OF}

收录范围：
1. 2020—2025年度完整年度报告，共6份。
2. 截至资料截止日最新已披露、严格意义上的季度报告。A股2026年第三季度报告尚未披露，因此本包收录2026年第一季度报告。

排除范围：年度报告摘要、提示性公告、业绩预告、业绩快报、单独审计附件、英文版及重复旧版本。

来源：巨潮资讯网（法定信息披露平台）官方原始PDF。
校验：PDF文件头、实际页数、qpdf结构、首末页渲染、公司身份信息（可提取时）和ZIP完整性。
"""
'''
source = source[:readme_start] + new_readme + source[readme_end:]
source = source.replace(
    '"scope": "2022-2025全部年报、最终IPO招股说明书、截至当前最新严格季度报告"',
    '"scope": "2020-2025完整年度报告、截至当前最新严格季度报告"'
)

exec(compile(source, str(source_path), 'exec'), {'__name__': '__main__', '__file__': str(source_path)})
