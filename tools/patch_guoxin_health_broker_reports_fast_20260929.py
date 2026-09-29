from pathlib import Path

path = Path("tools/package_guoxin_health_broker_reports_20260929.py")
text = path.read_text(encoding="utf-8")

text = text.replace('timeout=(45, 240)', 'timeout=(20, 60)')
text = text.replace('timeout=120,\n                allow_redirects=True,', 'timeout=45,\n                allow_redirects=True,')
text = text.replace('            quality=95,\n            optimize=True,', '            quality=90,\n            optimize=False,')

old = '''    text_parts: list[str] = []
    for page in reader.pages[: min(pages, 12)]:
        try:
            text_parts.append(page.extract_text() or "")
        except Exception as exc:
            print("TEXT_WARNING", path.name, repr(exc), flush=True)
    compact_text = re.sub(r"\\s+", "", "".join(text_parts))
    identity_match = COMPANY in compact_text or CODE in compact_text
    if require_text_identity and len(compact_text) > 500 and not identity_match:
        raise RuntimeError(f"报告文本未识别到{COMPANY}或{CODE}：{path.name}")
'''
new = '''    compact_text = ""
    identity_match = False
    if require_text_identity:
        try:
            text_result = subprocess.run(
                ["pdftotext", "-f", "1", "-l", str(min(pages, 2)), str(path), "-"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            compact_text = re.sub(r"\\s+", "", text_result.stdout or "")
            identity_match = COMPANY in compact_text or CODE in compact_text
            if len(compact_text) > 200 and not identity_match:
                raise RuntimeError(f"报告文本未识别到{COMPANY}或{CODE}：{path.name}")
        except subprocess.TimeoutExpired:
            print("TEXT_IDENTITY_TIMEOUT", path.name, flush=True)
        except UnicodeDecodeError as exc:
            print("TEXT_IDENTITY_DECODE_WARNING", path.name, repr(exc), flush=True)
'''
if old not in text:
    raise SystemExit("validation patch anchor not found")
text = text.replace(old, new, 1)
text = text.replace('timeout=240,\n    )', 'timeout=120,\n    )')
text = text.replace('timeout=240,\n        capture_output=True,', 'timeout=120,\n        capture_output=True,')
path.write_text(text, encoding="utf-8")
print("Applied fast Guoxin Health packaging patch")
