from pathlib import Path

source_path = Path('scripts/build_superhi_filings_20260927.py')
source = source_path.read_text(encoding='utf-8')
old = 'rows = hkex_links("20230320", "20230415")'
new = 'rows = hkex_links("20230320", "20230531")'
if old not in source:
    raise RuntimeError('Expected 2022 annual-report search window was not found')
source = source.replace(old, new, 1)
exec(compile(source, str(source_path), 'exec'), {'__name__': '__main__', '__file__': str(source_path)})
