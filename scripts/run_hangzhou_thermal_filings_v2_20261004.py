from pathlib import Path

source_path = Path('scripts/build_hangzhou_thermal_filings_20261004.py')
source = source_path.read_text(encoding='utf-8')
source = source.replace('ORG_ID = "gssh0605011"', 'ORG_ID = "9900039850"', 1)
exec(compile(source, str(source_path), 'exec'), {'__name__': '__main__', '__file__': str(source_path)})
