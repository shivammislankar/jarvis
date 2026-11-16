#!/usr/bin/env python3
"""Jarvis planner: turn a request into PROPOSED laptop actions. Never runs anything.

  plan.py "I'm going to sleep"
  → {"reply": "...", "actions": [{"args": ["pause"], "desc": "pause media"}, ...], "rejected": [...]}

Guardrails (blueprint: "any command the model proposes → confirm-before-run + allowlist"):
  * The local model (Dolphin, on this server — nothing leaves the machine) must answer in a fixed
    JSON schema whose action names are an enum of the ctl allowlist.
  * Every proposed action is validated again here; anything off-list or malformed is dropped and
    reported under "rejected". `close … force` is never proposed.
  * This script only proposes. The phone shows the list and runs it only after you answer y.
"""
import json, os, re, sys, urllib.request
from pathlib import Path

STATE = Path.home() / ".local/state/jarvis"
def _local_env(key, default):
    try:
        for line in (Path(__file__).resolve().parent.parent / "local.env").read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() == key: return v.strip()
    except FileNotFoundError: pass
    return default
# which local model plans: 8082 = fast (server default via local.env), 8080 = Dolphin
PORT = int(os.environ.get("JARVIS_PLAN_PORT") or _local_env("JARVIS_PLAN_PORT", "8080"))
MAX_ACTIONS = 5
NOARG = ("pause", "play", "next", "prev", "lock", "shot")
TLD = r"(com|org|net|in|io|dev|ai|co|me|tv|app|edu|gov)"

SYSTEM = """You plan actions on the user's laptop for the assistant Jarvis.
Only these actions exist (action: meaning; arg):
- app: open an application; arg = its plain name, e.g. "firefox", "vscode", "files", "text editor"
- close: close an application normally; arg = its plain name
- vol: set volume; arg = a number 0-100, or "up", "down", "mute", "unmute"
- pause / play / next / prev: control music or video; arg = ""
- lock: lock the screen; arg = ""
- shot: take a screenshot and show it on the phone; arg = ""
- open: open a website; arg = a domain like "youtube.com" (YouTube, Gmail, news etc. are websites, never "app")
- say: show a notification on the laptop; arg = the short message
Use at most 5 actions, only ones the request clearly asks for or implies.
If the request needs anything else (files, shell commands, settings, purchases, messages to people),
return no actions and say in "reply" that you can't do that.
"reply" = one short sentence to the user describing the plan."""

EXAMPLES = [
    ("I'm going to sleep", {"reply": "Pausing media, turning the volume down and locking the laptop.",
                            "actions": [{"action": "pause", "arg": ""}, {"action": "vol", "arg": "10"},
                                        {"action": "lock", "arg": ""}]}),
    ("set up for coding", {"reply": "Opening VS Code and a terminal.",
                           "actions": [{"action": "app", "arg": "vscode"}, {"action": "app", "arg": "terminal"}]}),
    ("put on some youtube", {"reply": "Opening YouTube in the browser.",
                             "actions": [{"action": "open", "arg": "youtube.com"}]}),
    ("delete my downloads folder", {"reply": "I can't delete files; I can only run laptop actions.", "actions": []}),
]

SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "actions": {"type": "array", "maxItems": MAX_ACTIONS, "items": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["app", "close", "vol", "pause", "play", "next",
                                                      "prev", "lock", "shot", "open", "say"]},
                "arg": {"type": "string"}},
            "required": ["action", "arg"]}},
    },
    "required": ["reply", "actions"],
}


def ask_model(request):
    msgs = [{"role": "system", "content": SYSTEM}]
    for q, a in EXAMPLES:
        msgs += [{"role": "user", "content": q}, {"role": "assistant", "content": json.dumps(a)}]
    msgs.append({"role": "user", "content": request})
    body = json.dumps({"messages": msgs, "temperature": 0.1, "max_tokens": 200,
                       "response_format": {"type": "json_object", "schema": SCHEMA}}).encode()
    key = (STATE / "api-key").read_text().strip()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(json.load(r)["choices"][0]["message"]["content"])


def validate(a):
    """One proposed action → (ctl args, human description) or raise ValueError(reason)."""
    if not isinstance(a, dict):
        raise ValueError("not an action")
    act = str(a.get("action", "")).strip().lower()
    arg = re.sub(r"\s+", " ", str(a.get("arg", ""))).strip()
    if act in NOARG:
        desc = {"pause": "pause media", "play": "play media", "next": "next track",
                "prev": "previous track", "lock": "lock the screen", "shot": "take a screenshot"}[act]
        return [act], desc
    if act in ("app", "close"):
        arg = re.sub(r"\b(force|forcefully)\b", "", arg, flags=re.I).strip()   # never force by AI
        if not re.fullmatch(r"[A-Za-z0-9 .+-]{1,40}", arg):
            raise ValueError(f"bad app name {arg!r}")
        return [act, *arg.split()], f"{'open' if act == 'app' else 'close'} {arg}"
    if act == "vol":
        if arg.rstrip("%").isdigit() and 0 <= int(arg.rstrip("%")) <= 100:
            return ["vol", arg.rstrip("%")], f"set volume to {arg.rstrip('%')}%"
        if arg.lower() in ("up", "down", "mute", "unmute"):
            return ["vol", arg.lower()], {"up": "volume up", "down": "volume down",
                                           "mute": "mute", "unmute": "unmute"}[arg.lower()]
        raise ValueError(f"bad volume {arg!r}")
    if act == "open":
        site = re.sub(r"^https?://", "", arg.lower()).rstrip("/")
        if not re.fullmatch(rf"[a-z0-9-]+(\.[a-z0-9-]+)*\.{TLD}(/[A-Za-z0-9._~/?=&%-]*)?", site):
            raise ValueError(f"not a website {arg!r}")
        return ["open", site], f"open {site}"
    if act == "say":
        if not (1 <= len(arg) <= 120) or not arg.isprintable():
            raise ValueError("bad message")
        return ["say", arg], f"show \"{arg}\" on the laptop"
    raise ValueError(f"unknown action {act!r}")


def plan(request):
    out = {"reply": "", "actions": [], "rejected": []}
    try:
        p = ask_model(request)
    except Exception as e:
        out["reply"] = f"Sorry, I couldn't plan that ({e.__class__.__name__})."
        return out
    out["reply"] = str(p.get("reply", ""))[:300]
    for a in (p.get("actions") or [])[:MAX_ACTIONS]:
        try:
            args, desc = validate(a)
            out["actions"].append({"args": args, "desc": desc})
        except ValueError as e:
            out["rejected"].append(str(e))
    return out


if __name__ == "__main__":
    req = " ".join(sys.argv[1:]).strip() or sys.stdin.read().strip()
    if not req:
        sys.exit("usage: plan.py <request>")
    print(json.dumps(plan(req)))
