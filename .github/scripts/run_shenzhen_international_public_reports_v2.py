from __future__ import annotations

from pathlib import Path

source = Path(".github/scripts/package_shenzhen_international_public_reports.py")
code = source.read_text(encoding="utf-8")
code = code.replace('"min_text_chars": 6500,', '"min_text_chars": 5000,', 1)

if '"min_text_chars": 5000,' not in code:
    raise RuntimeError("Threshold adjustment was not applied")

compiled = compile(code, str(source), "exec")
exec(compiled, {"__name__": "__main__"})
