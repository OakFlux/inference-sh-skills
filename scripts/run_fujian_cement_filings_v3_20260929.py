from pathlib import Path

wrapper_path = Path('scripts/run_fujian_cement_filings_20260929.py')
wrapper = wrapper_path.read_text(encoding='utf-8')

old_missing = (
    '        if not candidates:\n'
    '            raise RuntimeError(f"Missing annual report candidate for {year}")'
)
new_missing = '\n'.join([
    '        if not candidates and year == 2024:',
    '            candidates = [{',
    '                "cleanTitle": "福建水泥股份有限公司2024年年度报告",',
    '                "announcementTitle": "福建水泥股份有限公司2024年年度报告",',
    '                "adjunctUrl": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-04-22/600802_20250422_4JIU.pdf",',
    '                "adjunctSize": 1500,',
    '                "announcementTime": 1745251200000,',
    '                "announcementId": "SSE_600802_20250422_4JIU",',
    '            }]',
    '            print("SSE_FALLBACK_ANNUAL", year, candidates[0]["adjunctUrl"], flush=True)',
    '        if not candidates:',
    '            raise RuntimeError(f"Missing annual report candidate for {year}")',
])
if old_missing not in wrapper:
    raise RuntimeError('Unable to locate annual-report missing-candidate branch')
wrapper = wrapper.replace(old_missing, new_missing, 1)

hook = "\nexec(compile(source, str(source_path), 'exec'), {'__name__': '__main__', '__file__': str(source_path)})\n"
addon = """
source = source.replace(
    '\"source\": \"巨潮资讯网（深圳证券交易所法定信息披露平台）\",',
    '\"source\": (\"上海证券交易所\" if \"sse.com.cn\" in source_url else \"巨潮资讯网（法定信息披露平台）\"),'
)
source = source.replace(
    '来源：巨潮资讯网（法定信息披露平台）官方原始PDF。',
    '来源：巨潮资讯网及上海证券交易所官方原始PDF；2024年度完整年报采用上交所官方文件。'
)
exec(compile(source, str(source_path), 'exec'), {'__name__': '__main__', '__file__': str(source_path)})
"""
if hook not in wrapper:
    raise RuntimeError('Unable to locate final execution hook')
wrapper = wrapper.replace(hook, '\n' + addon, 1)
exec(compile(wrapper, str(wrapper_path), 'exec'), {'__name__': '__main__', '__file__': str(wrapper_path)})
