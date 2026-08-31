from __future__ import annotations

from pathlib import Path

source = Path(".github/scripts/package_shenzhen_international_static_public_reports.py")
code = source.read_text(encoding="utf-8")
old = '''    for tag in list(root.find_all(True)):
        text = tag.get_text(" ", strip=True)
'''
new = '''    for tag in list(root.find_all(True)):
        if tag.attrs is None or tag.parent is None:
            continue
        text = tag.get_text(" ", strip=True)
'''
if old not in code:
    raise RuntimeError("HTML cleanup loop was not found")
code = code.replace(old, new, 1)
compiled = compile(code, str(source), "exec")
exec(compiled, {"__name__": "__main__"})
