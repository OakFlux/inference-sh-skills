from pathlib import Path

source_path = Path("scripts/build_baicheng_301096_filings_20261006.py")
source = source_path.read_text(encoding="utf-8")

replacements = {
    'CHECKED_AS_OF = "2026-10-06"': 'CHECKED_AS_OF = "2026-10-12"',
    'COMPANY = "杭州百诚医药科技股份有限公司"': 'COMPANY = "浙江向日葵大健康科技股份有限公司"',
    'SHORT_NAME = "百诚医药"': 'SHORT_NAME = "向日葵"',
    'STOCK_CODE = "301096"': 'STOCK_CODE = "300111"',
    'PACKAGE = "百诚医药_301096_2020-2025年报_2026最新季报及半年报"': 'PACKAGE = "向日葵_300111_2020-2025年报_2026最新季报及半年报"',
    'WORK_DIR = Path("_baicheng_301096_filings_work")': 'WORK_DIR = Path("_xiangrikui_300111_filings_work")',
}

for old, new in replacements.items():
    if old not in source:
        raise RuntimeError(f"expected source text not found: {old}")
    source = source.replace(old, new, 1)

exec(compile(source, str(source_path), "exec"), {"__name__": "__main__"})
