import requests
url='https://data.eastmoney.com/newstatic/js/report/zw_macresearch.js'
r=requests.get(url,timeout=(20,120),headers={'User-Agent':'Mozilla/5.0','Referer':'https://data.eastmoney.com/report/info/AP201210260005551948.html'})
print('HTTP',r.status_code,len(r.content),r.url,flush=True)
r.raise_for_status()
lines=r.text.splitlines()
for start,end in [(5350,5425),(5425,5505),(500,780)]:
    print('RANGE',start,end,flush=True)
    for i in range(start,min(end,len(lines))+1):
        print(f'{i}: {lines[i-1]}',flush=True)
