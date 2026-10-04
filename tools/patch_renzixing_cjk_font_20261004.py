from pathlib import Path

path = Path("tools/package_renzixing_broker_reports_20261004.py")
text = path.read_text(encoding="utf-8")

import_anchor = "from reportlab.pdfbase.cidfonts import UnicodeCIDFont\n"
replacement_import = import_anchor + "from reportlab.pdfbase.ttfonts import TTFont\n"
if "from reportlab.pdfbase.ttfonts import TTFont" not in text:
    if import_anchor not in text:
        raise SystemExit("ReportLab font import anchor not found")
    text = text.replace(import_anchor, replacement_import, 1)

old_register = '    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))\n'
new_register = '''    if "ARPLSung" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(
            TTFont("ARPLSung", "/usr/share/fonts/truetype/arphic-gbsn00lp/gbsn00lp.ttf")
        )
'''
if old_register not in text:
    raise SystemExit("CID font registration anchor not found")
text = text.replace(old_register, new_register, 1)
text = text.replace('"STSong-Light"', '"ARPLSung"')

path.write_text(text, encoding="utf-8")
print("Patched Ren Zixing PDFs to embed AR PL Simplified Chinese font")
