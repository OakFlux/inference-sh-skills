import requests
from urllib.parse import urljoin

s=requests.Session(); s.trust_env=False
headers={
 'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36',
 'Accept':'application/pdf,*/*;q=0.8',
 'Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8',
 'Referer':'https://www.fxbaogao.com/view?id=1332144',
 'Origin':'https://www.fxbaogao.com',
}
for initial in [
 'https://report.fxbaogao.com/report/2019/06/17/1332144.pdf?download=1',
 'https://report.fxbaogao.com/report/2019/06/17/1332144.pdf?download=true',
 'https://report.fxbaogao.com/report/2019/06/17/1332144.pdf?attachment=1',
]:
 print('\nINITIAL',initial,flush=True)
 url=initial
 for hop in range(8):
  try:
   r=s.get(url,headers=headers,timeout=(15,30),allow_redirects=False)
  except Exception as e:
   print('ERROR',hop,url,repr(e),flush=True); break
  print('HOP',hop,r.status_code,r.url,r.headers.get('content-type'),len(r.content),'LOC',r.headers.get('location'),'SETCOOKIE',r.headers.get('set-cookie'),r.content[:80],flush=True)
  loc=r.headers.get('location')
  if not loc or r.status_code not in (301,302,303,307,308): break
  url=urljoin(r.url,loc)
