from __future__ import annotations

from pathlib import Path


def main() -> None:
    source_path = Path(".github/scripts/package_galaxy_microelectronics_final.py")
    code = source_path.read_text(encoding="utf-8")

    old = '''        ("if years != [2024, 2025]:", "if years != list(range(2020, 2026)):") ,
'''
    new = '''        ("if years != [2024, 2025]:", "if years != list(range(2020, 2026)):") ,
        ("if annual_years != [2024, 2025]:", "if annual_years != list(range(2020, 2026)):") ,
'''
    if old not in code:
        raise RuntimeError("Annual coverage transformation anchor was not found")
    code = code.replace(old, new, 1)

    compiled = compile(code, "package_galaxy_microelectronics_v2_generated.py", "exec")
    exec(compiled, {"__name__": "__main__"})


if __name__ == "__main__":
    main()
