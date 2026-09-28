from pathlib import Path

source_path = Path('scripts/build_chuanning_broker_reports_20260928.py')
source = source_path.read_text(encoding='utf-8')
source = source.replace('"org": "中泰证券"', '"org": "东莞证券"', 1)
source = source.replace(
    '"title_keyword": "抗生素龙头再添合成生物双翼"',
    '"title_keyword": "合成生物学助力公司维持抗生素行业领先地位"',
    1,
)
source = source.replace('"preferred_date": "2025-12-28"', '"preferred_date": "2023-04-18"', 1)
source = source.replace(
    '"label": "中泰证券_公司深度报告_抗生素龙头再添合成生物双翼_成长值得期待"',
    '"label": "东莞证券_深度报告_合成生物学助力公司维持抗生素行业领先地位"',
    1,
)
exec(compile(source, str(source_path), 'exec'), {'__name__': '__main__', '__file__': str(source_path)})
