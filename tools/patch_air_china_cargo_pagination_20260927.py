from pathlib import Path

path = Path("tools/package_air_china_cargo_filings_20260927.py")
text = path.read_text(encoding="utf-8")
old = "    page_size = 50\n"
new = "    page_size = 30\n"
if old not in text:
    raise SystemExit("Pagination patch anchor not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Patched CNINFO page size in", path)
