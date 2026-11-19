#!/usr/bin/env python3
"""Jarvis web chat — a small browser UI for the same router the phone uses.

Listens on the WireGuard address (10.66.0.1) and localhost only, so only your phone and
laptop on the private network can reach it; nothing is exposed to the internet. A token
(printed on first run, kept in ~/.local/state/jarvis/web-token) is required for every reply.

Reuses jarvis.py: same brains (f/d/q/c), same per-brain memory, the same "no prefix continues
your last model" stickiness, and the same chat history files as the phone. Local replies stream
token by token. Stdlib only. Runs as the systemd user service jarvis-web.
"""
import hmac, json, os, socket, sys, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import jarvis                                          # the router: brains, history, sticky, Claude

STATE = jarvis.STATE
PORT = int(jarvis.CONF.get("JARVIS_WEB_PORT", "8088"))
WG_IP = jarvis.CONF.get("JARVIS_WG_IP", "10.66.0.1")   # the private-network address to serve on
TOKEN_FILE = STATE / "web-token"
# Visible chat log the web page shows on every visit (separate from the model's short working
# memory). Kept for CHAT_DAYS days, then each old turn is pruned automatically.
TRANSCRIPT = STATE / "web-chat.json"
CHAT_DAYS = int(jarvis.CONF.get("JARVIS_CHAT_DAYS", "45"))
_tlock = __import__("threading").Lock()


def load_transcript():
    try: turns = json.loads(TRANSCRIPT.read_text()).get("turns", [])
    except Exception: turns = []
    cutoff = time.time() - CHAT_DAYS * 86400
    kept = [t for t in turns if t.get("at", 0) >= cutoff]
    if len(kept) != len(turns):
        try: TRANSCRIPT.write_text(json.dumps({"turns": kept}))
        except Exception: pass
    return kept


def add_turn(role, content, brain):
    with _tlock:
        turns = load_transcript()
        turns.append({"role": role, "content": content, "brain": brain, "at": int(time.time())})
        try: TRANSCRIPT.write_text(json.dumps({"turns": turns}))
        except Exception: pass


def token():
    if not TOKEN_FILE.exists():
        import base64
        TOKEN_FILE.write_text(base64.urlsafe_b64encode(os.urandom(18)).decode().rstrip("="))
        TOKEN_FILE.chmod(0o600)
    return TOKEN_FILE.read_text().strip()


# ---------- streaming a local brain (mirrors jarvis.ask_local, but yields tokens) ----------
def stream_local(b, text):
    jarvis.ensure_local(b)
    h = jarvis.load(b).get("messages", [])
    h.append({"role": "user", "content": text})
    body = json.dumps({"model": jarvis.LOCAL[b]["name"], "stream": True, "temperature": 0.7,
                       "messages": [{"role": "system", "content": jarvis.SYSTEM}] + h[-jarvis.MAX_HISTORY:]}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{jarvis.LOCAL[b]['port']}/v1/chat/completions",
                                 data=body, headers={"Content-Type": "application/json",
                                                     "Authorization": f"Bearer {jarvis.api_key()}"})
    reply = ""
    with urllib.request.urlopen(req, timeout=600) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                piece = json.loads(data)["choices"][0]["delta"].get("content", "")
            except Exception:
                continue
            if piece:
                reply += piece
                yield piece
    h.append({"role": "assistant", "content": reply})
    jarvis.save(b, {"messages": h[-jarvis.MAX_HISTORY:]})


def pick_brain(text, chosen):
    """Return (brain, message). `chosen` is '', 'auto', or a brain letter from the UI."""
    s = text.strip()
    if len(s) > 2 and s[1] == ":" and s[0].lower() in jarvis.BRAINS:    # explicit prefix wins
        return s[0].lower(), s[2:].strip()
    if chosen in jarvis.BRAINS:
        return chosen, s
    return (jarvis.last_brain() or jarvis.DEFAULT), s                   # auto = continue last


PAGE = r"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Jarvis</title>
<style>
:root{--bg:#f6f7f9;--fg:#111;--mut:#667;--card:#fff;--line:#e3e6ea;--me:#dcf3e4;--accent:#1a7f4b}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--fg:#e8eaed;--mut:#9aa3ad;--card:#1a1d23;--line:#2a2f37;--me:#1f3a2b;--accent:#4ad48a}}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;display:flex;flex-direction:column}
header{padding:10px 16px;border-bottom:1px solid var(--line);display:flex;gap:10px;align-items:center;flex-wrap:wrap}
header b{font-size:18px}select,button{font:inherit;color:var(--fg);background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 10px}
#log{flex:1;overflow:auto;padding:16px;max-width:820px;width:100%;margin:0 auto}
.msg{margin:10px 0;display:flex}.msg.me{justify-content:flex-end}
.bub{max-width:85%;padding:9px 13px;border-radius:14px;background:var(--card);border:1px solid var(--line);white-space:pre-wrap;word-wrap:break-word}
.me .bub{background:var(--me)}.who{font-size:12px;color:var(--mut);margin:0 4px 2px}
form{display:flex;gap:8px;padding:12px 16px;border-top:1px solid var(--line);max-width:820px;width:100%;margin:0 auto}
#t{flex:1;font:inherit;color:var(--fg);background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;resize:none}
#send{background:var(--accent);color:#fff;border:none;padding:0 16px;font-weight:600}
#send:disabled{opacity:.5}.hint{color:var(--mut);font-size:13px}
.gate{margin:auto;max-width:360px;text-align:center;padding:24px}
</style></head><body>
<header><b>Jarvis</b>
<select id=brain title="which model">
<option value=auto>Auto (last used)</option><option value=f>Fast</option>
<option value=d>Dolphin</option><option value=q>Qwen</option><option value=c>Claude</option></select>
<button id=new type=button title="delete this chat history now">Clear</button><span class=hint id=stat></span></header>
<div id=log></div>
<form id=f><textarea id=t rows=1 placeholder="Message Jarvis…  (prefix f: d: q: c: to pick a model)" autofocus></textarea><button id=send>Send</button></form>
<script>
const $=s=>document.querySelector(s),log=$('#log');
let tok=localStorage.getItem('jtok')||'';
function gate(){log.innerHTML='<div class=gate><p>Enter the Jarvis access token.</p>'+
 '<input id=tk type=password style="width:100%;padding:10px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg)">'+
 '<p><button onclick="save()">Unlock</button></p></div>';}
window.save=()=>{tok=$('#tk').value.trim();localStorage.setItem('jtok',tok);log.innerHTML='';loadHistory();};
function add(who,cls){const d=document.createElement('div');d.className='msg '+cls;
 d.innerHTML='<div><div class=who></div><div class=bub></div></div>';
 d.querySelector('.who').textContent=who;log.appendChild(d);log.scrollTop=log.scrollHeight;return d.querySelector('.bub');}
function loadHistory(){fetch('api/history',{headers:{Authorization:'Bearer '+tok}})
 .then(r=>{if(r.status===401){gate();return null;}return r.json();})
 .then(d=>{if(!d)return;log.innerHTML='';for(const t of d.turns){
   add(t.role==='user'?'you':'Jarvis · '+t.brain, t.role==='user'?'me':'').textContent=t.content;}
  $('#stat').textContent=d.turns.length?('kept '+d.days+' days'):'';log.scrollTop=log.scrollHeight;})
 .catch(()=>{});}
const t=$('#t');t.addEventListener('input',()=>{t.style.height='auto';t.style.height=Math.min(t.scrollHeight,160)+'px';});
t.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();$('#f').requestSubmit();}});
$('#new').onclick=async()=>{if(!confirm('Delete this chat history now?'))return;
 await fetch('api/reset',{method:'POST',headers:{Authorization:'Bearer '+tok}});log.innerHTML='';$('#stat').textContent='';};
$('#f').onsubmit=async e=>{e.preventDefault();const msg=t.value.trim();if(!msg)return;
 t.value='';t.style.height='auto';add('you','me').textContent=msg;
 $('#send').disabled=true;$('#stat').textContent='…';
 const bub=add('Jarvis','');
 try{
  const r=await fetch('api/chat',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+tok},
    body:JSON.stringify({text:msg,brain:$('#brain').value})});
  if(r.status===401){gate();return;}
  const rd=r.body.getReader(),dec=new TextDecoder();let buf='',meta=null;
  while(true){const{done,value}=await rd.read();if(done)break;buf+=dec.decode(value,{stream:true});
   if(meta===null){const i=buf.indexOf('\n');if(i<0)continue;meta=JSON.parse(buf.slice(0,i));buf=buf.slice(i+1);
    bub.parentNode.querySelector('.who').textContent='Jarvis · '+meta.brain;}
   bub.textContent=buf;log.scrollTop=log.scrollHeight;}
  if(meta&&meta.err)bub.textContent='⚠ '+buf;
 }catch(err){bub.textContent='⚠ '+err;}
 $('#send').disabled=false;$('#stat').textContent='';t.focus();};
if(!tok)gate();else loadHistory();
</script></body></html>"""

NAMES = {"f": "fast", "d": "dolphin", "q": "qwen", "c": "claude"}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass

    def _private(self):
        ip = self.client_address[0]
        return ip == "127.0.0.1" or ip.startswith("10.66.0.")

    def _auth(self):
        got = self.headers.get("Authorization", "")[7:] if self.headers.get("Authorization", "").startswith("Bearer ") else ""
        return hmac.compare_digest(got, token())

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if not self._private(): self.send_error(403); return
        path = self.path.split("?")[0]
        if path == "/api/history":                          # past messages, to render on page load
            if not self._auth(): self.send_error(401); return
            self._json({"turns": load_transcript(), "days": CHAT_DAYS}); return
        if path != "/":
            self.send_error(404); return
        body = PAGE.encode()
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        if not self._private(): self.send_error(403); return
        if not self._auth(): self.send_error(401); return
        path = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(n) or b"{}") if n else {}
        if path == "/api/reset":
            jarvis.reset("all")                             # forget model memory
            try: TRANSCRIPT.unlink(missing_ok=True)         # and clear the visible log
            except Exception: pass
            self.send_response(204); self.end_headers(); return
        if path != "/api/chat":
            self.send_error(404); return

        brain, msg = pick_brain(data.get("text", ""), data.get("brain", "auto"))
        jarvis.set_last(brain)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Transfer-Encoding", "chunked")   # stream a body of unknown length
        self.end_headers()

        def chunk(s):                                       # one HTTP chunk; flush so it arrives now
            b = s.encode() if isinstance(s, str) else s
            if not b: return
            self.wfile.write(f"{len(b):X}\r\n".encode() + b + b"\r\n"); self.wfile.flush()

        chunk(json.dumps({"brain": NAMES[brain]}) + "\n")   # first line = metadata
        add_turn("user", msg, NAMES[brain])
        full = ""
        try:
            if brain in ("f", "d"):                         # stream token by token
                for piece in stream_local(brain, msg):
                    full += piece; chunk(piece)
            else:                                           # qwen (strip reasoning) / claude: whole
                full = jarvis.ask_claude(msg) if brain == "c" else jarvis.ask_local(brain, msg)
                chunk(full)
        except Exception as e:
            full = f"[error] {e}"
            try: chunk("\n" + full)
            except Exception: pass
        add_turn("assistant", full, NAMES[brain])           # persist the reply for next visit
        try: self.wfile.write(b"0\r\n\r\n"); self.wfile.flush()   # terminating chunk
        except Exception: pass


def serve(host):
    for _ in range(60):                                  # wg0 may come up after this service at boot
        try:
            srv = ThreadingHTTPServer((host, PORT), H); break
        except OSError:
            time.sleep(2)
    else:
        return
    srv.serve_forever()


if __name__ == "__main__":
    tk = token()
    hosts = ["127.0.0.1"]
    try:
        socket.inet_aton(WG_IP); hosts.append(WG_IP)
    except OSError:
        pass
    print(f"Jarvis web on http://{WG_IP}:{PORT}  (token in {TOKEN_FILE})", flush=True)
    threads = [threading.Thread(target=serve, args=(h,), daemon=True) for h in hosts]
    for t in threads: t.start()
    for t in threads: t.join()
