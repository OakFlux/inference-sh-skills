from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

PACKAGE = '华新建材_600801_06655_1993-2025年报_招股及上市文件_2026最新定期报告'
root = Path(PACKAGE)
annual_dir = root / '01_年度报告'
equity_dir = root / '02_招股及上市文件'
latest_dir = root / '03_最新定期报告'
notes_dir = root / '04_档案说明'
work = Path('_huaxin_work')
render_dir = work / 'renders'
for d in (annual_dir, equity_dir, latest_dir, notes_dir, render_dir):
    d.mkdir(parents=True, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36',
    'Accept': 'application/pdf,text/html,application/xhtml+xml,application/octet-stream;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}
s = requests.Session()
s.trust_env = False

def candidates(url: str) -> list[str]:
    vals = [url]
    if 'www1.hkexnews.hk' in url:
        vals.append(url.replace('www1.hkexnews.hk', 'www.hkexnews.hk'))
    elif 'www.hkexnews.hk' in url:
        vals.append(url.replace('www.hkexnews.hk', 'www1.hkexnews.hk'))
    return list(dict.fromkeys(vals))

def request(url: str, *, stream: bool = False, timeout=(25, 240)) -> requests.Response:
    errors = []
    for u in candidates(url):
        for attempt in range(1, 6):
            try:
                h = dict(HEADERS)
                h['Referer'] = 'https://www1.hkexnews.hk/' if 'hkexnews.hk' in u else 'https://www.cninfo.com.cn/'
                r = s.get(u, headers=h, timeout=timeout, allow_redirects=True, stream=stream)
                print('GET', u, 'attempt', attempt, 'status', r.status_code, 'type', r.headers.get('content-type'), 'len', r.headers.get('content-length'), 'final', r.url, flush=True)
                r.raise_for_status()
                return r
            except Exception as exc:
                errors.append(f'{u} attempt {attempt}: {exc!r}')
                time.sleep(min(2 * attempt, 8))
    raise RuntimeError(f'failed request {url}: {errors[-8:]}')

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def download_pdf(urls: list[str] | str, dest: Path, min_bytes: int = 20_000) -> str:
    if isinstance(urls, str):
        urls = [urls]
    errors = []
    for url in urls:
        tmp = dest.with_suffix(dest.suffix + '.part')
        tmp.unlink(missing_ok=True)
        try:
            r = request(url, stream=True)
            try:
                with tmp.open('wb') as fh:
                    for chunk in r.iter_content(1024 * 1024):
                        if chunk:
                            fh.write(chunk)
                final_url = str(r.url)
            finally:
                r.close()
            size = tmp.stat().st_size
            head = tmp.read_bytes()[:8]
            if size < min_bytes or not head.startswith(b'%PDF-'):
                raise RuntimeError(f'not a valid PDF: size={size}, head={head!r}')
            tmp.replace(dest)
            return final_url
        except Exception as exc:
            errors.append(f'{url}: {exc!r}')
            tmp.unlink(missing_ok=True)
    raise RuntimeError(f'PDF download failed for {dest.name}: {errors}')

def fetch_html(url: str, dest: Path) -> tuple[str, str]:
    r = request(url, stream=False, timeout=(20, 120))
    try:
        raw = r.content
        final_url = str(r.url)
        encoding = r.apparent_encoding or r.encoding or 'utf-8'
    finally:
        r.close()
    if len(raw) < 1_000:
        raise RuntimeError(f'HTML too small for {dest.name}: {len(raw)} bytes')
    dest.write_bytes(raw)
    try:
        text = raw.decode(encoding, errors='replace')
    except LookupError:
        text = raw.decode('utf-8', errors='replace')
    return final_url, text

pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
styles = getSampleStyleSheet()
title_style = ParagraphStyle('TitleCN', parent=styles['Title'], fontName='STSong-Light', fontSize=16, leading=23, alignment=TA_CENTER, spaceAfter=12)
body_style = ParagraphStyle('BodyCN', parent=styles['BodyText'], fontName='STSong-Light', fontSize=8.5, leading=12, spaceAfter=3, wordWrap='CJK')
meta_style = ParagraphStyle('MetaCN', parent=body_style, fontSize=7.5, leading=10, textColor='#444444', spaceAfter=10)

def html_text_to_pdf(source_html: str, title: str, source_url: str, dest: Path) -> int:
    soup = BeautifulSoup(source_html, 'html.parser')
    for node in soup(['script', 'style', 'noscript']):
        node.decompose()
    for br in soup.find_all('br'):
        br.replace_with('\n')
    text = soup.get_text('\n')
    lines = []
    for line in text.splitlines():
        line = re.sub(r'\s+', ' ', line).strip()
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    if len(''.join(lines)) < 300:
        raise RuntimeError(f'extracted HTML text too short for {title}')
    doc = SimpleDocTemplate(str(dest), pagesize=A4, rightMargin=15*mm, leftMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm, title=title, author='华新建材集团股份有限公司（官方披露HTML转换）')
    story = [Paragraph(html.escape(title), title_style), Paragraph(html.escape('原始来源：' + source_url), meta_style), Spacer(1, 4*mm)]
    for line in lines:
        safe = html.escape(line)
        story.append(Paragraph(safe, body_style))
    doc.build(story)
    return len(lines)

def page_count(path: Path) -> int:
    return len(PdfReader(str(path), strict=False).pages)

def validate_pdf(path: Path, min_pages: int = 1) -> dict:
    if not path.exists() or path.stat().st_size < 10_000 or not path.read_bytes()[:8].startswith(b'%PDF-'):
        raise RuntimeError(f'invalid final PDF: {path}')
    q = subprocess.run(['qpdf', '--check', str(path)], capture_output=True, text=True)
    if q.returncode not in (0, 3):
        raise RuntimeError(f'qpdf failed for {path.name}: {q.stderr[-1500:]}')
    pages = page_count(path)
    if pages < min_pages:
        raise RuntimeError(f'page count too small for {path.name}: {pages}')
    check_pages = [1] + ([pages] if pages > 1 else [])
    for page in check_pages:
        prefix = render_dir / f'{hashlib.sha1(str(path).encode()).hexdigest()}_{page}'
        run = subprocess.run(['pdftoppm', '-f', str(page), '-l', str(page), '-r', '72', '-png', '-singlefile', str(path), str(prefix)], capture_output=True, text=True, timeout=180)
        png = Path(str(prefix) + '.png')
        if run.returncode != 0 or not png.exists() or png.stat().st_size < 800 or not png.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
            raise RuntimeError(f'render failed for {path.name} page {page}: {run.stderr[-1000:]}')
        png.unlink()
    identity_ok = False
    try:
        reader = PdfReader(str(path), strict=False)
        sample_pages = list(reader.pages[:min(6, pages)])
        if pages > 6:
            sample_pages.append(reader.pages[-1])
        sample = '\n'.join((p.extract_text() or '') for p in sample_pages)
        identity_ok = any(x.lower() in sample.lower() for x in ('华新', 'huaxin', '600801', '06655', '900933'))
    except Exception as exc:
        print('TEXT_CHECK_WARNING', path.name, repr(exc), flush=True)
    return {'pages': pages, 'bytes': path.stat().st_size, 'sha256': sha256(path), 'qpdf_return_code': q.returncode, 'render_verified_first_and_last_page': True, 'identity_text_verified_when_extractable': identity_ok}

records = []
raw_records = []
seen_hashes = set()

def add_pdf(path: Path, *, title: str, doc_type: str, fiscal_year: int | None, publication_date: str, source: str, source_url: str, source_form: str, notes: str = '', min_pages: int = 1):
    data = validate_pdf(path, min_pages=min_pages)
    if data['sha256'] in seen_hashes:
        raise RuntimeError(f'duplicate PDF detected: {path.name}')
    seen_hashes.add(data['sha256'])
    rec = {
        'relative_path': str(path.relative_to(root)), 'filename': path.name, 'title': title,
        'document_type': doc_type, 'fiscal_year': fiscal_year, 'publication_date': publication_date,
        'source': source, 'source_url': source_url, 'source_form': source_form, 'notes': notes,
        **data,
    }
    records.append(rec)
    print('VALIDATED', json.dumps(rec, ensure_ascii=False), flush=True)

annuals = [
    (2001,'2002-03-15','https://static.cninfo.com.cn/finalpage/2002-03-15/553155.PDF','2001_华新水泥_年度报告.pdf',''),
    (2002,'2003-03-11','https://static.cninfo.com.cn/finalpage/2003-03-11/10217616.PDF','2002_华新水泥_年度报告.pdf',''),
    (2003,'2004-03-19','https://static.cninfo.com.cn/finalpage/2004-03-19/13796576.PDF','2003_华新水泥_年度报告.pdf',''),
    (2004,'2005-03-24','https://static.cninfo.com.cn/finalpage/2005-03-24/15133863.PDF','2004_华新水泥_年度报告.pdf',''),
    (2005,'2006-03-07','https://static.cninfo.com.cn/finalpage/2006-03-07/16535948.PDF','2005_华新水泥_年度报告.pdf',''),
    (2006,'2007-03-17','https://static.cninfo.com.cn/finalpage/2007-03-17/21568195.PDF','2006_华新水泥_年度报告.pdf',''),
    (2007,'2008-03-19','https://static.cninfo.com.cn/finalpage/2008-03-19/38082020.PDF','2007_华新水泥_年度报告.pdf',''),
    (2008,'2009-03-11','https://static.cninfo.com.cn/finalpage/2009-03-11/50037544.PDF','2008_华新水泥_年度报告.pdf',''),
    (2009,'2010-03-31','https://static.cninfo.com.cn/finalpage/2010-03-31/57754459.PDF','2009_华新水泥_年度报告.pdf',''),
    (2010,'2011-03-31','https://static.cninfo.com.cn/finalpage/2011-03-31/59206805.PDF','2010_华新水泥_年度报告.pdf',''),
    (2011,'2012-04-20','https://static.cninfo.com.cn/finalpage/2012-04-20/60864764.PDF','2011_华新水泥_年度报告_修订版.pdf','采用后续披露的修订版'),
    (2012,'2013-03-26','https://static.cninfo.com.cn/finalpage/2013-03-26/62271105.PDF','2012_华新水泥_年度报告.pdf',''),
    (2013,'2014-03-29','https://static.cninfo.com.cn/finalpage/2014-03-29/63752775.PDF','2013_华新水泥_年度报告.pdf',''),
    (2014,'2015-03-27','https://static.cninfo.com.cn/finalpage/2015-03-27/1200750046.PDF','2014_华新水泥_年度报告.pdf',''),
    (2015,'2016-03-31','https://static.cninfo.com.cn/finalpage/2016-03-31/1202113147.PDF','2015_华新水泥_年度报告.pdf',''),
    (2016,'2017-03-24','https://static.cninfo.com.cn/finalpage/2017-03-24/1203190337.PDF','2016_华新水泥_年度报告.pdf',''),
    (2017,'2018-05-15','https://static.cninfo.com.cn/finalpage/2018-05-15/1204941629.PDF','2017_华新水泥_年度报告_修订版.pdf','采用后续披露的修订版'),
    (2018,'2019-03-30','https://static.cninfo.com.cn/finalpage/2019-03-30/1205964627.PDF','2018_华新水泥_年度报告.pdf',''),
    (2019,'2020-04-29','https://static.cninfo.com.cn/finalpage/2020-04-29/1207668512.PDF','2019_华新水泥_年度报告.pdf',''),
    (2020,'2021-03-30','https://static.cninfo.com.cn/finalpage/2021-03-30/1209472843.PDF','2020_华新水泥_年度报告_更正版.pdf','采用后续披露的更正版'),
    (2021,'2022-03-30','https://static.cninfo.com.cn/finalpage/2022-03-30/1212729802.PDF','2021_华新水泥_年度报告.pdf',''),
    (2022,'2023-03-29','https://static.cninfo.com.cn/finalpage/2023-03-29/1216246923.PDF','2022_华新水泥_年度报告.pdf',''),
    (2023,'2024-03-29','https://static.cninfo.com.cn/finalpage/2024-03-29/1219448741.PDF','2023_华新水泥_年度报告.pdf',''),
    (2024,'2025-03-27','https://static.cninfo.com.cn/finalpage/2025-03-27/1222912425.PDF','2024_华新水泥_年度报告.pdf',''),
    (2025,'2026-03-27','https://static.cninfo.com.cn/finalpage/2026-03-27/1225038214.PDF','2025_华新建材_年度报告.pdf','公司已完成名称变更'),
]
for year, pubdate, url, filename, note in annuals:
    dest = annual_dir / filename
    final_url = download_pdf(url, dest, min_bytes=80_000)
    add_pdf(dest, title=f'华新建材（原华新水泥）{year}年年度报告', doc_type='年度报告', fiscal_year=year, publication_date=pubdate, source='巨潮资讯网（法定信息披露平台）', source_url=final_url, source_form='官方PDF原件', notes=note, min_pages=10)

html_docs = [
    ('1993_华新水泥_年度报告摘要_官方原始网页.html','1993_华新水泥_年度报告摘要_可读版.pdf','华新水泥1993年年度报告摘要','年度报告摘要',1993,'1994-05-12','https://static.cninfo.com.cn/finalpage/1994-05-12/11368154.html',annual_dir,'官方公开电子档案仅检索到摘要，未检索到完整年报电子版'),
    ('1993_华新水泥_A股招股说明书概要_官方原始网页.html','1993_华新水泥_A股招股说明书概要_可读版.pdf','华新水泥股份有限公司招股说明书概要','招股说明书概要',None,'1993-11-03','https://static.cninfo.com.cn/finalpage/1993-11-03/158103.html',equity_dir,'官方公开电子档案提供招股说明书概要'),
    ('1993_华新水泥_A股股票上市公告书_官方原始网页.html','1993_华新水泥_A股股票上市公告书_可读版.pdf','华新水泥股份有限公司股票上市公告书','股票上市公告书',None,'1993-12-16','https://static.cninfo.com.cn/finalpage/1993-12-16/148870.html',equity_dir,'A股上市配套文件'),
]
for html_name, pdf_name, title, dtype, year, pubdate, url, outdir, note in html_docs:
    raw_path = outdir / html_name
    final_url, text = fetch_html(url, raw_path)
    raw_records.append({'relative_path': str(raw_path.relative_to(root)), 'filename': raw_path.name, 'title': title, 'document_type': dtype, 'publication_date': pubdate, 'source': '巨潮资讯网（法定信息披露平台）', 'source_url': final_url, 'bytes': raw_path.stat().st_size, 'sha256': sha256(raw_path), 'notes': '官方原始HTML网页'})
    pdf_path = outdir / pdf_name
    line_count = html_text_to_pdf(text, title, final_url, pdf_path)
    add_pdf(pdf_path, title=title, doc_type=dtype, fiscal_year=year, publication_date=pubdate, source='巨潮资讯网（法定信息披露平台）', source_url=final_url, source_form='官方HTML原件的文本排版转换PDF；原始HTML同时保留', notes=f'{note}；转换文本行数{line_count}', min_pages=1)

h_listing = equity_dir / '2022_华新水泥_H股以介绍方式上市_上市文件_港交所中文版.pdf'
h_url = download_pdf([
    'https://www1.hkexnews.hk/listedco/listconews/sehk/2022/0322/2022032200020_c.pdf',
    'https://static.cninfo.com.cn/finalpage/2022-03-23/1212644241.PDF',
], h_listing, min_bytes=200_000)
add_pdf(h_listing, title='华新水泥境外上市外资股以介绍方式在香港联合交易所主板上市之上市文件', doc_type='H股上市文件（介绍方式）', fiscal_year=None, publication_date='2022-03-22', source='香港交易所披露易；巨潮资讯备用镜像', source_url=h_url, source_form='官方PDF原件', notes='本次为原B股转换上市地并以介绍方式上市，并非新股发行招股', min_pages=20)

q1 = latest_dir / '2026_华新建材_第一季度报告.pdf'
q1_url = download_pdf('https://static.cninfo.com.cn/finalpage/2026-04-30/1225257077.PDF', q1, min_bytes=30_000)
add_pdf(q1, title='华新建材2026年第一季度报告', doc_type='第一季度报告', fiscal_year=2026, publication_date='2026-04-30', source='巨潮资讯网（法定信息披露平台）', source_url=q1_url, source_form='官方PDF原件', notes='截至2026年9月22日的最新季度报告', min_pages=3)

interim = latest_dir / '2026_华新建材_半年度报告_补充.pdf'
interim_url = download_pdf('https://static.cninfo.com.cn/finalpage/2026-08-29/1225529676.PDF', interim, min_bytes=80_000)
add_pdf(interim, title='华新建材2026年半年度报告', doc_type='半年度报告', fiscal_year=2026, publication_date='2026-08-29', source='巨潮资讯网（法定信息披露平台）', source_url=interim_url, source_form='官方PDF原件', notes='披露时间晚于2026年第一季度报告，作为最新财务信息补充收录', min_pages=10)

gap_text = '''华新建材（原华新水泥）历史电子档案缺口说明

核对日期：2026年9月22日

1. 本包收录2001—2025各会计年度完整年度报告，共25份；2011、2017和2020年度采用后续披露的修订版或更正版。
2. 对1993年度，巨潮资讯官方公开电子档案仅提供《1993年年度报告摘要》HTML，未检索到完整年度报告电子版；本包保留官方原始HTML并制作可读版PDF。
3. 对1994—2000年度，已按600801及原B股900933，分别检索巨潮资讯、上海证券交易所年度报告分类和全量历史公告索引，未发现可公开下载的完整年度报告电子文件。因而本包未使用来源不明或无法核验的网络文件冒充官方原件。
4. 股权发行与上市文件方面，官方公开电子档案可获得1993年A股《招股说明书概要》和《股票上市公告书》；未检索到1994年B股原始招股说明书的官方公开电子文件。
5. 2022年H股文件属于原B股转换上市地后“以介绍方式上市”的上市文件，不涉及新股发行，本包按招股及上市文件类别收录。
6. 截至核对日，最新“季度报告”为2026年第一季度报告；2026年半年度报告披露日期更晚，本包同时作为补充收录。
'''
(notes_dir / '历史电子档案缺口与收录口径说明.txt').write_text(gap_text, encoding='utf-8')

summary = {
    'package_name': PACKAGE,
    'issuer_current_name': '华新建材集团股份有限公司',
    'former_name': '华新水泥股份有限公司',
    'securities': {'A_share': '600801', 'former_B_share': '900933', 'H_share': '06655'},
    'checked_as_of': '2026-09-22',
    'coverage': {
        'complete_annual_reports': '2001-2025（25个会计年度）',
        '1993': '仅官方年度报告摘要HTML及其可读版PDF',
        '1994-2000': '官方公开电子档案未检索到完整年度报告文件',
        'equity_documents': '1993年A股招股说明书概要、A股股票上市公告书、2022年H股介绍上市文件',
        'latest_quarterly': '2026年第一季度报告',
        'supplemental_latest_periodic': '2026年半年度报告',
    },
    'pdf_count': len(records),
    'raw_html_count': len(raw_records),
    'pdf_records': records,
    'raw_html_records': raw_records,
}
(root / 'manifest.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

with (root / '文件清单.csv').open('w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['相对路径','文件类型','会计年度','披露日期','页数','字节数','SHA-256','来源','来源网址','备注'])
    for r in records:
        w.writerow([r['relative_path'],r['document_type'],r['fiscal_year'] or '',r['publication_date'],r['pages'],r['bytes'],r['sha256'],r['source'],r['source_url'],r['notes']])
    for r in raw_records:
        w.writerow([r['relative_path'],r['document_type'],'',r['publication_date'],'',r['bytes'],r['sha256'],r['source'],r['source_url'],r['notes']])

readme = f'''华新建材（原华新水泥）官方披露文件包

证券代码：A股600801；原B股900933；H股06655
核对日期：2026年9月22日

收录概况
- 完整年度报告：2001—2025，共25份，每年度一份；存在修订/更正时采用最终版本。
- 1993年度：官方公开电子档案仅有年度报告摘要，保留原始HTML并附可读版PDF。
- 1994—2000年度：在巨潮资讯、上海证券交易所及A/B股历史公告索引中未检索到可公开下载的完整年报电子文件，详见“04_档案说明”。
- 招股及上市文件：1993年A股招股说明书概要、A股股票上市公告书、2022年H股介绍上市文件。
- 最新季度报告：2026年第一季度报告；另附披露时间更晚的2026年半年度报告。

文件校验
- PDF文件数：{len(records)}
- 官方原始HTML文件数：{len(raw_records)}
- 每份PDF均完成文件头、页数、qpdf结构检查及首末页渲染检查。
- manifest.json记录文件元数据、来源、页数、大小及SHA-256。
- SHA256SUMS.txt用于完整性核验。

说明
本包仅收录能够核验来源的官方披露文件。HTML转PDF仅用于提高可读性，官方原始HTML同时保留，转换版不会替代原始文件。
'''
(root / '00_文件清单与范围说明.txt').write_text(readme, encoding='utf-8')

sums = []
for p in sorted(root.rglob('*')):
    if p.is_file() and p.name != 'SHA256SUMS.txt':
        sums.append(f'{sha256(p)}  {p.relative_to(root)}')
(root / 'SHA256SUMS.txt').write_text('\n'.join(sums) + '\n', encoding='utf-8')

zip_path = Path(PACKAGE + '.zip')
with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as z:
    for p in sorted(root.rglob('*')):
        if p.is_file():
            z.write(p, arcname=str(Path(PACKAGE) / p.relative_to(root)))
with zipfile.ZipFile(zip_path, 'r') as z:
    bad = z.testzip()
    if bad:
        raise RuntimeError(f'ZIP CRC failure: {bad}')
print('FINAL_ZIP', zip_path, zip_path.stat().st_size, sha256(zip_path), flush=True)
print('PDF_COUNT', len(records), 'RAW_HTML_COUNT', len(raw_records), flush=True)
