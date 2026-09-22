from pathlib import Path
import json, hashlib, requests
from PIL import Image, ImageOps, ImageDraw

OUT=Path('cidi_dongwu_eet_assets'); OUT.mkdir(exist_ok=True)
URLS=[
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-faf9c0c193cec940e795569ce5b87d6c.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-a51250284b7c897e6c594d17aa87804d.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-6cf4fd06fab70a57f9f1c5705642d6d1.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-65d2c412b215a4802f91aeadf6a9bbb4.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-5ed21d2b6d682db279d0acfdc463cb1b.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-57852170dd3480137b1c6ba9ac942683.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-924a5984ad7da41d4eeccc20844dfeb2.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-a13c98576b56b17ef60d5083b651cdb9.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-2d95ce9695e4fc3caa2f23ad683a923e.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-da288beee38d2b9969943bc72f07938c.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-19207e0332e8c9115d4628c7525cb67c.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-73cf3954181556e366ec49ed9e41f6f7.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-90bc1c345f45d9e1788dd2b6833d7aa9.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-ca9ef543a4cb55b1c98fff38f189aca7.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-d7976f28718d7e27eb5f93879ec4e75c.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-850abbab8e360ddfb96fe61a5eff4777.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-13f5eb3aea8c0a914c24c5f9bbd97593.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-c47a2b9a8d063410323314800ffa1282.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-28455db50695b6274a8d485643ae5200.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-658eccf8994c18989a4851918b5a4c4f.png',
'https://static.mianbaoban-assets.eet-china.com/xinyu-images/MBXY-CR-8f051ab6e865d413b4cf68fbf5916d76.png',
]
s=requests.Session(); s.trust_env=False
headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.eet-china.com/mp/a472858.html','Accept':'image/avif,image/webp,image/apng,image/*,*/*;q=0.8'}
records=[]
for i,u in enumerate(URLS,1):
    r=s.get(u,headers=headers,timeout=(10,60)); r.raise_for_status()
    raw=OUT/f'{i:02d}.raw'; raw.write_bytes(r.content)
    with Image.open(raw) as im:
        im.load(); w,h=im.size; mode=im.mode; fmt=im.format
        if im.mode not in ('RGB','L'): im=im.convert('RGB')
        dest=OUT/f'{i:02d}.png'; im.save(dest,'PNG')
    raw.unlink()
    sha=hashlib.sha256(dest.read_bytes()).hexdigest()
    records.append({'index':i,'url':u,'width':w,'height':h,'format':fmt,'mode':mode,'bytes':dest.stat().st_size,'sha256':sha})
    print(i,w,h,dest.stat().st_size,flush=True)
# Contact sheets for visual verification.
for batch_start in range(0,len(records),6):
    batch=records[batch_start:batch_start+6]
    canvas=Image.new('RGB',(1200,1800),'white'); draw=ImageDraw.Draw(canvas)
    for j,rec in enumerate(batch):
        im=Image.open(OUT/f"{rec['index']:02d}.png").convert('RGB')
        im.thumbnail((360,760))
        col=j%3; row=j//3
        x=30+col*390+(360-im.width)//2; y=30+row*870+(760-im.height)//2
        canvas.paste(im,(x,y)); draw.text((30+col*390,800+row*870),f"#{rec['index']} {rec['width']}x{rec['height']}",fill='black')
    canvas.save(OUT/f'contact_{batch_start+1:02d}_{batch_start+len(batch):02d}.jpg','JPEG',quality=85)
(OUT/'manifest.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
