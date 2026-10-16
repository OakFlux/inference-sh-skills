import requests

u='https://www.fxbaogao.com/_fxbg/2610141742/js/app-pages-fxbg-main-js.fd6234d1ab18d90a303e.chunk.js'
r=requests.get(u,timeout=120,headers={'User-Agent':'Mozilla/5.0'})
r.raise_for_status()
s=r.text
key='ca1f3b6f05410ce35d4a:function'
i=s.find(key)
print('INDEX',i,'LEN',len(s),flush=True)
print(s[i:i+30000],flush=True)
