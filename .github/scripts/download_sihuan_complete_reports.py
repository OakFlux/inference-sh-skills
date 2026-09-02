from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from pypdf import PdfReader

OUT = Path('/tmp/sihuan_complete_reports')
OUT.mkdir(parents=True, exist_ok=True)

UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36'
)
S = requests.Session()
S.headers.update({
    'User-Agent': UA,
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Referer': 'https://data.eastmoney.com/report/stock.jshtml',
})

TARGETS = [
    {
        'key': '太平洋证券_2026',
        'begin': '2026-08-25', 'end': '2026-08-31',
        'patterns': ['医美和创新药双轮驱动', '业绩逐步进入兑现期'],
        'fallback_org': ['太平洋'],
    },
    {
        'key': '国泰海通证券_2026',
        'begin': '2026-05-27', 'end': '2026-06-03',
        'patterns': ['平台型医美新星', '盈利有望释放'],
        'fallback_org': ['国泰海通', '海通'],
    },
    {
        'key': '华福证券_2025',
        'begin': '2025-06-05', 'end': '2025-06-12',
        'patterns': ['跨越制药边界', '成就美与创新'],
        'fallback_org': ['华福'],
    },
    {
        'key': '西南证券_2025',
        'begin': '2025-04-18', 'end': '2025-04-26',
        'patterns': ['有心栽花', '美不胜收'],
        'fallback_org': ['西南'],
    },
    {
        'key': '德邦证券_2023',
        'begin': '2023-07-02', 'end': '2023-07-10',
        'patterns': ['始于乐提葆', '医美平台化'],
        'fallback_org': ['德邦'],
    },
]


def norm(value: Any) -> str:
    return re.sub(r'[\s\u3000:：,，。·—_\-（）()【】\[\]“”"\'‘’]+', '', str(value or '')).lower()


def safe_name(value: str, max_len: int = 90) -> str:
    value = re.sub(r'[\\/:*?"<>|\r\n]+', '_', value).strip(' ._')
    return value[:max_len] or 'report'


def fetch_window(begin: str, end: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    total_pages = 1
    while page <= total_pages and page <= 60:
        params = {
            'industryCode': '*', 'pageSize': 100, 'industry': '*',
            'rating': '*', 'ratingChange': '*',
            'beginTime': begin, 'endTime': end, 'pageNo': page,
            'fields': '', 'qType': 0, 'orgCode': '', 'rcode': '',
            '_': int(time.time() * 1000),
        }
        response = S.get('https://reportapi.eastmoney.com/report/list', params=params, timeout=(20, 180))
        print('API', begin, end, 'page', page, 'status', response.status_code, 'bytes', len(response.content), flush=True)
        response.raise_for_status()
        payload = response.json()
        data = payload.get('data') or payload.get('Data') or []
        if not isinstance(data, list):
            data = []
        rows.extend(x for x in data if isinstance(x, dict))
        total_pages = int(payload.get('TotalPage') or payload.get('totalPage') or 1)
        print('  rows', len(data), 'total_pages', total_pages, 'hits', payload.get('hits'), flush=True)
        if not data:
            break
        page += 1
    return rows


def candidate_matches(row: dict[str, Any], target: dict[str, Any]) -> tuple[bool, str]:
    title = norm(row.get('title'))
    blob = norm(json.dumps(row, ensure_ascii=False))
    patterns = [norm(x) for x in target['patterns']]
    title_hit = any(p and p in title for p in patterns)
    company_hit = any(x in blob for x in ('四环医药', '四環醫藥', '00460', '0460hk', '460hk'))
    org_blob = norm(' '.join(str(row.get(k) or '') for k in ('orgSName', 'orgName')))
    org_hit = any(norm(x) in org_blob for x in target['fallback_org'])
    if title_hit:
        return True, 'title'
    if company_hit and org_hit:
        return True, 'company+org'
    return False, ''


def pdf_urls(row: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    info = str(row.get('infoCode') or row.get('infocode') or '').strip()
    for key in ('encodeUrl', 'pdfUrl', 'url', 'attachUrl', 'fileUrl'):
        value = row.get(key)
        if isinstance(value, str) and value:
            value = html.unescape(value).replace('\\/', '/')
            if value.startswith('//'):
                value = 'https:' + value
            elif value.startswith('/'):
                value = urljoin('https://data.eastmoney.com', value)
            if value.startswith('http'):
                urls.append(value)
    if info:
        for prefix in ('H3', 'H2', 'H1', 'H4'):
            base = f'https://pdf.dfcfw.com/pdf/{prefix}_{info}_1.pdf'
            urls.extend([base, base + '?download=1'])
        detail_urls = [
            f'https://data.eastmoney.com/report/zw_stock.jshtml?infocode={info}',
            f'https://data.eastmoney.com/report/zw_industry.jshtml?infocode={info}',
        ]
        for detail in detail_urls:
            try:
                r = S.get(detail, timeout=(20, 120))
                print('DETAIL', detail, r.status_code, len(r.content), flush=True)
                text = html.unescape(r.text).replace('\\/', '/')
                for found in re.findall(r'https?://[^\"\'<>\s]+?\.pdf(?:\?[^\"\'<>\s]*)?', text, re.I):
                    urls.append(found.rstrip('),;]}'))
                for found in re.findall(r'//pdf\.dfcfw\.com/[^\"\'<>\s]+', text, re.I):
                    urls.append('https:' + found.rstrip('),;]}'))
            except Exception as exc:
                print('DETAIL_ERROR', detail, repr(exc), flush=True)
    return list(dict.fromkeys(urls))


def valid_pdf_bytes(data: bytes) -> bool:
    return len(data) > 50_000 and data.lstrip()[:4] == b'%PDF'


def download_row(row: dict[str, Any], rank: int) -> dict[str, Any] | None:
    title = str(row.get('title') or '四环医药券商报告').strip()
    date = str(row.get('publishDate') or '')[:10]
    org = str(row.get('orgSName') or row.get('orgName') or '券商').strip()
    info = str(row.get('infoCode') or '').strip()
    for url in pdf_urls(row):
        try:
            response = S.get(url, timeout=(20, 240), allow_redirects=True, headers={
                'User-Agent': UA,
                'Referer': 'https://data.eastmoney.com/',
                'Accept': 'application/pdf,*/*;q=0.8',
            })
            data = response.content
            print('PDF_TRY', response.status_code, len(data), response.url[:220], flush=True)
            if not valid_pdf_bytes(data):
                continue
            filename = safe_name(f'{date}_{org}_{title}') + '.pdf'
            path = OUT / filename
            path.write_bytes(data)
            try:
                reader = PdfReader(str(path))
                pages = len(reader.pages)
                first_text = ''
                for idx in range(min(2, pages)):
                    try:
                        first_text += (reader.pages[idx].extract_text() or '') + '\n'
                    except Exception:
                        pass
                if pages < 8:
                    print('REJECT_TOO_SHORT', path.name, pages, flush=True)
                    path.unlink(missing_ok=True)
                    continue
                record = {
                    'rank': rank,
                    'file': path.name,
                    'path': str(path),
                    'title': title,
                    'date': date,
                    'broker': org,
                    'infoCode': info,
                    'pages': pages,
                    'bytes': len(data),
                    'sha256': hashlib.sha256(data).hexdigest(),
                    'source_url': response.url,
                    'first_text_sample': first_text[:1200],
                    'row': row,
                }
                print('DOWNLOADED', json.dumps({k: record[k] for k in ('file','pages','bytes','infoCode')}, ensure_ascii=False), flush=True)
                return record
            except Exception as exc:
                print('PDF_PARSE_ERROR', path.name, repr(exc), flush=True)
                path.unlink(missing_ok=True)
        except Exception as exc:
            print('PDF_ERROR', url[:180], repr(exc), flush=True)
    return None


all_matches: list[dict[str, Any]] = []
seen_info: set[str] = set()
scan_summary: list[dict[str, Any]] = []

for target in TARGETS:
    try:
        rows = fetch_window(target['begin'], target['end'])
    except Exception as exc:
        print('WINDOW_ERROR', target['key'], repr(exc), flush=True)
        scan_summary.append({'target': target['key'], 'error': repr(exc)})
        continue
    matches = []
    near = []
    for row in rows:
        matched, why = candidate_matches(row, target)
        blob = norm(json.dumps(row, ensure_ascii=False))
        if matched:
            copy = dict(row)
            copy['_target'] = target['key']
            copy['_match_reason'] = why
            matches.append(copy)
        elif any(x in blob for x in ('四环医药', '四環醫藥', '00460')) or any(norm(p) in blob for p in target['patterns']):
            near.append(row)
    print('TARGET_RESULT', target['key'], 'scanned', len(rows), 'matches', len(matches), 'near', len(near), flush=True)
    for row in matches:
        print('MATCH', target['key'], json.dumps(row, ensure_ascii=False)[:7000], flush=True)
        info = str(row.get('infoCode') or '')
        dedupe = info or norm(str(row.get('title'))) + norm(str(row.get('publishDate')))
        if dedupe not in seen_info:
            seen_info.add(dedupe)
            all_matches.append(row)
    for row in near[:20]:
        print('NEAR', target['key'], json.dumps(row, ensure_ascii=False)[:2500], flush=True)
    scan_summary.append({'target': target['key'], 'scanned': len(rows), 'matches': len(matches), 'near': len(near)})

(OUT / 'matched_rows.json').write_text(json.dumps(all_matches, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT / 'scan_summary.json').write_text(json.dumps(scan_summary, ensure_ascii=False, indent=2), encoding='utf-8')

# Prioritize the requested recent reports, then fallbacks.
priority = {target['key']: idx for idx, target in enumerate(TARGETS)}
all_matches.sort(key=lambda r: (priority.get(str(r.get('_target')), 999), str(r.get('publishDate') or '')))

downloaded: list[dict[str, Any]] = []
for row in all_matches:
    if len(downloaded) >= 3:
        break
    result = download_row(row, len(downloaded) + 1)
    if result:
        downloaded.append(result)

public_summary = []
for item in downloaded:
    public_summary.append({k: item[k] for k in ('rank','file','title','date','broker','infoCode','pages','bytes','sha256','source_url','first_text_sample')})
(OUT / 'downloaded_summary.json').write_text(json.dumps(public_summary, ensure_ascii=False, indent=2), encoding='utf-8')

readme_lines = [
    '四环医药（00460.HK）券商深度报告',
    f'成功下载并解析：{len(downloaded)} 份',
    '',
]
for item in public_summary:
    readme_lines.extend([
        f"{item['rank']}. {item['broker']}｜{item['date']}｜{item['title']}",
        f"   页数：{item['pages']}；文件：{item['file']}",
        f"   SHA-256：{item['sha256']}",
        '',
    ])
readme_lines.append('说明：仅收录可通过公开入口取得、能正常解析且不少于8页的完整PDF。')
(OUT / 'README.txt').write_text('\n'.join(readme_lines), encoding='utf-8')

zip_path = OUT / '四环医药_券商深度报告_公开完整PDF.zip'
with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=7) as zf:
    for item in downloaded:
        p = Path(item['path'])
        zf.write(p, arcname=p.name)
    for name in ('README.txt', 'downloaded_summary.json'):
        p = OUT / name
        if p.exists():
            zf.write(p, arcname=p.name)

print('FINAL_COUNT', len(downloaded), flush=True)
print('ZIP', zip_path, zip_path.stat().st_size if zip_path.exists() else 0, flush=True)
# Keep exit code zero so diagnostics are always uploaded.
sys.exit(0)
