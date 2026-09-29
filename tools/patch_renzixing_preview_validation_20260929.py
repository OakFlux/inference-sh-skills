from pathlib import Path

path = Path('tools/package_renzixing_broker_reports_20260929.py')
text = path.read_text(encoding='utf-8')

old_block = '''    first_stem = PREVIEW_DIR / f"{path.stem}_page1"
    subprocess.run(
        ["pdftoppm", "-f", "1", "-singlefile", "-png", "-r", "150", str(path), str(first_stem)],
        check=True,
        capture_output=True,
        timeout=180,
    )
    first_png = first_stem.with_suffix(".png")
    if not first_png.exists() or first_png.stat().st_size < 8_000:
        raise RuntimeError(f"首页渲染失败：{path.name}")

    last_stem = PREVIEW_DIR / f"{path.stem}_page{pages}"
    subprocess.run(
        ["pdftoppm", "-f", str(pages), "-l", str(pages), "-singlefile", "-png", "-r", "120", str(path), str(last_stem)],
        check=True,
        capture_output=True,
        timeout=180,
    )
    last_png = last_stem.with_suffix(".png")
    if not last_png.exists() or last_png.stat().st_size < 6_000:
        raise RuntimeError(f"末页渲染失败：{path.name}")
'''

new_block = '''    preview_id = sha256(path)[:12]
    first_stem = PREVIEW_DIR / f"{preview_id}_page1"
    first_render = subprocess.run(
        ["pdftocairo", "-f", "1", "-l", "1", "-singlefile", "-png", "-r", "150", str(path), str(first_stem)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    first_png = Path(str(first_stem) + ".png")
    if first_render.returncode != 0 or not first_png.exists() or first_png.stat().st_size < 1_000:
        print("FIRST_RENDER_DEBUG", first_render.returncode, first_render.stdout, first_render.stderr, sorted(str(p) for p in PREVIEW_DIR.glob("*")), flush=True)
        raise RuntimeError(f"首页渲染失败：{path.name}")
    with Image.open(first_png) as preview_image:
        preview_image.load()
        if preview_image.width < 500 or preview_image.height < 700:
            raise RuntimeError(f"首页渲染尺寸异常：{path.name}: {preview_image.size}")

    last_stem = PREVIEW_DIR / f"{preview_id}_page{pages}"
    last_render = subprocess.run(
        ["pdftocairo", "-f", str(pages), "-l", str(pages), "-singlefile", "-png", "-r", "120", str(path), str(last_stem)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    last_png = Path(str(last_stem) + ".png")
    if last_render.returncode != 0 or not last_png.exists() or last_png.stat().st_size < 1_000:
        print("LAST_RENDER_DEBUG", last_render.returncode, last_render.stdout, last_render.stderr, sorted(str(p) for p in PREVIEW_DIR.glob("*")), flush=True)
        raise RuntimeError(f"末页渲染失败：{path.name}")
    with Image.open(last_png) as preview_image:
        preview_image.load()
        if preview_image.width < 500 or preview_image.height < 700:
            raise RuntimeError(f"末页渲染尺寸异常：{path.name}: {preview_image.size}")
'''

if old_block not in text:
    raise SystemExit('preview rendering block not found')
path.write_text(text.replace(old_block, new_block, 1), encoding='utf-8')
print('Patched Renzixing preview rendering with pdftocairo')
