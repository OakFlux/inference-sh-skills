from pathlib import Path

source_path = Path("scripts/build_empyean_301269_filings_20260928.py")
source = source_path.read_text(encoding="utf-8")
source = source.replace(
    r"2026年(?:第一|第三)季度报告",
    r"2026年(?:第一|第三|一|三)季度报告",
)
namespace = {"__name__": "__main__", "__file__": str(source_path)}
exec(compile(source, str(source_path), "exec"), namespace)
