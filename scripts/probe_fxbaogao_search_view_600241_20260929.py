from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urljoin

import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36"
s = requests.Session()
s.trust_env = False
headers = {
    "User-Agent": UA,
    "Accept": "text/html,application/json,image/avif,image/webp,image/png,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def decode(r: requests.Response) -> str:
    for enc in (r.encoding, r.apparent_encoding, "utf-8", "gb18030"):
        if not enc:
            continue
        try:
            return r.content.decode(enc)
        except Exception:
            pass
    return r.content.decode("utf-8", errors="replace")

# Search page
search_url = "https://www.fxbaogao.com/rp?keywords=%E6%97%B6%E4%BB%A3%E4%B8%87%E6%81%92&order=2&nop=-1"
r = s.get(search_url, headers=headers, timeout=90, allow_redirects=True)
print("SEARCH", r.status_code, r.url, r.headers.get("content-type"), len(r.content), flush=True)
text = decode(r)
print("SEARCH_HEAD", re.sub(r"\s+", " ", text[:60000]), flush=True)
links = []
for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, flags=re.I | re.S):
    href = unescape(m.group(1))
    label = re.sub(r"<[^>]+>", "", unescape(m.group(2)))
    label = re.sub(r"\s+", " ", label).strip()
    if "时代万恒" in label or "600241" in label:
        links.append({"label": label, "url": urljoin(r.url, href)})
print("SEARCH_LINKS", json.dumps(links, ensure_ascii=False, indent=2), flush=True)
for pat in (
    r'/detail/(\d+)',
    r'"docId"\s*:\s*"?(\d+)"?',
    r'"title"\s*:\s*"([^"]*时代万恒[^"]*)"',
):
    vals = re.findall(pat, text, flags=re.I)
    print("SEARCH_PATTERN", pat, vals[:200], flush=True)

# Detail/view page and image sequence probe
for doc_id, date_path in [("1623958", "2010/11/08")]:
    for view_url in (
        f"https://www.fxbaogao.com/view?id={doc_id}",
        f"https://m.fxbaogao.com/view?id={doc_id}",
    ):
        try:
            v = s.get(view_url, headers=headers, timeout=90, allow_redirects=True)
            vt = decode(v)
            print("VIEW", view_url, v.status_code, v.url, v.headers.get("content-type"), len(v.content), flush=True)
            print("VIEW_HEAD", re.sub(r"\s+", " ", vt[:80000]), flush=True)
            for pat in (
                r'https?://[^"\'<> ]+report-image[^"\'<> ]+',
                r'["\']([^"\']+\.(?:png|jpg|jpeg|webp)[^"\']*)["\']',
                r'(?:pageCount|pages|pageNum|totalPage|totalPages)["\']?\s*[:=]\s*["\']?(\d+)',
                r'(?:docId|id)["\']?\s*[:=]\s*["\']?(\d+)',
            ):
                vals = re.findall(pat, vt, flags=re.I)
                print("VIEW_PATTERN", pat, vals[:200], flush=True)
        except Exception as exc:
            print("VIEW_ERROR", view_url, repr(exc), flush=True)

    valid = []
    for i in range(1, 81):
        candidates = [
            f"https://public.fxbaogao.com/report-image/{date_path}/{doc_id}-{i}.png",
            f"https://public.fxbaogao.com/report-image/{date_path}/{doc_id}-{i}.jpg",
            f"https://public.fxbaogao.com/report-image/{date_path}/{doc_id}-{i}.jpeg",
        ]
        found = False
        for image_url in candidates:
            try:
                x = s.get(image_url, headers=headers, timeout=40, allow_redirects=True)
                ct = (x.headers.get("content-type") or "").lower()
                head = x.content[:12]
                ok = x.status_code == 200 and len(x.content) > 1000 and ("image" in ct or head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8"))
                print("IMAGE", i, image_url, x.status_code, ct, len(x.content), head, "OK", ok, flush=True)
                if ok:
                    valid.append(image_url)
                    found = True
                    break
            except Exception as exc:
                print("IMAGE_ERROR", i, image_url, repr(exc), flush=True)
        if not found and i > 1:
            break
    print("VALID_IMAGES", json.dumps(valid, ensure_ascii=False, indent=2), flush=True)
