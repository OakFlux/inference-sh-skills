import requests

urls = [
    "https://report.fxbaogao.com/report/2019/06/17/1332144.pdf",
    "https://report.fxbaogao.com/report/2019/06/17/1332144.pdf?download=1",
    "https://dr.fxbaogao.com/report/2019/06/17/1332144.pdf",
]
for url in urls:
    try:
        r = requests.get(
            url,
            headers={
                "User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
                "Accept":"application/pdf,*/*;q=0.8",
                "Referer":"https://www.fxbaogao.com/view?id=1332144",
            },
            timeout=(10,20),
            allow_redirects=True,
        )
        print("RESULT", r.status_code, r.url, r.headers.get("content-type"), len(r.content), r.content[:20], flush=True)
    except Exception as e:
        print("ERROR", url, repr(e), flush=True)
