from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

session = requests.Session()
session.trust_env = False
session.headers.update({"User-Agent": "Mozilla/5.0 Chrome/152 Safari/537.36"})

for report_id in (966932, 967723):
    url = f"https://www.fxbaogao.com/view?id={report_id}"
    response = session.get(url, timeout=120)
    print("PAGE", report_id, response.status_code, response.url, response.headers.get("content-type"), len(response.content))
    print(response.text[:25000])
    soup = BeautifulSoup(response.text, "html.parser")
    print("TITLE", soup.title.get_text(" ", strip=True) if soup.title else "")
    for tag in soup.find_all(["script", "link", "img", "a", "iframe"]):
        location = tag.get("src") or tag.get("href")
        if location:
            print("ASSET", tag.name, urljoin(response.url, location), tag.get_text(" ", strip=True)[:150])
