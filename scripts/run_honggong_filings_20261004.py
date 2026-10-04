from pathlib import Path

template_path = Path("scripts/run_puruisi_filings_20261004.py")
template = template_path.read_text(encoding="utf-8")

# Reuse the validated CNINFO packaging workflow and specialize it for Honggong Technology.
for old, new in (
    ("301257", "301662"),
    ("普蕊斯（上海）医药科技开发股份有限公司", "宏工科技股份有限公司"),
    ("普蕊斯", "宏工科技"),
    ("Puruisi", "Honggong"),
    ("Puris", "Honggong"),
):
    template = template.replace(old, new)

needle = "}\nfor old, new in replacements.items():"
extra = '''    'LISTING_YEAR = 2022': 'LISTING_YEAR = 2025',
    'EXPECTED_ANNUAL_YEARS = [2022, 2023, 2024, 2025]': 'EXPECTED_ANNUAL_YEARS = [2024, 2025]',
    'VERIFY_DIR = Path("_verify_chuanning")': 'VERIFY_DIR = Path("_verify_honggong")',
    'ZIP_NAME = f"{COMPANY}_{CODE}_2022-2025全部年报_招股说明书_2026最新季报.zip"': 'ZIP_NAME = f"{COMPANY}_{CODE}_2024-2025全部年报_招股说明书_2026最新季报.zip"',
    '1. 公司上市后全部完整年度报告：2022、2023、2024、2025年度。': '1. 公司上市后全部完整年度报告：2024、2025年度。',
    '3. 截至资料截止日最新已披露、严格意义上的季度报告。A股2026年第三季度报告尚未到法定披露期，因此本包收录2026年第一季度报告。': '3. 截至资料截止日最新已披露、严格意义上的季度报告。2026年第三季度报告截至2026年10月4日尚未披露，因此本包收录2026年第一季度报告；2026年半年度报告不属于季度报告。',
    '"scope": "2022-2025全部年报、最终IPO招股说明书、截至当前最新严格季度报告"': '"scope": "2024-2025全部年报、最终IPO招股说明书、截至当前最新严格季度报告"',
}\nfor old, new in replacements.items():'''
if needle not in template:
    raise RuntimeError("Unable to locate replacement dictionary in template")
template = template.replace(needle, extra, 1)

exec(compile(template, str(template_path), "exec"), {"__name__": "__main__", "__file__": str(template_path)})
