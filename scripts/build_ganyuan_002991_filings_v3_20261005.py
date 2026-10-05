from pathlib import Path

source_path = Path("scripts/build_ganyuan_002991_filings_v2_20261005.py")
source = source_path.read_text(encoding="utf-8")

old_pattern = 'pattern = re.compile(r"(20\\d{2})年(第一季度|第三季度)报告")'
new_pattern = 'pattern = re.compile(r"(20\\d{2})年(第一季度|第三季度|一季度|三季度)报告")'
old_quarter = 'quarter = 1 if match.group(2) == "第一季度" else 3'
new_quarter = 'quarter = 1 if match.group(2) in ("第一季度", "一季度") else 3'

if old_pattern not in source:
    raise RuntimeError("quarter-title pattern was not found in v2 packager")
if old_quarter not in source:
    raise RuntimeError("quarter mapping statement was not found in v2 packager")

source = source.replace(old_pattern, new_pattern, 1)
source = source.replace(old_quarter, new_quarter, 1)

# The validation function accepts both formal and abbreviated quarter wording.
old_validation = 'marker_ok = quarter_cn in text and "报告" in text if text else False'
new_validation = 'marker_ok = (quarter_cn in text or (quarter == 1 and "一季度" in text) or (quarter == 3 and "三季度" in text)) and "报告" in text if text else False'
if old_validation not in source:
    raise RuntimeError("quarter validation statement was not found in v2 packager")
source = source.replace(old_validation, new_validation, 1)

exec(compile(source, str(source_path), "exec"), {"__name__": "__main__"})
