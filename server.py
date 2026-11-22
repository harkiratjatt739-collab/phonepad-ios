"""
PhonePad - use your phone as an Xbox 360 controller (with gyro aiming) on Windows.

Run:  start.bat   (or: py server.py)
Then scan the QR code in the console with your phone (same Wi-Fi).
"""
import asyncio
import datetime
import ipaddress
import json
import secrets
import socket
import ssl
import sys
from pathlib import Path

from aiohttp import web, WSMsgType
import vgamepad as vg

PORT = 8443
HERE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CERT, KEY, CERT_IP, TOKEN_FILE = (HERE / n for n in ("cert.pem", "key.pem", "cert.ip", "token.txt"))

BTN = {
    "A": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
    "B": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
    "X": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
    "Y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
    "LB": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
    "RB": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
    "START": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
    "BACK": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
    "GUIDE": vg.XUSB_BUTTON.XUSB_GAMEPAD_GUIDE,
    "L3": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
    "R3": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
    "UP": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
    "DOWN": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
    "LEFT": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
    "RIGHT": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
}

pad = vg.VX360Gamepad()
held = set()
clients = set()
loop = None


def clamp(v, lo=-1.0, hi=1.0):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(lo, min(hi, v))


def apply_state(m):
    want = {n for n in m.get("b", []) if n in BTN}
    for n in want - held:
        pad.press_button(button=BTN[n])
    for n in held - want:
        pad.release_button(button=BTN[n])
    held.clear()
    held.update(want)
    pad.left_joystick_float(x_value_float=clamp(m.get("lx")), y_value_float=clamp(m.get("ly")))
    pad.right_joystick_float(x_value_float=clamp(m.get("rx")), y_value_float=clamp(m.get("ry")))
    pad.left_trigger_float(value_float=clamp(m.get("lt"), 0, 1))
    pad.right_trigger_float(value_float=clamp(m.get("rt"), 0, 1))
    pad.update()


def release_all():
    apply_state({})


# Game rumble -> phone vibration
async def _send_rumble(large, small):
    msg = json.dumps({"t": "r", "l": large, "s": small})
    for ws in list(clients):
        try:
            await ws.send_str(msg)
        except Exception:
            pass


def on_rumble(client, target, large, small, led, user_data):
    if loop:
        asyncio.run_coroutine_threadsafe(_send_rumble(int(large), int(small)), loop)


try:
    pad.register_notification(callback_function=on_rumble)
except Exception:
    pass


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no packets are sent
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def ensure_cert(ip):
    if CERT.exists() and KEY.exists() and CERT_IP.exists() and CERT_IP.read_text().strip() == ip:
        return
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PhonePad")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=800))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address(ip))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    KEY.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    CERT_IP.write_text(ip)


def get_token():
    if TOKEN_FILE.exists():
        t = TOKEN_FILE.read_text().strip()
        if t:
            return t
    t = secrets.token_urlsafe(9)
    TOKEN_FILE.write_text(t)
    return t


TOKEN = get_token()


async def index(request):
    if request.query.get("k") != TOKEN:
        return web.Response(status=403, text="Scan the QR code shown on your PC.")
    return web.Response(text=PAGE, content_type="text/html")


async def ws_handler(request):
    if request.query.get("k") != TOKEN:
        return web.Response(status=403)
    ws = web.WebSocketResponse(heartbeat=10)
    await ws.prepare(request)
    clients.add(ws)
    print("Phone connected:", request.remote)
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    m = json.loads(msg.data)
                    if isinstance(m, dict):
                        apply_state(m)
                except (ValueError, TypeError):
                    pass
    finally:
        clients.discard(ws)
        if not clients:
            release_all()
        print("Phone disconnected")
    return ws


async def main():
    global loop
    loop = asyncio.get_running_loop()
    ip = local_ip()
    ensure_cert(ip)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)

    app = web.Application()
    app.add_routes([web.get("/", index), web.get("/ws", ws_handler)])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT, ssl_context=ctx).start()

    url = f"https://{ip}:{PORT}/?k={TOKEN}"
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii(invert=True)
    except Exception:
        pass
    print("\nOpen this on your phone (same Wi-Fi):\n  " + url)
    print("\nFirst time: your browser will warn about the certificate.")
    print("Tap Advanced -> Continue (it's your own PC). Ctrl+C to quit.\n")
    await asyncio.Event().wait()


PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>PhonePad</title>
<style>
:root{--bg:#14171c;--panel:#222831;--edge:#323a46;--ink:#e7ebf0;--dim:#7d8794;--a:#4fb36a;--b:#e5534b;--x:#4c8dff;--y:#f0b429;--gyro:#3dd6d0}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent;user-select:none;-webkit-user-select:none;touch-action:none}
html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font:600 13px system-ui,sans-serif;overflow:hidden;overscroll-behavior:none}
#pad{position:fixed;inset:0}
#pad>*{position:absolute}
.btn{background:var(--panel);border:2px solid var(--edge);border-radius:12px;display:grid;place-items:center;color:var(--ink)}
.btn.on{background:#3a4452;border-color:var(--ink)}
.sh{width:15%;height:15vh;top:3vh}
#LT{left:4%}#LB{left:20%}#RB{right:20%}#RT{right:4%}
.stick{border-radius:50%;background:radial-gradient(#2b323c,#1b2027);border:2px solid var(--edge);display:grid;place-items:center}
.knob{width:46%;height:46%;border-radius:50%;background:#4a5566;border:2px solid #667286;pointer-events:none}
#ls{left:5%;top:24vh;width:38vh;height:38vh}
#rs{right:28%;top:52vh;width:36vh;height:36vh}
#dpad{left:27%;top:54vh;width:32vh;height:32vh;display:grid;grid:1fr 1fr 1fr/1fr 1fr 1fr}
#dpad i{background:var(--panel);border:2px solid var(--edge);display:block}
#dpad i.on{background:var(--ink)}
#dpad .u{grid-area:1/2}#dpad .l{grid-area:2/1}#dpad .r{grid-area:2/3}#dpad .d{grid-area:3/2}#dpad .c{grid-area:2/2}
#face{right:5%;top:22vh;width:38vh;height:38vh}
#face .btn{position:absolute;width:42%;height:42%;border-radius:50%;font-size:18px;color:#101318;border:0}
#face .btn.on{filter:brightness(1.5);outline:3px solid var(--ink)}
#Y{left:29%;top:0;background:var(--y)}#X{left:0;top:29%;background:var(--x)}
#B{right:0;top:29%;background:var(--b)}#A{left:29%;bottom:0;background:var(--a)}
.sm{width:9vh;height:9vh;border-radius:50%;font-size:11px;color:var(--dim)}
#L3{left:6%;top:68vh}#R3{right:6%;top:68vh}
#mid{left:50%;top:4vh;transform:translateX(-50%);display:flex;gap:10px;align-items:center}
#mid .btn{height:8vh;min-height:30px;padding:0 14px;border-radius:99px}
#ctl{left:50%;top:28vh;transform:translateX(-50%);display:flex;flex-direction:column;gap:10px;align-items:center}
#ctl .btn{height:10vh;min-height:34px;padding:0 20px;border-radius:99px}
#gy.live{background:var(--gyro);color:#06201f;border-color:var(--gyro)}
#dot{left:50%;top:1.2vh;width:8px;height:8px;border-radius:50%;background:#e5534b;transform:translateX(-50%)}
#dot.ok{background:#4fb36a}
.ov{position:fixed;inset:0;background:rgba(10,12,15,.96);display:none;place-items:center;text-align:center;padding:24px;z-index:9;touch-action:auto}
.ov.show{display:grid}
.ov h1{margin:0 0 8px;font-size:22px}.ov p{color:var(--dim);margin:0 0 16px}
.go{background:var(--gyro);color:#06201f;border:0;font:700 16px system-ui;padding:14px 32px;border-radius:99px}
#set .box{background:var(--panel);border:2px solid var(--edge);border-radius:16px;padding:16px 20px;width:min(520px,92vw);text-align:left;max-height:94vh;overflow:auto}
#set label{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:7px 0;font-weight:600}
#set select,#set input[type=range]{width:55%;font:inherit}
#set input[type=checkbox]{width:22px;height:22px}
#rot{z-index:8}
@media (orientation:portrait){#rot{display:grid}}
</style></head><body>
<div id="pad">
  <div class="btn sh" id="LT" data-b="LT">LT</div><div class="btn sh" id="LB" data-b="LB">LB</div>
  <div class="btn sh" id="RB" data-b="RB">RB</div><div class="btn sh" id="RT" data-b="RT">RT</div>
  <div class="stick" id="ls"><div class="knob"></div></div>
  <div class="btn sm" id="L3" data-b="L3">L3</div>
  <div id="dpad"><i class="u"></i><i class="l"></i><i class="c"></i><i class="r"></i><i class="d"></i></div>
  <div id="mid"><div class="btn" data-b="BACK">Back</div><div class="btn" data-b="GUIDE">Guide</div><div class="btn" data-b="START">Start</div></div>
  <div id="ctl"><div class="btn" id="gy">Gyro off</div><div class="btn" id="ctr">Center</div><div class="btn" id="gear">Settings</div></div>
  <div class="stick" id="rs"><div class="knob"></div></div>
  <div class="btn sm" id="R3" data-b="R3">R3</div>
  <div id="face">
    <div class="btn" id="Y" data-b="Y">Y</div><div class="btn" id="X" data-b="X">X</div>
    <div class="btn" id="B" data-b="B">B</div><div class="btn" id="A" data-b="A">A</div>
  </div>
  <div id="dot"></div>
</div>

<div class="ov show" id="start"><div>
  <h1>PhonePad</h1><p>Hold your phone sideways. Tapping start turns on full screen and motion sensors.</p>
  <button class="go" id="go">Start</button>
</div></div>

<div class="ov" id="rot"><div><h1>Rotate your phone</h1><p>PhonePad works in landscape.</p></div></div>

<div class="ov" id="set"><div class="box">
  <label>Gyro mode<select id="mode"><option value="steer">Steering (tilt like a wheel)</option><option value="aim">Aim camera (right stick)</option><option value="off">Off</option></select></label>
  <label>Gyro active<select id="gate"><option value="always">Always</option><option value="LT">While holding LT</option><option value="RT">While holding RT</option><option value="LB">While holding LB</option><option value="RB">While holding RB</option></select></label>
  <label>Horizontal aim from<select id="hAxis"><option value="beta">Turning (yaw)</option><option value="alpha">Twisting (roll)</option></select></label>
  <label>Sensitivity <input type="range" id="sens" min="0.2" max="4" step="0.1"></label>
  <label>Invert horizontal <input type="checkbox" id="invX"></label>
  <label>Invert vertical <input type="checkbox" id="invY"></label>
  <label>Vibration <input type="checkbox" id="haptics"></label>
  <div style="text-align:center;margin-top:12px"><button class="go" id="close">Done</button> <button class="go" id="chg" style="display:none;background:#e5534b;color:#fff">Change PC</button></div>
</div></div>

<script>
const $=s=>document.querySelector(s);
const key=new URLSearchParams(location.search).get('k')||'';
let cfg={mode:'aim',gate:'always',hAxis:'beta',sens:1,invX:false,invY:false,haptics:true};
try{Object.assign(cfg,JSON.parse(localStorage.getItem('pp')||'{}'))}catch(e){}
const save=()=>{try{localStorage.setItem('pp',JSON.stringify(cfg))}catch(e){}};
const NATIVE=!!(window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.pp);
const post=o=>window.webkit.messageHandlers.pp.postMessage(o);
const buzz=(n=25)=>{if(!cfg.haptics)return;if(NATIVE)post({t:'tap'});else if(navigator.vibrate)navigator.vibrate(n)};

const down=new Set(), S={lx:0,ly:0,rx:0,ry:0}, G={alpha:0,beta:0,gamma:0};
let gyroOn=false;

// Buttons
document.querySelectorAll('[data-b]').forEach(el=>{
  const n=el.dataset.b;
  el.addEventListener('pointerdown',e=>{e.preventDefault();el.setPointerCapture(e.pointerId);down.add(n);el.classList.add('on');buzz()});
  const up=()=>{down.delete(n);el.classList.remove('on')};
  ['pointerup','pointercancel','lostpointercapture'].forEach(t=>el.addEventListener(t,up));
});

// Sticks
function stick(el,cb){
  let id=null;const knob=el.firstElementChild;
  const move=e=>{
    const r=el.getBoundingClientRect(),R=r.width/2;
    let dx=(e.clientX-r.left-R)/R,dy=(e.clientY-r.top-R)/R;const m=Math.hypot(dx,dy);
    if(m>1){dx/=m;dy/=m}
    knob.style.transform=`translate(${dx*R*.55}px,${dy*R*.55}px)`;cb(dx,-dy);
  };
  el.addEventListener('pointerdown',e=>{e.preventDefault();id=e.pointerId;el.setPointerCapture(id);move(e)});
  el.addEventListener('pointermove',e=>{if(e.pointerId===id)move(e)});
  const end=e=>{if(e.pointerId!==id)return;id=null;knob.style.transform='';cb(0,0)};
  el.addEventListener('pointerup',end);el.addEventListener('pointercancel',end);
}
stick($('#ls'),(x,y)=>{S.lx=x;S.ly=y});
stick($('#rs'),(x,y)=>{S.rx=x;S.ry=y});

// D-pad (8-way, slide across)
(()=>{
  const el=$('#dpad');let id=null;
  const arms={UP:el.querySelector('.u'),DOWN:el.querySelector('.d'),LEFT:el.querySelector('.l'),RIGHT:el.querySelector('.r')};
  const set=(on)=>{for(const k in arms){on.has(k)?down.add(k):down.delete(k);arms[k].classList.toggle('on',on.has(k))}};
  const move=e=>{
    const r=el.getBoundingClientRect(),R=r.width/2;
    const dx=(e.clientX-r.left-R)/R,dy=(r.top+R-e.clientY)/R,m=Math.hypot(dx,dy),on=new Set();
    if(m>.2){const s=dy/m,c=dx/m;if(s>.38)on.add('UP');if(s<-.38)on.add('DOWN');if(c>.38)on.add('RIGHT');if(c<-.38)on.add('LEFT')}
    set(on);
  };
  el.addEventListener('pointerdown',e=>{e.preventDefault();id=e.pointerId;el.setPointerCapture(id);buzz();move(e)});
  el.addEventListener('pointermove',e=>{if(e.pointerId===id)move(e)});
  const end=e=>{if(e.pointerId===id){id=null;set(new Set())}};
  el.addEventListener('pointerup',end);el.addEventListener('pointercancel',end);
})();

// Gyro
addEventListener('devicemotion',e=>{
  if(NATIVE)return;const r=e.rotationRate;if(!r)return;
  G.alpha=r.alpha||0;G.beta=r.beta||0;G.gamma=r.gamma||0;
});
const IOS=/iPhone|iPad|iPod/.test(navigator.userAgent);
let AC={x:0,y:0,z:0},steerZero=0;
window.nativeMotion=(a,b,g,x,y,z)=>{G.alpha=a;G.beta=b;G.gamma=g;AC.x=x;AC.y=y;AC.z=z};
addEventListener('devicemotion',e=>{
  if(NATIVE)return;const a=e.accelerationIncludingGravity;if(!a)return;
  const k=IOS?-1:1;AC.x=(a.x||0)*k;AC.y=(a.y||0)*k;AC.z=(a.z||0)*k;
});
const angleSign=()=>{
  const a=(screen.orientation&&screen.orientation.angle!=null)?screen.orientation.angle:(window.orientation||0);
  return (a===270||a===-90)?-1:1;
};
const dz=v=>{const a=Math.abs(v);return a<1.5?0:Math.sign(v)*(a-1.5)*cfg.sens/90};
const cl=v=>Math.max(-1,Math.min(1,v));
const r3=v=>Math.round(v*1000)/1000;
function steerRaw(){
  const n=Math.hypot(AC.x,AC.y,AC.z)||1;
  return Math.asin(Math.max(-1,Math.min(1,AC.y*angleSign()/n)))*180/Math.PI;
}
function gyroActive(){
  if(!gyroOn||cfg.mode==='off')return false;
  return cfg.gate==='always'||down.has(cfg.gate);
}
function build(){
  let rx=S.rx,ry=S.ry,lx=S.lx;
  if(gyroActive()){
    const s=angleSign();
    if(cfg.mode==='aim'){
      rx+=dz(-s*G[cfg.hAxis])*(cfg.invX?-1:1);
      ry+=dz(-s*G.gamma)*(cfg.invY?-1:1);
    }else{
      // steering: tilt the phone like a wheel (angle from gravity)
      let deg=steerRaw()-steerZero;
      if(Math.abs(deg)<3)deg=0;else deg-=Math.sign(deg)*3;
      lx+=cl(deg/(45/cfg.sens))*(cfg.invX?-1:1);
    }
  }
  return {b:[...down].filter(n=>n!=='LT'&&n!=='RT'),lx:r3(cl(lx)),ly:r3(S.ly),rx:r3(cl(rx)),ry:r3(cl(ry)),lt:down.has('LT')?1:0,rt:down.has('RT')?1:0};
}

// Network
let ws=null,last='',nativeOk=false;
window.nativeStatus=ok=>{nativeOk=ok;last='';$('#dot').classList.toggle('ok',ok)};
window.nativeRumble=(l,s)=>{if(cfg.haptics)post({t:'rumble',l:l,s:s})};
function connect(){
  if(NATIVE){post({t:'connect'});return}
  ws=new WebSocket(`wss://${location.host}/ws?k=${encodeURIComponent(key)}`);
  ws.onopen=()=>{$('#dot').classList.add('ok');last=''};
  ws.onclose=()=>{$('#dot').classList.remove('ok');setTimeout(connect,1000)};
  ws.onmessage=e=>{
    try{const m=JSON.parse(e.data);if(m.t==='r'&&cfg.haptics&&navigator.vibrate&&(m.l>10||m.s>10))navigator.vibrate(Math.min(120,40+Math.max(m.l,m.s)/3))}catch(_){}
  };
}
setInterval(()=>{
  const m=JSON.stringify(build());
  if(m!==last){if(NATIVE){if(nativeOk){post({t:'send',d:m});last=m}}else if(ws&&ws.readyState===1){ws.send(m);last=m}}
  const g=$('#gy');g.classList.toggle('live',gyroActive());
  g.textContent=!gyroOn||cfg.mode==='off'?'Gyro off':(gyroActive()?(cfg.mode==='steer'?'Gyro steering':'Gyro aiming'):'Gyro ready');
},8);
document.addEventListener('visibilitychange',()=>{if(document.hidden){down.clear();S.lx=S.ly=S.rx=S.ry=0}});

// Start / permissions
$('#go').onclick=async()=>{
  try{if(NATIVE)gyroOn=true;else if(typeof DeviceMotionEvent!=='undefined'&&DeviceMotionEvent.requestPermission){gyroOn=(await DeviceMotionEvent.requestPermission())==='granted'}else gyroOn=true}catch(e){gyroOn=false}
  try{await document.documentElement.requestFullscreen()}catch(e){}
  try{await screen.orientation.lock('landscape')}catch(e){}
  try{await navigator.wakeLock.request('screen')}catch(e){}
  $('#start').classList.remove('show');
  connect();
};
$('#ctr').addEventListener('pointerdown',()=>{steerZero=steerRaw();buzz(40)});
$('#gy').addEventListener('pointerdown',()=>{gyroOn=!gyroOn;if(gyroOn&&cfg.mode==='off'){cfg.mode='aim';save()}});

// Settings
const ids=['mode','gate','hAxis','sens','invX','invY','haptics'];
function fill(){ids.forEach(i=>{const el=$('#'+i);if(el.type==='checkbox')el.checked=cfg[i];else el.value=cfg[i]})}
ids.forEach(i=>{const el=$('#'+i);el.addEventListener('input',()=>{cfg[i]=el.type==='checkbox'?el.checked:(i==='sens'?parseFloat(el.value):el.value);save()})});
$('#gear').addEventListener('pointerdown',()=>{fill();$('#set').classList.add('show')});
$('#close').onclick=()=>$('#set').classList.remove('show');
if(NATIVE){$('#chg').style.display='inline-block';$('#chg').onclick=()=>post({t:'reset'})}
</script></body></html>
"""

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        release_all()
