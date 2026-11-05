#!/usr/bin/env python3
"""GEM12 Sub-Screen Studio

Web UI for the AOOSTAR GEM12 mini-PC front sub-screen (960x376).
Upload an image, pick a layout, crop freely, push it to the screen.

The screen itself is driven by AOOSTAR's own Linux agent (AOOSTAR-X), which
serves a small web API on port 5123. This app talks to that API instead of
speaking the USB protocol directly.

Config: environment variables or config.json next to this file.
"""
import base64
import http.cookiejar
import io
import json
import os
import random
import subprocess
import urllib.parse
import urllib.request
import uuid

from flask import Flask, abort, jsonify, render_template_string, request, send_file
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load_config():
    cfg = {
        "aoostar_url": "http://127.0.0.1:5123",
        "username": "admin",
        "password": "123456",
        "restart_cmd": "systemctl restart aoostar-x-service",
        "data_dir": os.path.join(ROOT, "data"),
        "switch_time": "60",
        "fonts": [],
    }
    path = os.path.join(ROOT, "config.json")
    if os.path.exists(path):
        cfg.update(json.load(open(path)))
    for k in ("aoostar_url", "username", "password", "restart_cmd", "data_dir", "switch_time"):
        env = os.environ.get("GEM12_" + k.upper())
        if env:
            cfg[k] = env
    return cfg


CFG = load_config()
HEADER = CFG.get("header", "GEM12")
APP_URL = CFG["aoostar_url"].rstrip("/")
UP = os.path.join(CFG["data_dir"], "uploads")
STORE = os.path.join(CFG["data_dir"], "panels.json")
DEFAULTS = os.path.join(CFG["data_dir"], "defaults.json")
os.makedirs(UP, exist_ok=True)

W, H = 960, 376                 # full canvas
FW, FH, FX, FY = 372, 336, 556, 20   # photo-card geometry
CX = 235                        # centre of the text column
ROWS = ((226, "CPU 温度"), (264, "CPU 占用"), (302, "内 存"))

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJKsc-Bold.otf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def font_path():
    for p in list(CFG.get("fonts") or []) + FONT_CANDIDATES:
        if p and os.path.exists(p):
            return p
    return None


FONT = font_path()

def _has_cjk(path):
    if not path:
        return False
    try:
        f = ImageFont.truetype(path, 20)
        return f.getmask("温").getbbox() is not None
    except Exception:
        return False


if not _has_cjk(FONT):
    import sys
    print("[warn] no CJK-capable font found — install one (e.g. apt install fonts-noto-cjk) "
          "or set \"fonts\" in config.json, otherwise Chinese labels render as boxes.",
          file=sys.stderr)

app = Flask(__name__)


def F(size):
    if FONT:
        return ImageFont.truetype(FONT, size)
    return ImageFont.load_default()


# ---------------------------------------------------------------- rendering
def base_bg():
    bg = Image.new("RGB", (W, H), (12, 9, 18))
    d = ImageDraw.Draw(bg)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(13 + 12 * t), int(9 + 7 * t), int(20 + 20 * t)))
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([FX - 60, FY - 40, FX + FW + 60, FY + FH + 40], fill=60)
    glow = glow.filter(ImageFilter.GaussianBlur(45))
    bg = Image.composite(Image.new("RGB", (W, H), (74, 38, 70)), bg, glow)
    random.seed(5)
    d = ImageDraw.Draw(bg)
    for _ in range(120):
        x, y = random.randint(0, 520), random.randint(0, H)
        a = random.randint(35, 120)
        d.point((x, y), fill=(a + 90, a + 80, a + 120))
    return bg


def fit_crop(im, cx, cy, cw, ar):
    """Crop a region with aspect ratio `ar`; None params => auto cover."""
    iw, ih = im.size
    if not cw:
        cw = min(iw, ih * ar)
        cx, cy = iw / 2, ih * 0.42
    cw = max(16, min(cw, iw, ih * ar))
    ch = cw / ar
    cx = min(max(cx, cw / 2), iw - cw / 2)
    cy = min(max(cy, ch / 2), ih - ch / 2)
    left, top = round(cx - cw / 2), round(cy - ch / 2)
    return (left, top, left + round(cw), top + round(ch))


def rounded_card(im, cx=None, cy=None, cw=None):
    im = im.convert("RGB")
    crop = im.crop(fit_crop(im, cx, cy, cw, FW / FH)).resize((FW, FH), Image.LANCZOS)
    mask = Image.new("L", (FW, FH), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, FW - 1, FH - 1], radius=16, fill=255)
    card = Image.new("RGBA", (FW, FH), (0, 0, 0, 0))
    card.paste(crop, (0, 0), mask)
    ImageDraw.Draw(card).rounded_rectangle([1, 1, FW - 2, FH - 2], radius=16,
                                           outline=(196, 140, 170, 180), width=2)
    return card


def scrim(bg, strength=232, span=560):
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    for x in range(W):
        d.line([(x, 0), (x, H)], fill=int(strength * max(0.0, 1 - x / span) ** 1.25))
    return Image.composite(Image.new("RGB", (W, H), (9, 7, 14)), bg.convert("RGB"), mask)


def compose(im, caption="", cx=None, cy=None, cw=None, style="card", bg_path=None):
    """style: card | full | layered"""
    im = im.convert("RGB")

    if style == "layered":
        if bg_path and os.path.exists(bg_path):
            bim = Image.open(bg_path).convert("RGB")
            bg = bim.crop(fit_crop(bim, None, None, None, W / H)).resize((W, H), Image.LANCZOS)
            bg = bg.convert("RGBA")
            bg.alpha_composite(Image.new("RGBA", (W, H), (6, 5, 11, 70)))
            bg = scrim(bg, 190, 520).convert("RGBA")
        else:
            bg = base_bg().convert("RGBA")
        card = rounded_card(im, cx, cy, cw)
        sh = Image.new("RGBA", card.size, (0, 0, 0, 0))
        sh.paste((0, 0, 0, 160), (0, 0), card.split()[3])
        bg.alpha_composite(sh.filter(ImageFilter.GaussianBlur(16)), (FX + 4, FY + 8))
        bg.alpha_composite(card, (FX, FY))

    elif style == "full":
        bg = im.crop(fit_crop(im, cx, cy, cw, W / H)).resize((W, H), Image.LANCZOS).convert("RGBA")
        bg = scrim(bg, 232, 560).convert("RGBA")
        bottom = Image.new("L", (W, H), 0)
        bd = ImageDraw.Draw(bottom)
        for y in range(H):
            bd.line([(0, y), (W, y)], fill=int(90 * max(0.0, (y - 300) / 76) ** 1.2))
        bg = Image.composite(Image.new("RGB", (W, H), (8, 6, 12)), bg.convert("RGB"), bottom).convert("RGBA")

    else:  # card
        bg = base_bg().convert("RGBA")
        card = rounded_card(im, cx, cy, cw)
        sh = Image.new("RGBA", card.size, (0, 0, 0, 0))
        sh.paste((0, 0, 0, 150), (0, 0), card.split()[3])
        bg.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)), (FX + 4, FY + 8))
        bg.alpha_composite(card, (FX, FY))

    d = ImageDraw.Draw(bg)
    d.text((CX, 34), "  ".join(HEADER.upper()), font=F(15), fill=(228, 124, 156), anchor="mt")
    for y, label in ROWS:
        d.text((70, y), label, font=F(22), fill=(160, 142, 190), anchor="lm")
        d.line([(70, y + 24), (400, y + 24)], fill=(46, 38, 64))
    if caption:
        d.text((CX, 348), caption, font=F(16), fill=(206, 155, 182), anchor="mm")

    out = io.BytesIO()
    bg.convert("RGB").save(out, "JPEG", quality=92)
    return out.getvalue()


# ---------------------------------------------------------------- app bridge
def sensor(name, label, cx, cy, size, color, unit="", dec=-1, w=400):
    h = round(size * 1.16)
    return {"id": str(uuid.uuid4()), "itemName": name, "mode": 1, "direction": 1, "type": 1,
            "label_name2": "", "label": label, "value": "",
            "x": round(cx - w / 2, 1), "y": round(cy - h / 2 + 2, 1), "width": w, "height": h,
            "fontColor": color, "fontSize": size, "fontFamily": "HarmonyOS_Sans_SC_Bold",
            "fontWeight": "normal", "unit": unit, "integerDigits": -1, "decimalDigits": dec,
            "textAlign": "center", "minAngle": 0, "maxAngle": 360, "minValue": 0, "maxValue": 100,
            "xz_x": 0, "xz_y": 0, "pic": ""}


SENSORS = [
    sensor("时间", "DATE_h_m_2", CX, 122, 86, "#f7f1ff"),
    sensor("日期", "DATE_y_m_d_3", CX, 182, 19, "#b09ece", dec=0),
    sensor("CPU温度", "cpu_temperature", 300, 226, 32, "#ffd7e6", " ℃", dec=0),
    sensor("CPU占用", "cpu_percent", 300, 264, 32, "#d8f0ff", " %", dec=0),
    sensor("内存", "memory_usage", 300, 302, 32, "#efe0ff", " %", dec=0),
]


def api_login():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.open(APP_URL + "/", data=urllib.parse.urlencode(
        {"username": CFG["username"], "password": CFG["password"]}).encode())
    return op


def push(panels):
    op = api_login()
    body = {"panels": []}
    for p in panels:
        im = Image.open(p["file"])
        jpg = compose(im, p.get("caption", ""), p.get("cx"), p.get("cy"), p.get("cw"),
                      p.get("style", "card"), p.get("bg"))
        body["panels"].append({"id": p["id"], "name": p.get("name", "custom"), "checked": True, "img": "",
                               "imgData": "data:image/jpeg;base64," + base64.b64encode(jpg).decode(),
                               "sensor": SENSORS})
    req = urllib.request.Request(APP_URL + "/save_custom_panels",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    op.open(req).read()


def apply_now():
    """Ask the AOOSTAR agent to reload panels (usually restarts its service)."""
    cmd = CFG.get("restart_cmd")
    if cmd:
        subprocess.run(cmd, shell=True, capture_output=True, timeout=180,
                       env={**os.environ, "GEM12_SWITCH": str(CFG.get("switch_time", "60"))})


def load():
    return json.load(open(STORE)) if os.path.exists(STORE) else []


def save(panels):
    json.dump(panels, open(STORE, "w"), ensure_ascii=False, indent=2)


def find(pid):
    for p in load():
        if p["id"] == pid:
            return p
    return None


def builtin_defaults():
    return []


def current_defaults():
    if os.path.exists(DEFAULTS):
        try:
            d = [p for p in json.load(open(DEFAULTS)) if os.path.exists(p.get("file", ""))]
            if d:
                return d
        except Exception:
            pass
    return builtin_defaults()


INDEX = """<!doctype html><meta charset=utf-8><title>GEM12 Sub-Screen</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
body{margin:0;background:#0d0a14;color:#e9e2f5;font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1060px;margin:0 auto;padding:26px 20px 60px}
h1{font-size:20px;font-weight:600;letter-spacing:.16em;color:#e07c9c;margin:0 0 4px}
.sub{color:#8e7fa8;font-size:13px;margin-bottom:20px}
#drop{border:1.5px dashed #3a2d50;border-radius:16px;padding:36px;text-align:center;color:#9b8bb7;transition:.2s;cursor:pointer}
#drop.on{border-color:#e07c9c;background:#1a1226;color:#f0e6fa}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;margin-top:22px}
.card{background:#15101f;border:1px solid #251b36;border-radius:14px;overflow:hidden}
.card img{width:100%;display:block}
.bar{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;font-size:12px;color:#9b8bb7;gap:8px}
button{background:#2a1b38;color:#f0e6fa;border:1px solid #4a2f5e;border-radius:9px;padding:7px 14px;cursor:pointer;font-size:13px}
button:hover{background:#3a2349}
.row{display:flex;gap:10px;align-items:center;margin-top:16px;flex-wrap:wrap}
</style>
<div class=wrap>
<h1>GEM12 SUB-SCREEN</h1>
<div class=sub>Upload an image → pick a layout (card / full-bleed / background + card) → crop freely → push to the 960×376 screen.</div>
<div id=drop>Drop an image here / click to choose</div>
<input type=file id=f accept="image/*" multiple hidden>
<div class=row><button onclick="act('restart')">Re-push</button><button onclick="act('setdefault')">Save as default</button><button onclick="act('reset')">Restore default</button></div>
<div class=grid id=list></div>
</div>
<script>
const drop=document.getElementById('drop'), fi=document.getElementById('f');
drop.onclick=()=>fi.click();
drop.ondragover=e=>{e.preventDefault();drop.classList.add('on')};
drop.ondragleave=()=>drop.classList.remove('on');
drop.ondrop=e=>{e.preventDefault();drop.classList.remove('on');up([...e.dataTransfer.files])};
fi.onchange=()=>up([...fi.files]);
async function up(files){
  if(!files.length) return;
  const fd=new FormData(); files.forEach(f=>fd.append('files',f));
  drop.textContent='uploading…';
  const j=await (await fetch('/api/upload',{method:'POST',body:fd})).json();
  if(j.id){location='/edit/'+j.id}else{drop.textContent=j.msg||'failed';load()}
}
async function act(a){const r=await fetch('/api/'+a,{method:'POST'}); drop.textContent=(await r.json()).msg; load();}
async function del(id){await fetch('/api/del?id='+id,{method:'POST'}); load();}
async function load(){
  const j=await (await fetch('/api/list')).json();
  document.getElementById('list').innerHTML=j.panels.map(p=>
   `<div class=card><img src="/thumb/${p.id}"><div class=bar><span>${p.name}</span>
    <span><button onclick="location='/edit/${p.id}'">crop</button> <button onclick="del('${p.id}')">del</button></span></div></div>`
   ).join('')||'<div class=sub>no panels yet</div>';
}
load();
</script>"""

EDIT = """<!doctype html><meta charset=utf-8><title>Crop · GEM12 Sub-Screen</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
body{margin:0;background:#0d0a14;color:#e9e2f5;font:14px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:22px 18px 60px}
h1{font-size:17px;color:#e07c9c;letter-spacing:.12em;margin:0 0 14px;font-weight:600}
.cols{display:flex;gap:26px;flex-wrap:wrap;align-items:flex-start}
#vp{width:558px;max-width:92vw;background:#000;border-radius:14px;overflow:hidden;
    position:relative;cursor:grab;touch-action:none;border:1px solid #38284c;box-shadow:0 12px 40px #0008}
#vp.drag{cursor:grabbing}
#vp img{position:absolute;left:50%;top:50%;will-change:transform;user-select:none;-webkit-user-drag:none}
#preview{width:520px;max-width:100%;border-radius:12px;border:1px solid #2b2038;display:block;background:#0a0710}
.panel{background:#141021;border:1px solid #241a33;border-radius:14px;padding:16px}
.lbl{color:#8e7fa8;font-size:12px;letter-spacing:.08em;margin-bottom:6px}
.seg{display:inline-flex;border:1px solid #3a2a4e;border-radius:10px;overflow:hidden;margin-bottom:4px}
.seg button{border:0;border-radius:0;background:#181125;padding:8px 16px}
.seg button.on{background:#8c3b5c}
input[type=range]{width:100%;accent-color:#e07c9c}
input[type=text]{background:#0f0b17;border:1px solid #2b203c;color:#e9e2f5;border-radius:9px;
  padding:8px 10px;width:100%;box-sizing:border-box}
button{background:#2a1b38;color:#f0e6fa;border:1px solid #4a2f5e;border-radius:9px;padding:9px 16px;cursor:pointer;font-size:14px}
button.pri{background:#8c3b5c;border-color:#b4527c}
.row{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap}
.hint{color:#6f6186;font-size:12px;margin-top:8px}
#status{color:#9be0b0;font-size:13px;margin-top:10px;min-height:20px}
</style>
<div class=wrap>
<h1>Framing · drag to pan / scroll to zoom</h1>
<div class=cols>
  <div>
    <div id=vp><img id=img src="/src/{{pid}}" draggable=false></div>
    <div class=panel style="margin-top:12px">
      <div class=lbl>layout</div>
      <div class=seg>
        <button id=bCard onclick="setStyle('card')">card</button>
        <button id=bFull onclick="setStyle('full')">full-bleed</button>
        <button id=bLay onclick="setStyle('layered')">bg + card</button>
      </div>
      <div id=bgBox style="display:none;margin-top:10px">
        <div class=lbl>background image (for "bg + card")</div>
        <input type=file id=bgFile accept="image/*" style="color:#9b8bb7;font-size:12px">
        <div class=hint id=bgHint>background: {{bghint}}</div>
      </div>
      <div class=lbl style="margin-top:12px">zoom</div>
      <input type=range id=zoom min=1 max=4 step=0.01 value=1>
      <div class=lbl style="margin-top:12px">caption (optional)</div>
      <input type=text id=cap value="{{caption}}" placeholder="a line of text at the bottom">
      <div class=row>
        <button class=pri onclick=apply()>Apply to screen</button>
        <button onclick=reset()>Reset</button>
        <button onclick="location='/'">Back</button>
      </div>
      <div id=status></div>
      <div class=hint>full-bleed darkens the left edge automatically so the readouts stay legible.</div>
    </div>
  </div>
  <div>
    <div class=lbl>live preview (what the screen gets)</div>
    <img id=preview src="/api/panel_preview/{{pid}}">
  </div>
</div>
</div>
<script>
const PID="{{pid}}";
const VW=558;
let STYLE="{{style}}";
let ASP = STYLE==='full' ? 960/376 : 372/336;
let VH = Math.round(VW/ASP);
const img=document.getElementById('img'), vp=document.getElementById('vp'), zs=document.getElementById('zoom');
let IW=0, IH=0, b=1, z=1, ox=0, oy=0;
const init={{init|safe}};

function markStyle(){ document.getElementById('bCard').classList.toggle('on', STYLE==='card');
  document.getElementById('bFull').classList.toggle('on', STYLE==='full');
  document.getElementById('bLay').classList.toggle('on', STYLE==='layered');
  document.getElementById('bgBox').style.display = STYLE==='layered' ? 'block' : 'none'; }

function measure(){ b=Math.max(VW/IW, VH/IH);
  img.style.width=(IW*b)+'px'; img.style.height=(IH*b)+'px';
  img.style.marginLeft=(-IW*b/2)+'px'; img.style.marginTop=(-IH*b/2)+'px'; }
function clamp(){ const dw=IW*b*z, dh=IH*b*z;
  const mx=Math.max(0,(dw-VW)/2), my=Math.max(0,(dh-VH)/2);
  ox=Math.min(mx,Math.max(-mx,ox)); oy=Math.min(my,Math.max(-my,oy)); }
function render(){ img.style.transform=`translate(${ox}px,${oy}px) scale(${z})`; }
function curCW(){ return VW/(b*z); }
function curCenter(){ return [IW/2 - ox/(b*z), IH/2 - oy/(b*z)]; }
function layout(){ vp.style.height=VH+'px'; if(IW){ measure(); clamp(); render(); apc(); } }

function setStyle(s){ if(s===STYLE) return; STYLE=s;
  ASP = s==='full' ? 960/376 : 372/336; VH = Math.round(VW/ASP);
  z=1; ox=0; oy=0; zs.value=1; markStyle(); layout(); }

document.getElementById('bgFile').onchange = async e => {
  const f=e.target.files[0]; if(!f) return;
  const fd=new FormData(); fd.append('file', f);
  document.getElementById('bgHint').textContent='uploading…';
  const j=await (await fetch('/api/setbg?id='+PID,{method:'POST',body:fd})).json();
  document.getElementById('bgHint').textContent=j.msg||'done'; apc();
};

img.onload=()=>{ IW=img.naturalWidth; IH=img.naturalHeight; measure();
  if(init.cw){ z=Math.min(4,Math.max(1,VW/(b*init.cw)));
    ox=(IW/2-init.cx)*b*z; oy=(IH/2-init.cy)*b*z; zs.value=z; }
  clamp(); render(); apc(); };
if(img.complete && img.naturalWidth) img.onload();

let down=false, sx=0, sy=0, sox=0, soy=0;
vp.onpointerdown=e=>{down=true;vp.classList.add('drag');sx=e.clientX;sy=e.clientY;sox=ox;soy=oy;vp.setPointerCapture(e.pointerId)};
vp.onpointermove=e=>{if(!down)return;ox=sox+(e.clientX-sx);oy=soy+(e.clientY-sy);clamp();render();apc()};
vp.onpointerup=()=>{down=false;vp.classList.remove('drag')};
vp.onwheel=e=>{e.preventDefault();zs.value=Math.min(4,Math.max(1,parseFloat(zs.value)-Math.sign(e.deltaY)*0.08));zs.oninput()};
zs.oninput=()=>{const nz=parseFloat(zs.value); const k=nz/z; ox*=k; oy*=k; z=nz; clamp(); render(); apc();};

let t=null;
function apc(){ clearTimeout(t); t=setTimeout(()=>{
  const [cx,cy]=curCenter();
  document.getElementById('preview').src=`/api/panel_preview/${PID}?cx=${cx}&cy=${cy}&cw=${curCW()}`
    +`&style=${STYLE}&cap=`+encodeURIComponent(document.getElementById('cap').value)+`&t=${Date.now()}`;
},300); }

function reset(){ z=1; ox=0; oy=0; zs.value=1; clamp(); render(); apc(); }

async function apply(){
  const [cx,cy]=curCenter();
  const body={id:PID,cx:cx,cy:cy,cw:curCW(),style:STYLE,caption:document.getElementById('cap').value};
  document.getElementById('status').textContent='pushing…';
  const j=await (await fetch('/api/crop',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body)})).json();
  document.getElementById('status').textContent=j.msg||'done';
}
markStyle(); layout();
</script>"""


# ---------------------------------------------------------------- routes
@app.route("/")
def index():
    return render_template_string(INDEX)


@app.route("/api/list")
def api_list():
    return jsonify(panels=[{"id": p["id"], "name": p.get("name", "")} for p in load()])


@app.route("/thumb/<pid>")
def thumb(pid):
    p = find(pid)
    if not p:
        abort(404)
    return send_file(p["file"])


@app.route("/src/<pid>")
def src(pid):
    p = find(pid)
    if not p:
        abort(404)
    return send_file(p["file"])


@app.route("/edit/<pid>")
def edit(pid):
    p = find(pid)
    if not p:
        abort(404)
    init = {"cx": p.get("cx"), "cy": p.get("cy"), "cw": p.get("cw")}
    bgh = os.path.basename(p["bg"]) if p.get("bg") else "none"
    return render_template_string(EDIT, pid=pid, caption=p.get("caption", ""),
                                  style=p.get("style", "card"), bghint=bgh, init=json.dumps(init))


@app.route("/api/panel_preview/<pid>")
def panel_preview(pid):
    p = find(pid)
    if not p:
        abort(404)
    im = Image.open(p["file"])
    jpg = compose(im,
                  request.args.get("cap", p.get("caption", "")),
                  request.args.get("cx", type=float),
                  request.args.get("cy", type=float),
                  request.args.get("cw", type=float),
                  request.args.get("style", p.get("style", "card")),
                  p.get("bg"))
    return send_file(io.BytesIO(jpg), mimetype="image/jpeg")


@app.route("/api/upload", methods=["POST"])
def api_upload():
    files = request.files.getlist("files")
    if not files:
        return jsonify(ok=False, msg="no file"), 400
    panels = []                       # uploading replaces the current set
    for fs in files:
        ext = os.path.splitext(fs.filename)[1].lower() or ".jpg"
        pid = str(uuid.uuid4())
        path = os.path.join(UP, pid + ext)
        fs.save(path)
        try:
            Image.open(path).verify()
        except Exception:
            os.remove(path)
            continue
        panels.append({"id": pid, "name": fs.filename, "file": path, "caption": "",
                       "cx": None, "cy": None, "cw": None, "style": "card"})
    if not panels:
        return jsonify(ok=False, msg="unsupported image"), 400
    save(panels)
    return jsonify(ok=True, id=panels[0]["id"], count=len(panels))


@app.route("/api/setbg", methods=["POST"])
def api_setbg():
    pid = request.args.get("id", "")
    fs = (request.files.getlist("file") or [None])[0]
    if not fs:
        return jsonify(ok=False, msg="no file"), 400
    ext = os.path.splitext(fs.filename)[1].lower() or ".jpg"
    path = os.path.join(UP, "bg-" + pid + ext)
    fs.save(path)
    try:
        Image.open(path).verify()
    except Exception:
        os.remove(path)
        return jsonify(ok=False, msg="unsupported image"), 400
    panels = load()
    for p in panels:
        if p["id"] == pid:
            p["bg"] = path
    save(panels)
    return jsonify(ok=True, msg="background: " + os.path.basename(path))


@app.route("/api/crop", methods=["POST"])
def api_crop():
    d = request.get_json(force=True)
    panels = load()
    for p in panels:
        if p["id"] == d["id"]:
            p["cx"], p["cy"], p["cw"] = float(d["cx"]), float(d["cy"]), float(d["cw"])
            p["caption"] = d.get("caption", "")
            p["style"] = d.get("style", p.get("style", "card"))
    save(panels)
    push(panels)
    apply_now()
    return jsonify(msg="pushed (the screen blanks for a second)")


@app.route("/api/restart", methods=["POST"])
def api_restart():
    push(load())
    apply_now()
    return jsonify(msg="re-pushed")


@app.route("/api/setdefault", methods=["POST"])
def api_setdefault():
    cur = load()
    if not cur:
        return jsonify(msg="nothing to save"), 400
    json.dump(cur, open(DEFAULTS, "w"), ensure_ascii=False, indent=2)
    return jsonify(msg=f"{len(cur)} panel(s) saved as default")


@app.route("/api/reset", methods=["POST"])
def api_reset():
    d = current_defaults()
    if not d:
        return jsonify(msg="no default saved yet"), 400
    save(d)
    push(d)
    apply_now()
    return jsonify(msg="restored default")


@app.route("/api/del", methods=["POST"])
def api_del():
    pid = request.args.get("id", "")
    panels = [p for p in load() if p["id"] != pid]
    save(panels)
    if panels:
        push(panels)
        apply_now()
    return jsonify(msg="deleted")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("GEM12_PORT", "5124")))
