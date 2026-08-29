from __future__ import annotations

import requests
import textwrap

SOURCE_URL = (
    "https://raw.githubusercontent.com/OakFlux/inference-sh-skills/"
    "e78cdf29c3a2721979d2ee1a81123fbf0a37dee3/"
    ".github/workflows/tmp-package-foxit-reports.yml"
)


def main() -> None:
    response = requests.get(SOURCE_URL, timeout=120)
    response.raise_for_status()
    workflow = response.text

    start_marker = "          python - <<'PY'\n"
    end_marker = "\n          PY\n"
    if start_marker not in workflow or end_marker not in workflow:
        raise RuntimeError("Unable to extract embedded packaging script")

    block = workflow.split(start_marker, 1)[1].split(end_marker, 1)[0]
    code = textwrap.dedent(block)

    replacements = [
        ("foxit_verified_package", "qiule_verified_package"),
        ('STOCK_ID = "688095"', 'STOCK_ID = "920087"'),
        (
            'COMPANY = "福建福昕软件开发股份有限公司"',
            'COMPANY = "河南秋乐种业科技股份有限公司"',
        ),
        ('SHORT_NAME = "福昕软件"', 'SHORT_NAME = "秋乐种业"'),
        ("福建福昕软件开发股份有限公司", "河南秋乐种业科技股份有限公司"),
        ("福昕软件", "秋乐种业"),
        ('"foxit"', '"qiule"'),
        ("688095.SH", "920087.BJ"),
        ('f"{STOCK_ID}.SH"', 'f"{STOCK_ID}.BJ"'),
        ("static.sse.com.cn", "static.bse.cn"),
        ("01_年度报告_2020-2025", "01_年度报告_2014-2025"),
        ("2020—2025", "2014—2025"),
        ("range(2020, 2026)", "range(2014, 2026)"),
        ("共6份完整年度报告", "共12份完整年度报告"),
        ("len(documents) != 7", "len(documents) != 13"),
        ("Expected 7 documents", "Expected 13 documents"),
        ("list(range(2020, 2026))", "list(range(2014, 2026))"),
        ("len(pdfs) != 7", "len(pdfs) != 13"),
        ("Expected 7 PDFs", "Expected 13 PDFs"),
        (
            'minimum_pages = {"annual": 100, "half": 60}[kind]',
            'minimum_pages = {"annual": 40, "half": 60}[kind]',
        ),
        (
            "秋乐种业_2020-2025年报_2026年最新半年报_完整PDF.zip",
            "秋乐种业_全部年报_2026年最新半年报_完整PDF.zip",
        ),
    ]
    for old, new in replacements:
        code = code.replace(old, new)

    original_extract = "    raw_url, detail_url, context = extract_pdf_from_detail(record)"
    replacement_extract = """    if year == 2014:
        raw_url = \"https://www.neeq.com.cn/disclosure/2015/2015-04-23/1429788302_905419.pdf\"
        detail_url = \"https://www.neeq.com.cn/disclosure/announcement.html?companyCode=831087\"
        context = \"全国股转系统官方附件：秋乐种业2014年年度报告，披露日期2015-04-23\"
    else:
        raw_url, detail_url, context = extract_pdf_from_detail(record)"""
    if original_extract not in code:
        raise RuntimeError("Annual extraction line was not found")
    code = code.replace(original_extract, replacement_extract, 1)

    original_download = (
        "    used_url = download_pdf(download_candidates(raw_url), target, detail_url)"
    )
    replacement_download = """    if year == 2014:
        legacy_path = \"/disclosure/2015/2015-04-23/1429788302_905419.pdf\"
        annual_candidates = [
            \"https://www.neeq.com.cn\" + legacy_path,
            \"https://static.neeq.com.cn\" + legacy_path,
            \"https://www.bse.cn\" + legacy_path,
            \"https://static.bse.cn\" + legacy_path,
            \"http://www.neeq.com.cn\" + legacy_path,
        ]
    else:
        annual_candidates = download_candidates(raw_url)
    used_url = download_pdf(annual_candidates, target, detail_url)"""
    if original_download not in code:
        raise RuntimeError("Annual download line was not found")
    code = code.replace(original_download, replacement_download, 1)

    required = [
        'STOCK_ID = "920087"',
        'COMPANY = "河南秋乐种业科技股份有限公司"',
        'SHORT_NAME = "秋乐种业"',
        "range(2014, 2026)",
        "list(range(2014, 2026))",
        "1429788302_905419.pdf",
        "秋乐种业_全部年报_2026年最新半年报_完整PDF.zip",
    ]
    missing = [token for token in required if token not in code]
    if missing:
        raise RuntimeError(f"Required transformations missing: {missing}")

    compile(code, "qiule_generated_packaging.py", "exec")
    exec(compile(code, "qiule_generated_packaging.py", "exec"), {"__name__": "__main__"})


if __name__ == "__main__":
    main()
