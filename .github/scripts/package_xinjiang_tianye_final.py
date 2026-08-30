from __future__ import annotations

import requests
import textwrap

SOURCE_URL = (
    "https://raw.githubusercontent.com/OakFlux/inference-sh-skills/"
    "e78cdf29c3a2721979d2ee1a81123fbf0a37dee3/"
    ".github/workflows/tmp-package-foxit-reports.yml"
)


def main() -> None:
    response = requests.get(SOURCE_URL, timeout=120)
    response.raise_for_status()
    workflow = response.text

    start_marker = "          python - <<'PY'\n"
    end_marker = "\n          PY\n"
    if start_marker not in workflow or end_marker not in workflow:
        raise RuntimeError("Unable to extract embedded packaging script")

    block = workflow.split(start_marker, 1)[1].split(end_marker, 1)[0]
    code = textwrap.dedent(block)

    replacements = [
        ("foxit_verified_package", "xinjiang_tianye_verified_package"),
        ('STOCK_ID = "688095"', 'STOCK_ID = "600075"'),
        (
            'COMPANY = "福建福昕软件开发股份有限公司"',
            'COMPANY = "新疆天业股份有限公司"',
        ),
        ('SHORT_NAME = "福昕软件"', 'SHORT_NAME = "新疆天业"'),
        ("福建福昕软件开发股份有限公司", "新疆天业股份有限公司"),
        ("福昕软件", "新疆天业"),
        ('"foxit"', '"xinjiangtianye"'),
        ("688095.SH", "600075.SH"),
    ]
    for old, new in replacements:
        code = code.replace(old, new)

    required = [
        'STOCK_ID = "600075"',
        'COMPANY = "新疆天业股份有限公司"',
        'SHORT_NAME = "新疆天业"',
        '"xinjiangtianye"',
        "新疆天业_2020-2025年报_2026年最新半年报_完整PDF.zip",
    ]
    missing = [token for token in required if token not in code]
    if missing:
        raise RuntimeError(f"Required transformations missing: {missing}")

    compiled = compile(code, "xinjiang_tianye_generated_packaging.py", "exec")
    exec(compiled, {"__name__": "__main__"})


if __name__ == "__main__":
    main()
