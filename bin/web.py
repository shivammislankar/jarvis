#!/usr/bin/env python3
"""Jarvis web chat — a ChatGPT-style browser UI for the same models the phone uses.

Private network only: binds to the WireGuard address (10.66.0.1) and localhost, token-protected,
and refuses any client not on the private network. Nothing is exposed to the internet.

Unlike the phone (one continuous thread), the web UI keeps SEPARATE conversations, each with its
own memory — create, switch, rename, delete, like ChatGPT/Claude. Each conversation is a file in
~/.local/state/jarvis/web-chats/; one unused for CHAT_DAYS days (default 45) is auto-deleted.
Local replies stream token by token. Stdlib only. systemd user service jarvis-web.
"""
import base64, hmac, json, os, re, secrets, shutil, socket, subprocess, sys, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import jarvis                                          # the router: brains, Claude, SYSTEM, DEFAULT
import memo                                            # notes / reminders / to-dos / events (same dir)

STATE = jarvis.STATE
PORT = int(jarvis.CONF.get("JARVIS_WEB_PORT", "8088"))
WG_IP = jarvis.CONF.get("JARVIS_WG_IP", "10.66.0.1")
TOKEN_FILE = STATE / "web-token"
CHATS = STATE / "web-chats"
CHAT_DAYS = int(jarvis.CONF.get("JARVIS_CHAT_DAYS", "45"))
MAX_CTX = jarvis.MAX_HISTORY                            # messages of a conversation sent as context
NAMES = {"f": "fast", "d": "dolphin", "q": "qwen", "c": "claude"}
LETTER = {v: k for k, v in NAMES.items()}
LOCK = threading.Lock()


def token():
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(base64.urlsafe_b64encode(os.urandom(18)).decode().rstrip("="))
        TOKEN_FILE.chmod(0o600)
    return TOKEN_FILE.read_text().strip()


# ---------- conversation storage ----------
def valid_id(cid):
    return isinstance(cid, str) and re.fullmatch(r"[0-9a-f]{8,32}", cid)

def cpath(cid):
    return CHATS / f"{cid}.json"

def load_chat(cid):
    if not valid_id(cid): return None
    try: return json.loads(cpath(cid).read_text())
    except Exception: return None

def save_chat(c):
    CHATS.mkdir(parents=True, exist_ok=True)
    tmp = cpath(c["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(c)); tmp.replace(cpath(c["id"]))

def title_from(text):
    t = re.sub(r"\s+", " ", text).strip()
    return (t[:40] + "…") if len(t) > 40 else (t or "New chat")

def list_chats():
    """Prune conversations idle > CHAT_DAYS, return the rest newest-first (for the sidebar)."""
    CHATS.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - CHAT_DAYS * 86400
    out = []
    for f in CHATS.glob("*.json"):
        try: c = json.loads(f.read_text())
        except Exception: continue
        # last interaction = the later of last message (updated) and last opened (seen)
        if max(c.get("updated", 0), c.get("seen", 0)) < cutoff:
            try: f.unlink()
            except Exception: pass
            continue
        out.append({"id": c["id"], "title": c.get("title", "Chat"), "updated": c.get("updated", 0)})
    out.sort(key=lambda x: x["updated"], reverse=True)
    return out

def new_chat():
    c = {"id": secrets.token_hex(8), "title": "New chat",
         "created": int(time.time()), "updated": int(time.time()), "seen": int(time.time()),
         "claude_session": None, "messages": []}
    save_chat(c)
    return c

def import_legacy():
    """One-time: turn the old single transcript (web-chat.json) into the first conversation."""
    legacy = STATE / "web-chat.json"
    CHATS.mkdir(parents=True, exist_ok=True)
    if not legacy.exists() or any(CHATS.glob("*.json")):
        return
    try: turns = json.loads(legacy.read_text()).get("turns", [])
    except Exception: turns = []
    if turns:
        msgs = [{"role": t["role"], "content": t["content"],
                 "b": LETTER.get(t.get("brain", "fast"), "f"), "at": t.get("at", int(time.time()))}
                for t in turns]
        first = next((m["content"] for m in msgs if m["role"] == "user"), "Imported chat")
        c = {"id": secrets.token_hex(8), "title": title_from(first),
             "created": msgs[0]["at"], "updated": msgs[-1]["at"],
             "claude_session": None, "messages": msgs}
        save_chat(c)
    try: legacy.rename(legacy.with_suffix(".json.imported"))
    except Exception: pass


# ---------- model calls, with per-conversation context ----------
def ctx_messages(convo):
    return ([{"role": "system", "content": jarvis.SYSTEM}] +
            [{"role": m["role"], "content": m["content"]} for m in convo["messages"][-MAX_CTX:]])

def stream_local(brain, convo):
    jarvis.ensure_local(brain)
    body = json.dumps({"model": jarvis.LOCAL[brain]["name"], "stream": True, "temperature": 0.7,
                       "messages": ctx_messages(convo)}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{jarvis.LOCAL[brain]['port']}/v1/chat/completions",
                                 data=body, headers={"Content-Type": "application/json",
                                                     "Authorization": f"Bearer {jarvis.api_key()}"})
    with urllib.request.urlopen(req, timeout=600) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"): continue
            data = line[5:].strip()
            if data == "[DONE]": break
            try: piece = json.loads(data)["choices"][0]["delta"].get("content", "")
            except Exception: continue
            if piece: yield piece

def ask_local(brain, convo):
    jarvis.ensure_local(brain)
    body = json.dumps({"model": jarvis.LOCAL[brain]["name"], "temperature": 0.7,
                       "messages": ctx_messages(convo)}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{jarvis.LOCAL[brain]['port']}/v1/chat/completions",
                                 data=body, headers={"Content-Type": "application/json",
                                                     "Authorization": f"Bearer {jarvis.api_key()}"})
    with urllib.request.urlopen(req, timeout=600) as r:
        reply = json.load(r)["choices"][0]["message"]["content"].strip()
    if brain == "q" and "</think>" in reply:
        reply = reply.split("</think>", 1)[1].strip()
    return reply

def ask_claude(text, convo):
    """Claude with memory scoped to THIS conversation via its own resumed session."""
    cwd = STATE / "claude-cwd"; cwd.mkdir(exist_ok=True)
    claude = shutil.which("claude") or str(jarvis.HOME / ".local/bin/claude")
    cmd = [claude, "-p", "--output-format", "json", "--tools", "", "--system-prompt", jarvis.SYSTEM]
    if convo.get("claude_session"): cmd += ["--resume", convo["claude_session"]]
    p = subprocess.run(cmd, input=text, cwd=cwd, capture_output=True, text=True, timeout=600)
    try: out = json.loads(p.stdout)
    except json.JSONDecodeError:
        raise RuntimeError((p.stderr or p.stdout).strip() or "claude returned nothing")
    if out.get("session_id"): convo["claude_session"] = out["session_id"]
    if out.get("is_error"): raise RuntimeError(out.get("result", "claude error"))
    return out.get("result", "").strip()


def usage_stats(days=30):
    """Aggregate the usage log for the dashboard: per-model counts, avg time, Claude usage."""
    cutoff = time.time() - days * 86400
    per = {}; total = 0; by_day = {}
    try:
        for line in open(jarvis.USAGE):
            try: r = json.loads(line)
            except Exception: continue
            if r.get("at", 0) < cutoff: continue
            b = NAMES.get(r.get("brain"), r.get("brain", "?"))
            d = per.setdefault(b, {"count": 0, "secs": 0.0})
            d["count"] += 1; d["secs"] += r.get("s", 0); total += 1
            day = time.strftime("%Y-%m-%d", time.localtime(r["at"]))
            by_day[day] = by_day.get(day, 0) + 1
    except FileNotFoundError:
        pass
    models = [{"model": b, "count": v["count"], "avg_s": round(v["secs"] / v["count"], 1) if v["count"] else 0}
              for b, v in sorted(per.items(), key=lambda kv: -kv[1]["count"])]
    last7 = [{"day": d[5:], "n": by_day.get(d, 0)} for d in
             [time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400)) for i in range(6, -1, -1)]]
    return {"days": days, "total": total, "claude": per.get("claude", {}).get("count", 0),
            "models": models, "last7": last7}


def pick_brain(text, chosen, convo):
    s = text.strip()
    if len(s) > 2 and s[1] == ":" and s[0].lower() in jarvis.BRAINS:    # prefix wins
        return s[0].lower(), s[2:].strip()
    if chosen in jarvis.BRAINS:
        return chosen, s
    for m in reversed(convo["messages"]):                              # auto = last brain in this chat
        if m["role"] == "assistant" and m.get("b") in jarvis.BRAINS:
            return m["b"], s
    return jarvis.DEFAULT, s


PAGE = r"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Jarvis</title>
<style>
:root{--bg:#f6f7f9;--fg:#111;--mut:#667;--card:#fff;--line:#e3e6ea;--me:#dcf3e4;--accent:#1a7f4b;--side:#eef0f3}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--fg:#e8eaed;--mut:#9aa3ad;--card:#1a1d23;--line:#2a2f37;--me:#1f3a2b;--accent:#4ad48a;--side:#14171c}}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;display:flex;height:100%;overflow:hidden}
#side{width:260px;background:var(--side);border-right:1px solid var(--line);display:flex;flex-direction:column;flex-shrink:0}
#side h1{font-size:16px;margin:0;padding:14px 14px 6px}
#newc{margin:8px 10px;padding:9px;border:1px solid var(--line);border-radius:9px;background:var(--card);color:var(--fg);font:inherit;cursor:pointer}
#list{flex:1;overflow:auto;padding:4px 8px}
.ci{display:flex;align-items:center;gap:6px;padding:8px 9px;border-radius:8px;cursor:pointer;color:var(--fg)}
.ci:hover{background:var(--card)}.ci.on{background:var(--card);border:1px solid var(--line)}
.ci .ti{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:14px}
.ci .x{opacity:0;color:var(--mut);padding:0 4px}.ci:hover .x{opacity:1}
#main{flex:1;display:flex;flex-direction:column;min-width:0}
header{padding:9px 14px;border-bottom:1px solid var(--line);display:flex;gap:10px;align-items:center}
#burger{display:none;background:none;border:none;color:var(--fg);font-size:20px}
select{font:inherit;color:var(--fg);background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 10px}
#log{flex:1;overflow:auto;padding:16px}.wrap{max-width:820px;margin:0 auto}
.msg{margin:10px 0;display:flex}.msg.me{justify-content:flex-end}
.bub{max-width:85%;padding:9px 13px;border-radius:14px;background:var(--card);border:1px solid var(--line);white-space:pre-wrap;word-wrap:break-word}
.me .bub{background:var(--me)}.who{font-size:12px;color:var(--mut);margin:0 4px 2px}
form{display:flex;gap:8px;padding:12px 16px;border-top:1px solid var(--line)}.fwrap{max-width:820px;margin:0 auto;width:100%;display:flex;gap:8px}
#t{flex:1;font:inherit;color:var(--fg);background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;resize:none}
#send{background:var(--accent);color:#fff;border:none;padding:0 16px;font-weight:600;border-radius:10px}#send:disabled{opacity:.5}
.empty{color:var(--mut);text-align:center;margin-top:60px}
#search{margin:0 10px 6px;padding:7px 9px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);font:inherit;width:calc(100% - 20px)}
.tools{margin:2px 4px}.copy{background:none;border:1px solid var(--line);color:var(--mut);border-radius:6px;font-size:12px;padding:2px 8px;cursor:pointer}
.bub pre.code{background:var(--side);border:1px solid var(--line);border-radius:8px;padding:8px;overflow:auto;white-space:pre;font-family:ui-monospace,monospace;font-size:13px;margin:6px 0}
.bub code{background:var(--side);border-radius:4px;padding:1px 4px;font-family:ui-monospace,monospace;font-size:90%}.bub a{color:var(--accent)}
.gate{margin:auto;max-width:360px;text-align:center;padding:24px}
#dash{position:fixed;inset:0;background:rgba(0,0,0,.4);display:none;z-index:9}
.dcard{margin:auto;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;max-width:440px;width:92%}
.dcard h3{margin:0 0 8px}.dcard table{width:100%;border-collapse:collapse}.dcard td,.dcard th{text-align:left;padding:4px 6px;border-bottom:1px solid var(--line);font-size:14px}
.bars{display:flex;gap:4px;align-items:flex-end;height:54px;margin:12px 0 2px}.bars>div{flex:1;background:var(--accent);border-radius:3px 3px 0 0;min-height:2px}
@media(max-width:720px){#side{position:fixed;inset:0 40% 0 0;z-index:5;transform:translateX(-100%);transition:.2s}#side.open{transform:none}#burger{display:block}}
</style></head><body>
<nav id=side><h1>Jarvis</h1><button id=newc>+ New chat</button><input id=search placeholder="Search chats…"><div id=list></div></nav>
<div id=main>
<header><button id=burger>☰</button>
<select id=brain title="model"><option value=auto>Auto</option><option value=f>Fast</option>
<option value=d>Dolphin</option><option value=q>Qwen</option><option value=c>Claude</option></select>
<span id=stat style="color:var(--mut);font-size:13px"></span>
<button id=listsb title="to-dos & calendar" style="margin-left:auto;background:none;border:none;color:var(--fg);font-size:18px;cursor:pointer">☑</button>
<button id=statsb title="usage" style="background:none;border:none;color:var(--fg);font-size:18px;cursor:pointer">📊</button></header>
<div id=log><div class=wrap id=msgs></div></div>
<form id=f><div class=fwrap><textarea id=t rows=1 placeholder="Message Jarvis…  (prefix f: d: q: c: to pick a model)" autofocus></textarea><button id=send>Send</button></div></form>
</div>
<div id=dash><div class=dcard><h3>Usage · last 30 days</h3><div id=dbody></div>
<p style=text-align:right><button id=dclose style="background:var(--accent);color:#fff;border:none;border-radius:8px;padding:7px 14px">Close</button></p></div></div>
<div id=lists style="position:fixed;inset:0;background:rgba(0,0,0,.4);display:none;z-index:9"><div class=dcard>
<h3>To-do</h3><div id=todobody></div>
<div style="display:flex;gap:6px;margin:6px 0 14px"><input id=todoin placeholder="Add a task…" style="flex:1;padding:7px 9px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)"><button id=todoadd style="background:var(--accent);color:#fff;border:none;border-radius:8px;padding:0 12px">Add</button></div>
<h3>Calendar</h3><div id=evbody></div>
<div style="display:flex;gap:6px;margin:6px 0 4px"><input id=evin placeholder="e.g. dentist tomorrow at 5pm" style="flex:1;padding:7px 9px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)"><button id=evadd style="background:var(--accent);color:#fff;border:none;border-radius:8px;padding:0 12px">Add</button></div>
<p style=text-align:right><button id=lclose style="background:var(--accent);color:#fff;border:none;border-radius:8px;padding:7px 14px">Close</button></p></div></div>
<script>
const $=s=>document.querySelector(s),msgs=$('#msgs'),list=$('#list');
let tok=localStorage.getItem('jtok')||'',cur=null;
function hdr(){return {Authorization:'Bearer '+tok}}
function gate(){document.body.innerHTML='<div class=gate><p>Enter the Jarvis access token.</p>'+
 '<input id=tk type=password style="width:100%;padding:10px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg)">'+
 '<p><button onclick="save()">Unlock</button></p></div>';}
window.save=()=>{tok=document.getElementById('tk').value.trim();localStorage.setItem('jtok',tok);location.reload();};
function esc(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function md(s){return s.split('```').map((p,i)=>i%2
  ? '<pre class=code>'+esc(p.replace(/^[a-z0-9]*\n/i,''))+'</pre>'
  : esc(p).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>')
     .replace(/(^|\n)#{1,6} (.+)/g,'$1<b>$2</b>').replace(/(^|\n)\s*[-*] (.+)/g,'$1• $2')
     .replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g,'<a href="$2" target=_blank rel=noopener>$1</a>')
     .replace(/\n/g,'<br>')).join('');}
function addMsg(who,cls,text,asMd){const d=document.createElement('div');d.className='msg '+cls;
 d.innerHTML='<div><div class=who></div><div class=bub></div><div class=tools></div></div>';
 d.querySelector('.who').textContent=who;const bub=d.querySelector('.bub');
 if(text!=null){if(asMd){bub.innerHTML=md(text);copyBtn(d,text);}else bub.textContent=text;}
 msgs.appendChild(d);$('#log').scrollTop=$('#log').scrollHeight;return bub;}
function copyBtn(d,text){const tl=d.querySelector('.tools');tl.innerHTML='<button class=copy>Copy</button>';
 const b=tl.querySelector('.copy');b.onclick=()=>{navigator.clipboard.writeText(text);b.textContent='Copied';setTimeout(()=>b.textContent='Copy',1200);};}
async function chats(q){const r=await fetch('api/chats'+(q?'?q='+encodeURIComponent(q):''),{headers:hdr()});if(r.status===401){gate();return;}
 const d=await r.json();list.innerHTML='';
 d.chats.forEach(c=>{const e=document.createElement('div');e.className='ci'+(c.id===cur?' on':'');
  e.innerHTML='<span class=ti></span><span class=x>✕</span>';const ti=e.querySelector('.ti');ti.textContent=c.title;
  ti.onclick=()=>open_(c.id);
  ti.ondblclick=async()=>{const nt=prompt('Rename chat',c.title);if(nt==null)return;
   await fetch('api/rename',{method:'POST',headers:{...hdr(),'Content-Type':'application/json'},body:JSON.stringify({id:c.id,title:nt})});chats($('#search').value);};
  e.querySelector('.x').onclick=async ev=>{ev.stopPropagation();if(!confirm('Delete this chat?'))return;
   await fetch('api/delete',{method:'POST',headers:{...hdr(),'Content-Type':'application/json'},body:JSON.stringify({id:c.id})});
   if(cur===c.id){cur=null;msgs.innerHTML='';}chats($('#search').value);};
  list.appendChild(e);});
 $('#stat').textContent='auto-deletes after '+d.days+' days of no use';}
async function open_(id){cur=id;msgs.innerHTML='';$('#side').classList.remove('open');
 const r=await fetch('api/chat?id='+id,{headers:hdr()});if(!r.ok)return;const d=await r.json();
 d.messages.forEach(m=>addMsg(m.role==='user'?'you':'Jarvis · '+m.brain,m.role==='user'?'me':'',m.content,m.role!=='user'));
 chats($('#search').value);}
$('#newc').onclick=()=>{cur=null;msgs.innerHTML='<div class=empty>New chat — say something to begin.</div>';
 document.querySelectorAll('.ci').forEach(e=>e.classList.remove('on'));$('#side').classList.remove('open');};
$('#burger').onclick=()=>$('#side').classList.toggle('open');
$('#statsb').onclick=async()=>{const r=await fetch('api/stats',{headers:hdr()});if(!r.ok)return;const d=await r.json();
 let h='<p>'+d.total+' replies · '+d.claude+' via Claude.</p><table><tr><th>Model</th><th>Replies</th><th>Avg time</th></tr>';
 d.models.forEach(m=>h+='<tr><td>'+m.model+'</td><td>'+m.count+'</td><td>'+m.avg_s+'s</td></tr>');
 if(!d.models.length)h+='<tr><td colspan=3 style=color:var(--mut)>No replies yet.</td></tr>';
 h+='</table>';const mx=Math.max(1,...d.last7.map(x=>x.n));
 h+='<div class=bars>'+d.last7.map(x=>'<div style="height:'+(x.n/mx*100)+'%" title="'+x.day+': '+x.n+'"></div>').join('')+'</div>';
 h+='<div style="display:flex;gap:4px">'+d.last7.map(x=>'<span style="flex:1;text-align:center;font-size:10px;color:var(--mut)">'+x.day+'</span>').join('')+'</div>';
 $('#dbody').innerHTML=h;$('#dash').style.display='flex';};
$('#dclose').onclick=()=>$('#dash').style.display='none';
$('#dash').onclick=e=>{if(e.target.id==='dash')$('#dash').style.display='none';};
async function lists(){const r=await fetch('api/lists',{headers:hdr()});if(!r.ok)return;const d=await r.json();
 $('#todobody').innerHTML=d.todos.length?d.todos.map(t=>'<label style="display:flex;gap:8px;padding:3px 0;align-items:center"><input type=checkbox data-n='+t.n+'><span>'+esc(t.text)+'</span></label>').join(''):'<p style=color:var(--mut)>No tasks.</p>';
 $('#evbody').innerHTML=d.events.length?d.events.map(e=>'<div style="display:flex;justify-content:space-between;padding:3px 0"><span>'+esc(e.text)+'</span><span style=color:var(--mut)>'+esc(e.when)+'</span></div>').join(''):'<p style=color:var(--mut)>Nothing upcoming.</p>';
 $('#todobody').querySelectorAll('input').forEach(c=>c.onchange=async()=>{await fetch('api/list',{method:'POST',headers:{...hdr(),'Content-Type':'application/json'},body:JSON.stringify({kind:'todo',cmd:'done',arg:c.dataset.n})});lists();});}
async function addItem(kind,inp){const v=inp.value.trim();if(!v)return;inp.value='';
 await fetch('api/list',{method:'POST',headers:{...hdr(),'Content-Type':'application/json'},body:JSON.stringify({kind,cmd:'add',arg:v})});lists();}
$('#listsb').onclick=()=>{lists();$('#lists').style.display='flex';};
$('#lclose').onclick=()=>$('#lists').style.display='none';
$('#lists').onclick=e=>{if(e.target.id==='lists')$('#lists').style.display='none';};
$('#todoadd').onclick=()=>addItem('todo',$('#todoin'));$('#todoin').addEventListener('keydown',e=>{if(e.key==='Enter')addItem('todo',$('#todoin'));});
$('#evadd').onclick=()=>addItem('event',$('#evin'));$('#evin').addEventListener('keydown',e=>{if(e.key==='Enter')addItem('event',$('#evin'));});
let sTimer;$('#search').addEventListener('input',e=>{clearTimeout(sTimer);sTimer=setTimeout(()=>chats(e.target.value),200);});
const t=$('#t');t.addEventListener('input',()=>{t.style.height='auto';t.style.height=Math.min(t.scrollHeight,160)+'px';});
t.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();$('#f').requestSubmit();}});
$('#f').onsubmit=async e=>{e.preventDefault();const msg=t.value.trim();if(!msg)return;
 if(msgs.querySelector('.empty'))msgs.innerHTML='';
 t.value='';t.style.height='auto';addMsg('you','me',msg,false);$('#send').disabled=true;
 const bub=addMsg('Jarvis','');let buf='';
 try{const r=await fetch('api/send',{method:'POST',headers:{...hdr(),'Content-Type':'application/json'},
   body:JSON.stringify({id:cur,text:msg,brain:$('#brain').value})});
  if(r.status===401){gate();return;}
  const rd=r.body.getReader(),dec=new TextDecoder();let meta=null;
  while(true){const{done,value}=await rd.read();if(done)break;buf+=dec.decode(value,{stream:true});
   if(meta===null){const i=buf.indexOf('\n');if(i<0)continue;meta=JSON.parse(buf.slice(0,i));buf=buf.slice(i+1);
    cur=meta.id;bub.closest('.msg').querySelector('.who').textContent='Jarvis · '+meta.brain;}
   bub.textContent=buf;$('#log').scrollTop=$('#log').scrollHeight;}
  bub.innerHTML=md(buf);copyBtn(bub.closest('.msg'),buf);          // render markdown + copy when done
 }catch(err){bub.textContent='⚠ '+err;}
 $('#send').disabled=false;chats($('#search').value);t.focus();};
if(!tok)gate();else{chats().then(()=>{fetch('api/chats',{headers:hdr()}).then(r=>r.json()).then(d=>{if(d.chats[0])open_(d.chats[0].id);else $('#newc').click();});});}
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def _private(self):
        ip = self.client_address[0]
        return ip == "127.0.0.1" or ip.startswith("10.66.0.")
    def _auth(self):
        a = self.headers.get("Authorization", "")
        got = a[7:] if a.startswith("Bearer ") else ""
        return hmac.compare_digest(got, token())
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if not self._private(): self.send_error(403); return
        path, _, qs = self.path.partition("?")
        if path == "/":
            body = PAGE.encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if not self._auth(): self.send_error(401); return
        if path == "/api/chats":
            q = dict(p.split("=", 1) for p in qs.split("&") if "=" in p).get("q", "")
            from urllib.parse import unquote_plus
            q = unquote_plus(q).strip().lower()
            with LOCK:
                items = list_chats()
                if q:                                       # search title AND message text
                    hits = []
                    for it in items:
                        c = load_chat(it["id"])
                        if c and (q in it["title"].lower() or
                                  any(q in m["content"].lower() for m in c["messages"])):
                            hits.append(it)
                    items = hits
                self._json({"chats": items, "days": CHAT_DAYS})
            return
        if path == "/api/stats":
            self._json(usage_stats()); return
        if path == "/api/lists":
            self._json({"todos": memo.main(["todo", "list"]).get("items", []),
                        "events": memo.main(["event", "list"]).get("items", [])}); return
        if path == "/api/chat":
            cid = dict(p.split("=", 1) for p in qs.split("&") if "=" in p).get("id", "")
            with LOCK:
                c = load_chat(cid)
                if not c: self.send_error(404); return
                c["seen"] = int(time.time()); save_chat(c)      # opening a chat counts as interaction
            self._json({"id": c["id"], "title": c["title"],
                        "messages": [{"role": m["role"], "content": m["content"],
                                      "brain": NAMES.get(m.get("b"), "")} for m in c["messages"]]}); return
        self.send_error(404)

    def do_POST(self):
        if not self._private(): self.send_error(403); return
        if not self._auth(): self.send_error(401); return
        path = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(n) or b"{}") if n else {}

        if path == "/api/delete":
            c = load_chat(data.get("id", ""))
            if c:
                try: cpath(c["id"]).unlink()
                except Exception: pass
            self.send_response(204); self.end_headers(); return
        if path == "/api/list":
            k, cmd, arg = data.get("kind"), data.get("cmd"), str(data.get("arg", ""))
            if k in ("todo", "event") and cmd in ("add", "done", "del"):
                self._json(memo.main([k, cmd, arg])); return
            self.send_error(400); return
        if path == "/api/rename":
            with LOCK:
                c = load_chat(data.get("id", ""))
                if not c: self.send_error(404); return
                c["title"] = title_from(data.get("title", ""))[:60]; save_chat(c)
            self.send_response(204); self.end_headers(); return
        if path != "/api/send":
            self.send_error(404); return

        # Load or create the conversation, decide the brain, then stream the reply.
        with LOCK:
            convo = load_chat(data.get("id", "")) or new_chat()
            brain, msg = pick_brain(data.get("text", ""), data.get("brain", "auto"), convo)
            convo["messages"].append({"role": "user", "content": msg, "b": brain, "at": int(time.time())})
            if convo["title"] == "New chat":
                convo["title"] = title_from(msg)
            save_chat(convo)

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store"); self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        def chunk(s):
            b = s.encode() if isinstance(s, str) else s
            if b: self.wfile.write(f"{len(b):X}\r\n".encode() + b + b"\r\n"); self.wfile.flush()
        chunk(json.dumps({"brain": NAMES[brain], "id": convo["id"], "title": convo["title"]}) + "\n")
        full = ""; _t0 = time.time()
        try:
            if brain in ("f", "d"):
                for piece in stream_local(brain, convo):
                    full += piece; chunk(piece)
            elif brain == "q":
                full = ask_local(brain, convo); chunk(full)
            else:
                full = ask_claude(msg, convo); chunk(full)
        except Exception as e:
            full = f"[error] {e}";
            try: chunk("\n" + full)
            except Exception: pass
        jarvis.log_usage(brain, time.time() - _t0, "web")
        with LOCK:                                      # re-load in case it changed, append reply
            c = load_chat(convo["id"]) or convo
            c["messages"].append({"role": "assistant", "content": full, "b": brain, "at": int(time.time())})
            c["updated"] = c["seen"] = int(time.time())
            if convo.get("claude_session"): c["claude_session"] = convo["claude_session"]
            save_chat(c)
        try: self.wfile.write(b"0\r\n\r\n"); self.wfile.flush()
        except Exception: pass


def serve(host):
    for _ in range(60):
        try: srv = ThreadingHTTPServer((host, PORT), H); break
        except OSError: time.sleep(2)
    else: return
    srv.serve_forever()


if __name__ == "__main__":
    token(); import_legacy()
    hosts = ["127.0.0.1"]
    try: socket.inet_aton(WG_IP); hosts.append(WG_IP)
    except OSError: pass
    print(f"Jarvis web on http://{WG_IP}:{PORT}", flush=True)
    ts = [threading.Thread(target=serve, args=(h,), daemon=True) for h in hosts]
    for t in ts: t.start()
    for t in ts: t.join()
