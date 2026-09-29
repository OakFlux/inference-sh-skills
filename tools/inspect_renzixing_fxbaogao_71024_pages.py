from pathlib import Path
import json
import requests
from PIL import Image
from io import BytesIO

base = 'https://public.fxbaogao.com/report-image/2016/04/21/71024-{page}.png'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36',
    'Referer': 'https://www.fxbaogao.com/view?id=71024',
}
records = []
for page in range(1, 11):
    url = base.format(page=page)
    r = requests.get(url, headers=headers, timeout=120)
    rec = {'page': page, 'url': url, 'status': r.status_code, 'bytes': len(r.content), 'content_type': r.headers.get('content-type')}
    if r.status_code == 200 and len(r.content) > 10000:
        im = Image.open(BytesIO(r.content)); im.load()
        rec.update({'format': im.format, 'width': im.width, 'height': im.height, 'mode': im.mode})
    records.append(rec)
    print(json.dumps(rec, ensure_ascii=False), flush=True)
Path('renzixing_fxbaogao_71024_pages.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
