from pathlib import Path

path = Path('tools/package_changying_broker_reports_20260928.py')
text = path.read_text(encoding='utf-8')
start = text.index('CANDIDATES = [')
end = text.index('\n\nHEADERS =', start)
new_block = '''CANDIDATES = [
    {
        "priority": 1,
        "title_contains": "引擎切换，新动能助推进入快车道",
        "institution_expected": "信达证券",
        "min_pages": 15,
    },
    {
        "priority": 2,
        "title_contains": "全品类布局，增发加码新能源与5G",
        "institution_expected": "民生证券",
        "min_pages": 12,
    },
    {
        "priority": 3,
        "title_contains": "金属巨头焕发新春，多产品布局弹性大",
        "institution_expected": "民生证券",
        "min_pages": 12,
    },
    {
        "priority": 4,
        "title_contains": "深化新能源和元宇宙产业布局，构筑新增长极",
        "institution_expected": "中航证券",
        "min_pages": 8,
    },
    {
        "priority": 5,
        "title_contains": "精密制造全球龙头，全面拥抱新兴产业",
        "institution_expected": "华鑫证券",
        "min_pages": 8,
    },
    {
        "priority": 6,
        "title_contains": "消费电子、新能源双轮驱动",
        "institution_expected": "华鑫证券",
        "min_pages": 5,
    },
    {
        "priority": 7,
        "title_contains": "新能源汽车，机器人积极布局",
        "institution_expected": "中邮证券",
        "min_pages": 4,
    },
]'''
path.write_text(text[:start] + new_block + text[end:], encoding='utf-8')
print('Patched Changying Precision report candidates')
