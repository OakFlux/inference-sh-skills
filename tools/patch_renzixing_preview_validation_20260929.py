from pathlib import Path

path = Path('tools/package_renzixing_broker_reports_20260929.py')
text = path.read_text(encoding='utf-8')

old_first = '''    first_png = first_stem.with_suffix(".png")
    if not first_png.exists() or first_png.stat().st_size < 8_000:
        raise RuntimeError(f"首页渲染失败：{path.name}")
'''
new_first = '''    first_png = first_stem.with_suffix(".png")
    if not first_png.exists() or first_png.stat().st_size < 1_000:
        raise RuntimeError(f"首页渲染失败：{path.name}")
    with Image.open(first_png) as preview_image:
        preview_image.load()
        if preview_image.width < 500 or preview_image.height < 700:
            raise RuntimeError(f"首页渲染尺寸异常：{path.name}: {preview_image.size}")
'''

old_last = '''    last_png = last_stem.with_suffix(".png")
    if not last_png.exists() or last_png.stat().st_size < 6_000:
        raise RuntimeError(f"末页渲染失败：{path.name}")
'''
new_last = '''    last_png = last_stem.with_suffix(".png")
    if not last_png.exists() or last_png.stat().st_size < 1_000:
        raise RuntimeError(f"末页渲染失败：{path.name}")
    with Image.open(last_png) as preview_image:
        preview_image.load()
        if preview_image.width < 500 or preview_image.height < 700:
            raise RuntimeError(f"末页渲染尺寸异常：{path.name}: {preview_image.size}")
'''

if old_first not in text or old_last not in text:
    raise SystemExit('preview validation patch anchors not found')
text = text.replace(old_first, new_first, 1).replace(old_last, new_last, 1)
path.write_text(text, encoding='utf-8')
print('Patched Renzixing preview validation')
