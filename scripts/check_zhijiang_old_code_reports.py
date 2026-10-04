import html
import json
import re
from urllib.parse import urljoin

import requests

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

params = {
    "industryCode": "*",
    "pageSize": "100",
    "industry": "*",
    "rating": "*",
    "ratingChange": "*",
    "beginTime": "2015-01-01",
    "endTime": "2030-01-01",
    "pageNo": "1",
    "fields": "",
    "qType": "0",
    "orgCode": "",
    "code": "834839",
    "rcode": "",
    "p": "1",
    "pageNum": "1",
    "pageNumber": "1",
}
response = session.get(
    "https://reportapi.eastmoney.com/report/list",
    params=params,
    headers={**headers, "Referer": "https://data.eastmoney.com/report/"},
    timeout=90,
)
print("EASTMONEY", response.status_code, response.url, response.text[:50000], flush=True)

urls = [
    "https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=834839&t1=all",
    "https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=oc834839&t1=all",
]
report_urls = []
for url in urls:
    response = session.get(url, headers=headers, timeout=90, allow_redirects=True)
    response.encoding = response.apparent_encoding or response.encoding or "gbk"
    text = response.text
    clean = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.I | re.S)
    clean = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", clean)))
    print("SINA", url, response.status_code, response.url, clean[:20000], flush=True)
    for match in re.finditer(r'''href\s*=\s*["']([^"']+)["']''', text, re.I):
        full = urljoin(response.url, html.unescape(match.group(1)))
        if "vReport_Show" in full or "/rptid/" in full:
            report_urls.append(full)

report_urls = list(dict.fromkeys(report_urls))
print("REPORT_URLS", json.dumps(report_urls, ensure_ascii=False, indent=2), flush=True)
for url in report_urls:
    response = session.get(url, headers=headers, timeout=90, allow_redirects=True)
    response.encoding = response.apparent_encoding or response.encoding or "gbk"
    text = response.text
    title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""
    links = []
    for match in re.finditer(r'''href\s*=\s*["']([^"']+)["']''', text, re.I):
        full = urljoin(response.url, html.unescape(match.group(1)))
        if any(token in full.lower() for token in ("pdf", "/url", "download", "file.finance")):
            links.append(full)
    print("DETAIL", url, title, json.dumps(list(dict.fromkeys(links)), ensure_ascii=False), flush=True)
