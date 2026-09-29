from pathlib import Path

wrapper_path = Path('scripts/run_zhongxin_saike_filings_20260929.py')
wrapper = wrapper_path.read_text(encoding='utf-8')
needle = "\nexec(compile(source, str(source_path), 'exec'), {'__name__': '__main__', '__file__': str(source_path)})\n"
injection = """
source = source.replace(
    'identity_terms = (\"川宁\", \"301301\", \"yili chuanning\", \"chuanning\")',
    'identity_terms = (\"中新赛克\", \"002912\", \"sinovatio\", \"zhongxin saike\", \"saike\")'
)
exec(compile(source, str(source_path), 'exec'), {'__name__': '__main__', '__file__': str(source_path)})
"""
if needle not in wrapper:
    raise RuntimeError('Unable to locate final execution hook')
wrapper = wrapper.replace(needle, '\n' + injection, 1)
exec(compile(wrapper, str(wrapper_path), 'exec'), {'__name__': '__main__', '__file__': str(wrapper_path)})
