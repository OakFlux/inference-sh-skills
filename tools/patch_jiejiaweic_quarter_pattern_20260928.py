from pathlib import Path

path = Path("tools/package_jiejiaweic_filings_20260928.py")
text = path.read_text(encoding="utf-8")
old = '    pattern = re.compile(r"20\\d{2}年(?:第一|第三)季度报告")\n'
new = '    pattern = re.compile(r"20\\d{2}年第?[一三]季度报告")\n'
if old not in text:
    raise SystemExit("Quarter-report pattern anchor not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Patched quarterly-report title pattern in", path)
