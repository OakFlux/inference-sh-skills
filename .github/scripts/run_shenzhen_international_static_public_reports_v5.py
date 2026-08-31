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
        '''    for tag in list(root.find_all(True)):
        text = tag.get_text(" ", strip=True)
''',
        '''    for tag in list(root.find_all(True)):
        if tag.attrs is None or tag.parent is None:
            continue
        text = tag.get_text(" ", strip=True)
''',
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
    (
        '''    cleaned_html, source_text, embedded_images = clean_container(container, final_url)
    source_chars = len(compact(source_text))
''',
        '''    cleaned_html, source_text, embedded_images = clean_container(container, final_url)
    # Use the complete public-reading text as the canonical delivery body.  The
    # source's deeply nested site HTML can collapse during print rendering, so
    # rebuild it as plain, searchable paragraphs without losing report text.
    ignored_lines = {
        "点击免费查看完整报告", "我的下载", "登录", "注册", "收藏", "分享",
        "你可能感兴趣", "相关推荐", "热门报告", "报告封面",
    }
    public_lines = []
    for raw_line in source_text.splitlines():
        line = re.sub(r"\\s+", " ", raw_line).strip()
        if not line or line in ignored_lines:
            continue
        if line.startswith("发现报告") or line.startswith("免责声明：本网站"):
            continue
        public_lines.append(line)
    cleaned_html = "".join(
        f"<p>{html_lib.escape(line)}</p>" for line in public_lines
    )
    embedded_images = []
    source_chars = len(compact(source_text))
''',
    ),
]

for old, new in replacements:
    if old not in code:
        raise RuntimeError(f"Required patch token not found: {old!r}")
    code = code.replace(old, new, 1)

compiled = compile(code, str(source), "exec")
exec(compiled, {"__name__": "__main__"})
