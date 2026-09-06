#!/usr/bin/env python3
import csv,hashlib,re,shutil,subprocess,time,zipfile
from pathlib import Path
import requests
from pypdf import PdfReader

OUT=Path('明源云_券商研究报告_3份'); WORK=Path('_myc_work'); PRE=WORK/'preview'
OUT.mkdir(exist_ok=True); PRE.mkdir(parents=True,exist_ok=True)
CN=Path('明源云_券商深度研究报告_3份.zip'); EN=Path('MYC_Broker_Reports.zip')
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36'
S=requests.Session(); S.headers.update({'User-Agent':UA,'Accept-Language':'en-US,en;q=0.9'})
REPORTS=[
 {'date':'2022-08-23','title':'Weak SaaS demand with tighter cost control ahead','cn':'SaaS需求偏弱，后续将加强成本控制','article':'https://www.cmbi.com.hk/article/7176.html?lang=en','urls':['https://hk-official.cmbi.info/upload/00f9be3f-8627-4737-a24a-42b81d76b409.pdf']},
 {'date':'2021-11-16','title':'Property policy bottomed but sales data still weak','cn':'房地产政策见底，但销售数据仍弱','article':'https://www.cmbi.com.hk/article/6103.html?lang=en','urls':['https://sg.cmbi.com/upload/202111/20211116792201.pdf','https://hk-official.cmbi.info/upload/b21df84e-f644-4219-bfa3-63707e24006c.pdf']},
 {'date':'2021-05-10','title':'In a sweet spot','cn':'基础性覆盖报告：处于有利增长位置','article':'https://www.cmbi.com.hk/article/5430.html?lang=en','urls':['https://hk-official.cmbi.info/upload/4751eaf2-99b3-4354-bf01-8d8828ba71b6.pdf']},
]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest()
def get(urls):
 errs=[]
 for n in range(3):
  for u in urls:
   try:
    r=S.get(u,headers={'User-Agent':UA,'Referer':'https://www.cmbi.com.hk/','Accept':'application/pdf,*/*'},timeout=(30,600),allow_redirects=True)
    print('GET',r.status_code,len(r.content),u,flush=True)
    if r.status_code==200 and r.content.startswith(b'%PDF-'): return r.content,u,r.url
    errs.append(f'{u}:{r.status_code}/{len(r.content)}')
   except Exception as e: errs.append(f'{u}:{e!r}')
  time.sleep(2+n)
 raise RuntimeError(';'.join(errs))
def text(p,reader):
 a=[]
 for i in range(min(20,len(reader.pages))):
  try:a.append(reader.pages[i].extract_text() or '')
  except Exception:pass
 return re.sub(r'\s+','',('\n'.join(a)).upper())
def clean(t): return re.sub(r'[^A-Za-z0-9]+','_',t).strip('_')[:65]
records=[]
for i,x in enumerate(REPORTS,1):
 data,req,res=get(x['urls']); tmp=WORK/f'{i}.pdf'; tmp.write_bytes(data)
 rd=PdfReader(str(tmp)); pages=len(rd.pages)
 if pages<5: raise RuntimeError(f'{x["title"]}: only {pages} pages')
 q=subprocess.run(['qpdf','--check',str(tmp)],capture_output=True,text=True)
 if q.returncode not in (0,3): raise RuntimeError(q.stderr[-500:])
 tx=text(tmp,rd); company=('MINGYUANCLOUD' in tx or '909HK' in tx or '0909HK' in tx); broker=('CMBINTERNATIONAL' in tx or 'CMBIS' in tx)
 if not company or not broker: raise RuntimeError(f'identity check failed {x["title"]} company={company} broker={broker}')
 for label,pn in [('first',1),('last',pages)]:
  prefix=PRE/f'{i}_{label}'; subprocess.run(['pdftoppm','-f',str(pn),'-l',str(pn),'-singlefile','-png','-r','90',str(tmp),str(prefix)],check=True,capture_output=True)
  if Path(str(prefix)+'.png').stat().st_size<1000: raise RuntimeError('render failed')
 name=f'{i:02d}_招银国际_明源云_{x["date"]}_{clean(x["title"])}_{pages}页.pdf'; dst=OUT/name; shutil.copy2(tmp,dst)
 rec={**x,'sequence':i,'filename':name,'pages':pages,'bytes':dst.stat().st_size,'sha256':sha(dst),'requested':req,'resolved':res,'company':company,'broker':broker}
 records.append(rec); print('VERIFIED',rec,flush=True)
if len({r['sha256'] for r in records})!=3: raise RuntimeError('duplicate PDF')
with (OUT/'来源与校验清单.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.writer(f); w.writerow(['序号','文件名','券商','报告日期','英文标题','中文说明','页数','文件大小_字节','SHA256','券商文章页','PDF地址'])
 for r in records:w.writerow([r['sequence'],r['filename'],'招银国际',r['date'],r['title'],r['cn'],r['pages'],r['bytes'],r['sha256'],r['article'],r['resolved']])
lines=['明源云集团控股有限公司（0909.HK）券商研究报告包','整理日期：2026-09-06','','仅收录招银国际官方网站可直接取得并完成结构校验的原始PDF；未收录付费摘要、缺页预览或图片拼接版。','','文件清单：']
for r in records:lines.append(f"{r['sequence']}. {r['filename']}｜{r['pages']}页｜SHA-256：{r['sha256']}")
lines+=['','校验：PDF文件头、实际页数、公司名称/股票代码、券商署名、qpdf结构及首尾页渲染均已检查。','详细来源见《来源与校验清单.csv》。']
(OUT/'README_文件说明.txt').write_text('\n'.join(lines),encoding='utf-8')
for z in (CN,EN):
 with zipfile.ZipFile(z,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as a:
  for p in sorted(OUT.rglob('*')):
   if p.is_file():a.write(p,arcname=str(p))
 with zipfile.ZipFile(z) as a:
  bad=a.testzip()
  if bad:raise RuntimeError(bad)
Path('PACKAGE_SHA256.txt').write_text(f'{sha(EN)}  {EN.name}\n',encoding='utf-8')
print('PACKAGE',EN,EN.stat().st_size,sha(EN),flush=True)
