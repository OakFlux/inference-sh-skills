from __future__ import annotations

import requests

SOURCE_URL = (
    "https://raw.githubusercontent.com/OakFlux/inference-sh-skills/"
    "c0312b2866218be5adb67faffa5ea7ace46872db/"
    ".github/scripts/package_zhongchuangzhiling_reports.py"
)

response = requests.get(SOURCE_URL, timeout=180)
response.raise_for_status()
code = response.text
old = '        "取消",\n    )'
new = '        "取消",\n        "h股",\n    )'
if old not in code:
    raise RuntimeError("Unable to locate annual-report exclusion list")
code = code.replace(old, new, 1)
if '        "h股",' not in code:
    raise RuntimeError("H-share exclusion patch was not applied")
compiled = compile(code, "package_zhongchuangzhiling_reports_v2_generated.py", "exec")
exec(compiled, {"__name__": "__main__"})
