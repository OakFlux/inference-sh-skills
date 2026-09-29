from pathlib import Path

wrapper_path = Path('scripts/run_chuanning_filings_v2_20260928.py')
wrapper = wrapper_path.read_text(encoding='utf-8')
needle = "patched = source[:start] + replacement + source[end:]\nexec("

injection = r'''patched = source[:start] + replacement + source[end:]

patched = patched.replace('CODE = "301301"', 'CODE = "002912"')
patched = patched.replace('COMPANY = "川宁生物"', 'COMPANY = "中新赛克"')
patched = patched.replace(
    'FULL_COMPANY = "伊犁川宁生物技术股份有限公司"',
    'FULL_COMPANY = "深圳市中新赛克科技股份有限公司"'
)
patched = patched.replace('AS_OF = "2026-09-28"', 'AS_OF = "2026-09-29"')
patched = patched.replace(
    'EXPECTED_ANNUAL_YEARS = [2022, 2023, 2024, 2025]',
    'EXPECTED_ANNUAL_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]'
)
patched = patched.replace(
    'ZIP_NAME = f"{COMPANY}_{CODE}_2022-2025全部年报_招股说明书_2026最新季报.zip"',
    'ZIP_NAME = f"{COMPANY}_{CODE}_2020-2025年报_2026最新季报.zip"'
)
patched = patched.replace(
    '("2022-01-01", "2022-12-31"),',
    '("2020-01-01", "2020-12-31"),\n        ("2021-01-01", "2021-12-31"),\n        ("2022-01-01", "2022-12-31"),'
)
patched = patched.replace('"pageSize": "100"', '"pageSize": "30"')
patched = patched.replace('if page * 100 >= total:', 'if page * 30 >= total:')
patched = patched.replace('(?:第一|第三)季度报告', '(?:第一|第三|一|三)季度报告')
patched = patched.replace('(第一|第三)季度报告', '(第一|第三|一|三)季度报告')
patched = patched.replace(
    'q = "Q1" if zh_quarter == "第一" else "Q3"',
    'q = "Q1" if zh_quarter in ("第一", "一") else "Q3"'
)

choose_start = patched.index('def choose_documents(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:')
choose_end = patched.index('\ndef publication_date', choose_start)
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
        candidates.sort(key=ann_time, reverse=True)
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
    quarters.sort(key=ann_time, reverse=True)
    quarter = dict(quarters[0])
    quarter["kind"] = "最新季报"
    selected.append(quarter)
    print("SELECT_QUARTER", quarter["cleanTitle"], quarter.get("adjunctUrl"), flush=True)
    return selected
'''
patched = patched[:choose_start] + choose_replacement + patched[choose_end:]
patched = patched.replace(
    '    if sum(r["document_type"] == "招股说明书" for r in records) != 1:\n'
    '        raise RuntimeError("Expected exactly one final IPO prospectus")\n',
    ''
)
readme_start = patched.index('    readme = f"""')
readme_end = patched.index('    (ROOT / "00_文件清单与范围说明.txt").write_text', readme_start)
new_readme = r'''    readme = f"""{FULL_COMPANY}（证券简称：{COMPANY}；证券代码：{CODE}）官方披露文件包

资料截止日期：{AS_OF}

收录范围：
1. 2020—2025年度完整年度报告，共6份。
2. 截至资料截止日最新已披露、严格意义上的季度报告。A股2026年第三季度报告尚未披露，因此本包收录2026年第一季度报告。

排除范围：年度报告摘要、提示性公告、业绩预告、业绩快报、单独审计附件、英文版及重复旧版本。

来源：巨潮资讯网（深圳证券交易所法定信息披露平台）官方原始PDF。
校验：PDF文件头、实际页数、qpdf结构、首末页渲染、公司身份信息（可提取时）和ZIP完整性。
"""
'''
patched = patched[:readme_start] + new_readme + patched[readme_end:]
patched = patched.replace(
    '"scope": "2022-2025全部年报、最终IPO招股说明书、截至当前最新严格季度报告"',
    '"scope": "2020-2025完整年度报告、截至当前最新严格季度报告"'
)

exec('''

if needle not in wrapper:
    raise RuntimeError('Unable to locate the generic packager execution hook')
wrapper = wrapper.replace(needle, injection, 1)
exec(compile(wrapper, str(wrapper_path), 'exec'), {'__name__': '__main__', '__file__': str(wrapper_path)})
