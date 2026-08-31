from __future__ import annotations

import requests

SOURCE_URL = (
    "https://raw.githubusercontent.com/OakFlux/inference-sh-skills/"
    "3b83f75be82e0b46e8b1c29a2e4edfeef37b648d/"
    ".github/scripts/package_actions_technology_final.py"
)

STOCK_ID = "688103"
COMPANY = "昆山国力电子科技股份有限公司"
SHORT_NAME = "国力电子"
FORMER_SHORT_NAME = "国力股份"
TICKER = "688103.SH"
PROSPECTUS_DATE = "2021-09-06"
PROSPECTUS_DETAIL_ID = 7525689
LATEST_HALF_ARCHIVE_DATE = "2026-08-27"


def main() -> None:
    response = requests.get(SOURCE_URL, timeout=120)
    response.raise_for_status()
    code = response.text

    replacements = [
        ("actions_technology_verified_package", "guoli_electronics_verified_package"),
        ('STOCK_ID = "688049"', f'STOCK_ID = "{STOCK_ID}"'),
        ('COMPANY = "炬芯科技股份有限公司"', f'COMPANY = "{COMPANY}"'),
        ('SHORT_NAME = "炬芯科技"', f'SHORT_NAME = "{SHORT_NAME}"'),
        ('TICKER = "688049.SH"', f'TICKER = "{TICKER}"'),
        ('PROSPECTUS_DATE = "2021-11-24"', f'PROSPECTUS_DATE = "{PROSPECTUS_DATE}"'),
        (
            "PROSPECTUS_DETAIL_ID = 7675376",
            f"PROSPECTUS_DETAIL_ID = {PROSPECTUS_DETAIL_ID}",
        ),
        (
            'LATEST_HALF_DATE = "2026-08-25"',
            f'LATEST_HALF_DATE = "{LATEST_HALF_ARCHIVE_DATE}"',
        ),
        ("炬芯科技股份有限公司", COMPANY),
        ("炬芯科技", SHORT_NAME),
        ('"actions"', '"glvac"'),
        ("2021年11月29日", "2021年9月10日"),
        ("2021年11月24日", "2021年9月6日"),
        ("2026年8月25日", "2026年8月27日"),
        ("2021/2021-11/", "2021/2021-9/"),
        ('"prepared_date": "2026-08-30"', '"prepared_date": "2026-08-31"'),
        ('"整理日期：2026-08-30"', '"整理日期：2026-08-31"'),
    ]
    for old, new in replacements:
        code = code.replace(old, new)

    loop_marker = '''    for old, new in replacements:\n        code = code.replace(old, new)\n\n    original_inspection ='''
    loop_replacement = f'''    for old, new in replacements:\n        code = code.replace(old, new)\n\n    # 2021—2024年公告使用旧证券简称“国力股份”，2025年起使用“国力电子”。\n    code = code.replace(\n        'TITLE_COMPANY_MARKERS = ("{SHORT_NAME}", "{COMPANY}")',\n        'TITLE_COMPANY_MARKERS = ("{SHORT_NAME}", "{FORMER_SHORT_NAME}", "{COMPANY}")',\n    )\n\n    original_inspection ='''
    if loop_marker not in code:
        raise RuntimeError("Unable to inject former short-name handling")
    code = code.replace(loop_marker, loop_replacement, 1)

    required = [
        f'STOCK_ID = "{STOCK_ID}"',
        f'COMPANY = "{COMPANY}"',
        f'SHORT_NAME = "{SHORT_NAME}"',
        f'PROSPECTUS_DATE = "{PROSPECTUS_DATE}"',
        f'PROSPECTUS_DETAIL_ID = {PROSPECTUS_DETAIL_ID}',
        f'LATEST_HALF_DATE = "{LATEST_HALF_ARCHIVE_DATE}"',
        "2021/2021-9/",
        f'TITLE_COMPANY_MARKERS = ("{SHORT_NAME}", "{FORMER_SHORT_NAME}", "{COMPANY}")',
        "国力电子_全部年报_招股说明书_2026年最新半年报_完整PDF.zip",
    ]
    missing = [token for token in required if token not in code]
    if missing:
        raise RuntimeError(f"Required transformations missing: {missing}")

    compiled = compile(code, "guoli_electronics_generated_packaging.py", "exec")
    exec(compiled, {"__name__": "__main__"})


if __name__ == "__main__":
    main()
