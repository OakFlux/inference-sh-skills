from pathlib import Path

wrapper_path = Path('scripts/run_chuanning_filings_v2_20260928.py')
wrapper = wrapper_path.read_text(encoding='utf-8')
needle = "patched = source[:start] + replacement + source[end:]\nexec("
replacement = """patched = source[:start] + replacement + source[end:]
# CNINFO currently caps each response at 30 rows even when a larger pageSize is requested.
patched = patched.replace('\\\"pageSize\\\": \\\"100\\\"', '\\\"pageSize\\\": \\\"30\\\"')
patched = patched.replace('if page * 100 >= total:', 'if page * 30 >= total:')
# CNINFO uses both '第一季度报告' and the shorter '一季度报告' title forms.
patched = patched.replace('(?:第一|第三)季度报告', '(?:第一|第三|一|三)季度报告')
patched = patched.replace('(第一|第三)季度报告', '(第一|第三|一|三)季度报告')
patched = patched.replace('q = \\\"Q1\\\" if zh_quarter == \\\"第一\\\" else \\\"Q3\\\"', 'q = \\\"Q1\\\" if zh_quarter in (\\\"第一\\\", \\\"一\\\") else \\\"Q3\\\"')
exec("""
if needle not in wrapper:
    raise RuntimeError('Unable to locate v2 execution hook')
wrapper = wrapper.replace(needle, replacement, 1)
exec(compile(wrapper, str(wrapper_path), 'exec'), {'__name__': '__main__', '__file__': str(wrapper_path)})
