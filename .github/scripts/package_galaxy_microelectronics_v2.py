from __future__ import annotations

from pathlib import Path


def main() -> None:
    source_path = Path(".github/scripts/package_galaxy_microelectronics_final.py")
    code = source_path.read_text(encoding="utf-8")

    old = '''        ("if years != [2024, 2025]:", "if years != list(range(2020, 2026)):") ,
'''
    new = '''        ("if years != [2024, 2025]:", "if years != list(range(2020, 2026)):") ,
        ("if [item[\\"year\\"] for item in documents if item[\\"category\\"] == \\"Annual Report\\"] != [2024, 2025]:", "if [item[\\"year\\"] for item in documents if item[\\"category\\"] == \\"Annual Report\\"] != list(range(2020, 2026)):") ,
        ("3. 招股说明书采用2024年9月23日披露的正式发行版，排除招股意向书、申报稿、注册稿和问询回复。", "3. 招股说明书采用2021年1月19日披露的正式发行版，排除招股意向书、申报稿、注册稿和问询回复。") ,
        ("4. 最新半年报为2026年8月20日披露、覆盖截至2026年6月30日止六个月的完整报告。", "4. 最新半年报为2026年8月10日披露、覆盖截至2026年6月30日止六个月的完整报告。") ,
        ("整理日期：2026-08-29", "整理日期：2026-08-30") ,
'''
    if old not in code:
        raise RuntimeError("Annual coverage transformation anchor was not found")
    code = code.replace(old, new, 1)

    compiled = compile(code, "package_galaxy_microelectronics_v2_generated.py", "exec")
    exec(compiled, {"__name__": "__main__"})


if __name__ == "__main__":
    main()
