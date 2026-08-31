from __future__ import annotations

from pathlib import Path

source = Path(".github/scripts/package_shenzhen_international_static_public_reports.py")
code = source.read_text(encoding="utf-8")

replacements = [
    (
        'response = session.get(url, timeout=(25, 180), allow_redirects=True)',
        'response = session.get(url, timeout=(15, 60), allow_redirects=True)',
    ),
    (
        '    for attempt in range(1, 5):',
        '    for attempt in range(1, 4):',
    ),
    (
        '        absolute = urljoin(source_url, src)\n        try:',
        '        absolute = urljoin(source_url, src)\n'
        '        if "public.fxbaogao.com/report-image/" not in absolute:\n'
        '            image.decompose()\n'
        '            continue\n'
        '        try:',
    ),
    (
        'timeout=(20, 120),',
        'timeout=(15, 45),',
    ),
    (
        '        ("风险提示", "風險提示", "风险因素", "風險因素"),\n',
        '',
    ),
]

for old, new in replacements:
    if old not in code:
        raise RuntimeError(f"Required patch token not found: {old!r}")
    code = code.replace(old, new, 1)

compiled = compile(code, str(source), "exec")
exec(compiled, {"__name__": "__main__"})
