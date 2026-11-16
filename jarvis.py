#!/usr/bin/env python3
"""Jarvis router — picks a brain by prefix.

  f: <text>   fast small model (local; the default on the server)
  d: <text>   Dolphin 3 8B (local)
  q: <text>   Qwen3 8B    (local)
  c: <text>   Claude      (via Claude Code, leaves the machine)
  <text>      default brain: JARVIS_DEFAULT_BRAIN in ~/jarvis/local.env (f, d or q; else d)

Commands: /reset [f|d|q|c|all]   /status   /quit
Usage:    jarvis.py              -> interactive
          jarvis.py "c: hello"   -> one-shot (what the phone calls over SSH)
          echo hi | jarvis.py -  -> read prompt from stdin
Stdlib only. Local brains are llamafile servers on 127.0.0.1 (never exposed).
"""
import json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
from pathlib import Path

HOME = Path.home()
ROOT = Path(__file__).resolve().parent
STATE = HOME / ".local/state/jarvis"
STATE.mkdir(parents=True, exist_ok=True)

def _local_env():
    """KEY=VALUE lines from ~/jarvis/local.env (per-machine settings, not in git)."""
    env = {}
    try:
        for line in (ROOT / "local.env").read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and not k.strip().startswith("#"): env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return env
CONF = _local_env()

# big = 8B models: only one of them runs at a time (laptop: 4 GB VRAM; server: 11 GB RAM).
# The small fast model never stops anything and is never stopped.
LOCAL = {
    "f": {"name": "fast", "port": 8082, "big": False},
    "d": {"name": "dolphin", "port": 8080, "big": True},
    "q": {"name": "qwen", "port": 8081, "big": True},
}
DEFAULT = CONF.get("JARVIS_DEFAULT_BRAIN", "d") if CONF.get("JARVIS_DEFAULT_BRAIN", "d") in LOCAL else "d"
MAX_HISTORY = 20          # messages kept per local brain
SYSTEM = ("You are Jarvis, a concise personal assistant. Answer directly. "
          "Never claim to have run a command; only suggest them.")

# ---------- history ----------
def hist_path(b): return STATE / f"{b}.json"

def load(b):
    try: return json.loads(hist_path(b).read_text())
    except Exception: return {}

def save(b, data): hist_path(b).write_text(json.dumps(data))

def reset(which):
    for b in (["f", "d", "q", "c"] if which in ("", "all") else [which]):
        hist_path(b).unlink(missing_ok=True)
    return f"reset: {which or 'all'}"

# ---------- local brains ----------
def api_key():
    try: return (STATE / "api-key").read_text().strip()
    except FileNotFoundError: return ""          # brain.sh creates it on first start

def healthy(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False

def ensure_local(b):
    """Start brain b if needed. Starting a big (8B) brain stops the other big one."""
    cfg = LOCAL[b]
    if healthy(cfg["port"]): return
    for other, ocfg in LOCAL.items():
        if other != b and cfg["big"] and ocfg["big"]:
            subprocess.run(["systemctl", "--user", "stop", f"jarvis-brain@{ocfg['name']}"],
                           capture_output=True)
    subprocess.run(["systemctl", "--user", "start", f"jarvis-brain@{cfg['name']}"],
                   capture_output=True)
    print(f"[waking {cfg['name']}…]", file=sys.stderr, flush=True)
    for _ in range(180):
        if healthy(cfg["port"]): return
        time.sleep(1)
    raise RuntimeError(f"{cfg['name']} did not come up — check: journalctl --user -u jarvis-brain@{cfg['name']}")

def ask_local(b, text):
    ensure_local(b)
    h = load(b).get("messages", [])
    h.append({"role": "user", "content": text})
    body = json.dumps({"model": LOCAL[b]["name"],
                       "messages": [{"role": "system", "content": SYSTEM}] + h[-MAX_HISTORY:],
                       "temperature": 0.7}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{LOCAL[b]['port']}/v1/chat/completions",
                                 data=body, headers={"Content-Type": "application/json",
                                                     "Authorization": f"Bearer {api_key()}"})
    with urllib.request.urlopen(req, timeout=600) as r:
        reply = json.load(r)["choices"][0]["message"]["content"].strip()
    if b == "q" and "</think>" in reply:          # hide Qwen3's reasoning block
        reply = reply.split("</think>", 1)[1].strip()
    h.append({"role": "assistant", "content": reply})
    save(b, {"messages": h[-MAX_HISTORY:]})
    return reply

# ---------- Claude ----------
def ask_claude(text):
    st = load("c")
    cwd = STATE / "claude-cwd"; cwd.mkdir(exist_ok=True)   # neutral dir: no project context
    claude = shutil.which("claude") or str(HOME / ".local/bin/claude")   # SSH shells may lack PATH
    cmd = [claude, "-p", "--output-format", "json",
           "--tools", "",                                # chat only: no file/shell access
           "--system-prompt", SYSTEM]
    if st.get("session_id"): cmd += ["--resume", st["session_id"]]
    # The message goes on stdin, never argv: text like "--tools=Bash" can only ever be text
    p = subprocess.run(cmd, input=text, cwd=cwd, capture_output=True, text=True, timeout=600)
    try:
        out = json.loads(p.stdout)
    except json.JSONDecodeError:
        raise RuntimeError((p.stderr or p.stdout).strip() or "claude returned nothing")
    if out.get("session_id"): save("c", {"session_id": out["session_id"]})
    if out.get("is_error"): raise RuntimeError(out.get("result", "claude error"))
    return out.get("result", "").strip()

# ---------- routing ----------
def route(line):
    s = line.strip()
    if not s: return None
    if s.startswith("/"):
        cmd, _, arg = s[1:].partition(" ")
        if cmd == "reset": return reset(arg.strip())
        if cmd == "status":
            return "\n".join(f"{c['name']}: {'up' if healthy(c['port']) else 'down'}"
                             for c in LOCAL.values())
        if cmd in ("quit", "exit"): sys.exit(0)
        return "commands: /reset [d|q|c|all]  /status  /quit"
    brain, text = DEFAULT, s
    if len(s) > 2 and s[1] == ":" and s[0].lower() in ("f", "d", "q", "c"):
        brain, text = s[0].lower(), s[2:].strip()
    return ask_claude(text) if brain == "c" else ask_local(brain, text)

def main():
    args = sys.argv[1:]
    if args:
        line = sys.stdin.read() if args == ["-"] else " ".join(args)
        try: print(route(line) or "")
        except Exception as e: print(f"[error] {e}", file=sys.stderr); sys.exit(1)
        return
    print("Jarvis online. d: dolphin · q: qwen · c: claude · /status /reset /quit")
    while True:
        try: line = input("› ")
        except (EOFError, KeyboardInterrupt): print(); break
        try:
            r = route(line)
            if r: print(r)
        except Exception as e:
            print(f"[error] {e}")

if __name__ == "__main__":
    main()
