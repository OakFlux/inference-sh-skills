from pathlib import Path

path = Path("tools/package_air_china_cargo_filings_20260927.py")
text = path.read_text(encoding="utf-8")

replacements = [
    ("    page_size = 50\n", "    page_size = 30\n", "pagination"),
    (
        '        if re.search(r"20\\d{2}年(?:第一|第三)季度报告", title) and is_full_report_title(title):\n',
        '        if re.search(r"20\\d{2}年(?:第一|第三|一|三)季度报告", title) and is_full_report_title(title):\n',
        "quarter candidate title variants",
    ),
    (
        '    quarter_label_match = re.search(r"(第一|第三)季度报告", quarter_title)\n',
        '    quarter_label_match = re.search(r"(第一|第三|一|三)季度报告", quarter_title)\n',
        "quarter label variants",
    ),
]

for old, new, label in replacements:
    if old not in text:
        raise SystemExit(f"Patch anchor not found: {label}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("Patched CNINFO pagination and quarter-title variants in", path)
