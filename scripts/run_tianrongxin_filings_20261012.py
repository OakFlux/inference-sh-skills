from pathlib import Path

base_path = Path("scripts/build_chuanning_filings_20260928.py")
source = base_path.read_text(encoding="utf-8")

replacements = {
    'CODE = "301301"': 'CODE = "002212"',
    'COMPANY = "川宁生物"': 'COMPANY = "天融信"',
    'FULL_COMPANY = "伊犁川宁生物技术股份有限公司"': 'FULL_COMPANY = "天融信科技集团股份有限公司"',
    'AS_OF = "2026-09-28"': 'AS_OF = "2026-10-12"',
    'LISTING_YEAR = 2022': 'LISTING_YEAR = 2008',
    'EXPECTED_ANNUAL_YEARS = [2022, 2023, 2024, 2025]': 'EXPECTED_ANNUAL_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]',
    'VERIFY_DIR = Path("_verify_chuanning")': 'VERIFY_DIR = Path("_verify_tianrongxin")',
    'ZIP_NAME = f"{COMPANY}_{CODE}_2022-2025全部年报_招股说明书_2026最新季报.zip"': 'ZIP_NAME = f"{COMPANY}_{CODE}_2020-2025年报_最新季报_截至20261012.zip"',
    'identity_terms = ("川宁", "301301", "yili chuanning", "chuanning")': 'identity_terms = ("天融信", "002212", "南洋股份", "topsec")',
}
for old, new in replacements.items():
    if old not in source:
        raise RuntimeError(f"Expected source fragment not found: {old}")
    source = source.replace(old, new, 1)

# Use the official CNINFO Shenzhen stock map to resolve the current issuer orgId.
resolver_start = source.index("def find_org_id() -> str:")
resolver_end = source.index("\ndef query_announcements(org_id: str)", resolver_start)
resolver = r'''def find_org_id() -> str:
    for warm_url in ("https://www.cninfo.com.cn/new/disclosure", "https://www.cninfo.com.cn/"):
        try:
            response = SESSION.get(warm_url, timeout=(20, 60))
            print("WARM", response.status_code, response.url, len(response.content), flush=True)
        except Exception as exc:
            print("WARM_FAILED", warm_url, repr(exc), flush=True)

    response = request_with_retry(
        "GET",
        "https://www.cninfo.com.cn/new/data/szse_stock.json",
        headers={
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://www.cninfo.com.cn/new/disclosure",
        },
    )
    data = response.json()
    stock_list = data.get("stockList") if isinstance(data, dict) else data
    for item in stock_list or []:
        code = str(item.get("code") or "")
        name = str(item.get("zwjc") or item.get("name") or "")
        org_id = str(item.get("orgId") or item.get("orgid") or "")
        if org_id and (code == CODE or COMPANY in name):
            print("ORG_ID_FROM_MAP", org_id, item, flush=True)
            return org_id
    raise RuntimeError(f"Unable to resolve CNINFO orgId for {CODE}")
'''
source = source[:resolver_start] + resolver + source[resolver_end:]

# Query every calendar year in the requested range plus the current year.
query_start = source.index("def query_announcements(org_id: str)")
windows_start = source.index("    windows = [", query_start)
windows_end = source.index("    ]", windows_start) + len("    ]")
windows = '''    windows = [
        ("2020-01-01", "2020-12-31"),
        ("2021-01-01", "2021-12-31"),
        ("2022-01-01", "2022-12-31"),
        ("2023-01-01", "2023-12-31"),
        ("2024-01-01", "2024-12-31"),
        ("2025-01-01", "2025-12-31"),
        ("2026-01-01", AS_OF),
    ]'''
source = source[:windows_start] + windows + source[windows_end:]
source = source.replace('"pageSize": "100"', '"pageSize": "30"')
source = source.replace("if page * 100 >= total:", "if page * 30 >= total:")
source = source.replace("if page > 20:", "if page > 60:")

# Select only the requested annual reports and the latest strict quarterly report.
choose_start = source.index("def choose_documents(rows: list[dict[str, Any]])")
choose_end = source.index("\ndef publication_date", choose_start)
choose_function = r'''def choose_documents(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    annual_excludes = (
        "摘要", "英文版", "取消", "提示性公告", "更正公告",
        "补充公告", "审计报告", "问询函", "回复",
    )

    def replacement_score(title: str) -> int:
        return 100 if any(
            marker in title
            for marker in ("更正后", "更新后", "修订后", "修订版", "修订稿", "更新版")
        ) else 0

    for year in EXPECTED_ANNUAL_YEARS:
        key = f"{year}年年度报告"
        candidates = [
            row for row in rows
            if is_pdf(row)
            and key in row["cleanTitle"]
            and not any(excluded in row["cleanTitle"] for excluded in annual_excludes)
        ]
        if not candidates:
            raise RuntimeError(f"Missing annual report candidate for {year}")
        candidates.sort(
            key=lambda row: (replacement_score(row["cleanTitle"]), ann_time(row)),
            reverse=True,
        )
        chosen = dict(candidates[0])
        chosen["kind"] = "年度报告"
        chosen["report_year"] = year
        selected.append(chosen)
        print("SELECT_ANNUAL", year, chosen["cleanTitle"], chosen.get("adjunctUrl"), flush=True)

    quarter_excludes = ("提示性公告", "更正公告", "补充公告", "关于", "审阅报告", "英文版")
    quarter_pattern = re.compile(r"20\d{2}年(?:第一|第三|一|三)季度报告")
    quarters = [
        row for row in rows
        if is_pdf(row)
        and quarter_pattern.search(row["cleanTitle"])
        and not any(excluded in row["cleanTitle"] for excluded in quarter_excludes)
    ]
    if not quarters:
        raise RuntimeError("Missing quarterly report candidate")
    quarters.sort(key=lambda row: (ann_time(row), replacement_score(row["cleanTitle"])), reverse=True)
    latest = dict(quarters[0])
    latest["kind"] = "最新季报"
    selected.append(latest)
    print("SELECT_QUARTER", latest["cleanTitle"], latest.get("adjunctUrl"), flush=True)
    return selected
'''
source = source[:choose_start] + choose_function + source[choose_end:]

# Prefer the date embedded in the official CNINFO file path.
pub_start = source.index("def publication_date(row: dict[str, Any])")
pub_end = source.index("\ndef destination_for", pub_start)
pub_function = r'''def publication_date(row: dict[str, Any]) -> str:
    adjunct = str(row.get("adjunctUrl") or "")
    match = re.search(r"finalpage/(20\d{2}-\d{2}-\d{2})/", adjunct)
    if match:
        return match.group(1)
    value = ann_time(row)
    if value <= 0:
        return ""
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
'''
source = source[:pub_start] + pub_function + source[pub_end:]

# Support both long and short quarterly-report title forms.
source = source.replace("(20\\d{2})年(第一|第三)季度报告", "(20\\d{2})年(第一|第三|一|三)季度报告")
source = source.replace(
    'q = "Q1" if zh_quarter == "第一" else "Q3"',
    'q = "Q1" if zh_quarter in ("第一", "一") else "Q3"',
)

# The package intentionally excludes the issuer's old IPO prospectus.
source = source.replace(
    '    if sum(r["document_type"] == "招股说明书" for r in records) != 1:\n'
    '        raise RuntimeError("Expected exactly one final IPO prospectus")\n',
    '',
)
source = source.replace(
    '1. 公司上市后全部完整年度报告：2022、2023、2024、2025年度。',
    '1. 2020—2025年度完整年度报告；如存在修订、更正或更新版本，优先保留后续版本。',
)
source = source.replace(
    '2. 首次公开发行股票并在创业板上市的最终完整招股说明书。\n',
    '',
)
source = source.replace(
    '3. 截至资料截止日最新已披露、严格意义上的季度报告。A股2026年第三季度报告尚未到法定披露期，因此本包收录2026年第一季度报告。',
    '2. 截至资料截止日最新已披露、严格意义上的季度报告。',
)
source = source.replace(
    '"scope": "2022-2025全部年报、最终IPO招股说明书、截至当前最新严格季度报告"',
    '"scope": "2020-2025年度报告及截至当前最新严格季度报告"',
)

exec(compile(source, str(base_path), "exec"), {"__name__": "__main__", "__file__": str(base_path)})
