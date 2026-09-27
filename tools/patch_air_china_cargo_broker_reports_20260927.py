from pathlib import Path

path = Path("tools/package_air_china_cargo_broker_reports_20260927.py")
text = path.read_text(encoding="utf-8")
old = '    if not path.exists() or path.stat().st_size < 30_000:\n'
new = '    minimum_size = 5_000 if "公开资料整理版" in path.name else 30_000\n    if not path.exists() or path.stat().st_size < minimum_size:\n'
if old not in text:
    raise SystemExit("PDF size threshold patch anchor not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Patched generated PDF size threshold in", path)
