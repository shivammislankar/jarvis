#!/usr/bin/env python3
"""Turn a spoken sentence into a laptop action (ctl args) or a chat message.

  intent.py "open firefox please"   → {"kind": "action", "args": ["app", "firefox"]}
  intent.py "what is a black hole"  → {"kind": "chat",   "text": "what is a black hole"}

Deliberately plain pattern matching, no AI: only the fixed ctl actions can be
triggered, and nothing destructive (no force-close) is reachable by voice.
"""
import json, re, sys

NUM = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split())}
NUM.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
            "eighty": 80, "ninety": 90, "hundred": 100, "a hundred": 100, "one hundred": 100})
FILLER = r"^(hey |ok |okay )?(jarvis[, ]*)?(please |can you |could you |would you )*"
TLD = r"(com|org|net|in|io|dev|ai|co|me|tv|app)"

def number(s):
    s = s.strip().replace("%", "").replace(" percent", "").replace("-", " ")
    if s.isdigit(): return int(s)
    if s in NUM: return NUM[s]
    parts = s.split()                                   # "thirty five"
    if len(parts) == 2 and parts[0] in NUM and parts[1] in NUM and NUM[parts[0]] >= 20:
        return NUM[parts[0]] + NUM[parts[1]]
    return None

SPOKEN = {"vs code": "vscode", "visual studio": "vscode", "file manager": "files", "the files": "files",
          "libre office": "libreoffice", "fire fox": "firefox", "system settings": "settings"}

def clean_target(t):
    t = re.sub(r"\b(the|app|application|program|window|for me|now|please|force|forcefully)\b", " ", t)
    for k, v in SPOKEN.items(): t = re.sub(rf"\b{k}\b", v, t)
    return re.sub(r"\s+", " ", t).strip()

def as_site(t):
    """'youtube dot com' / 'youtube.com' → 'youtube.com', else None."""
    t = re.sub(r"\s+dot\s+", ".", t).replace(" ", "")
    return t if re.fullmatch(rf"[a-z0-9-]+(\.[a-z0-9-]+)*\.{TLD}(/\S*)?", t) else None

def parse(said):
    s = said.lower().strip()
    s = re.sub(r"[.!?,]+$", "", s).strip()
    s = re.sub(FILLER, "", s).strip()
    s = re.sub(r"\s+", " ", s)
    A = lambda *a: {"kind": "action", "args": list(a)}

    if re.fullmatch(r"(good ?bye|bye( bye)?|stop listening|that's all|that is all|exit voice( mode)?|go to sleep|thank you,? that's all)( jarvis)?", s):
        return {"kind": "bye"}

    # morning brief
    if re.fullmatch(r"good morning( jarvis)?|(my |the )?(morning )?brief(ing)?( me)?|brief me|what('s| is) (on )?(my day|today)( look like)?", s):
        return {"kind": "brief"}

    # notes + reminders (stored on the server by memo.py; reminders ring as phone alarms)
    if re.fullmatch(r"(set a )?remind(er)?( me)?\b.*", s):
        return {"kind": "remind", "text": said.strip()}
    if re.fullmatch(r"(what (are|were) )?(my|any) reminders|(show|list|read)( me)? my reminders|what reminders do i have", s):
        return {"kind": "reminders"}
    if re.fullmatch(r"(what (did|have) i (ask|asked|tell|told) you to remember|(read|show|list)( me)? my notes|(what are )?my notes)", s):
        return {"kind": "notes"}
    m = re.match(r"(?:(?:hey |ok |okay )?jarvis[, ]*)?(?:please )?(?:remember|make a note|take a note|note down|note|write down)"
                 r"(?: (?:that|this))?[ :,]+(.+)", said.strip(), flags=re.I)
    if m and not s.startswith(("remember when", "remember what")):
        return {"kind": "note", "text": m.group(1).strip().rstrip(".")}

    # to-do list
    m = re.match(r"(?:(?:hey |ok |okay )?jarvis[, ]*)?(?:please )?add (.+?) to my (?:to-?do ?list|list|tasks)$", said.strip(), flags=re.I)
    if m: return {"kind": "todo", "text": m.group(1).strip().rstrip(".")}
    if re.fullmatch(r"(what('s| is) on )?my (to-?do ?list|list|tasks)|(show|list|read)( me)? my (to-?do ?list|list|tasks)", s):
        return {"kind": "todos"}
    # calendar / events
    m = re.match(r"(?:(?:hey |ok |okay )?jarvis[, ]*)?(?:please )?add (?:an? )?(?:event|appointment|meeting)[ :,]+(.+)", said.strip(), flags=re.I)
    if m: return {"kind": "event", "text": m.group(1).strip()}
    if re.fullmatch(r"(what('s| is) on )?my (calendar|schedule|events|agenda)|(show|list|read)( me)? my (calendar|schedule|events)|what('s| is) (coming up|on (today|this week))", s):
        return {"kind": "events"}

    # multi-step requests → the planner proposes actions; the phone asks before running any
    m = re.fullmatch(r"(do(?! (you|i|we|they|it|he|she|not)\b)|plan|handle|set (things )?up for|get (the laptop |it |things )?ready for)[ :,]+(.+)", s)
    if m: return {"kind": "plan", "text": m.group(0) if m.group(1).startswith(("set", "get")) else m.group(m.lastindex)}

    # bedtime is a common routine — plan it (still needs your y on the phone)
    if re.fullmatch(r"(i'?m|i am) (going|off|heading) to (sleep|bed)( now)?|good ?night( jarvis)?|bed ?time", s):
        return {"kind": "plan", "text": "I'm going to sleep"}

    # chat with a specific brain: "ask claude …", "ask qwen …"
    m = re.match(r"(ask|tell) (claude|qwen|dolphin)[, ]+(.+)", s)
    if m: return {"kind": "chat", "text": f"{m.group(2)[0]}: {m.group(3)}"}

    # volume
    if re.fullmatch(r"(un ?mute|sound on)( (it|the (sound|volume|laptop)))?", s): return A("vol", "unmute")
    if re.fullmatch(r"(mute|silence)( (it|the (sound|volume|laptop)))?|sound off", s): return A("vol", "mute")
    if re.fullmatch(r"(turn (it|the (sound|volume|music)) up|volume up|louder|increase (the )?volume)", s): return A("vol", "up")
    if re.fullmatch(r"(turn (it|the (sound|volume|music)) down|volume down|quieter|softer|lower (the )?volume|decrease (the )?volume)", s): return A("vol", "down")
    m = re.fullmatch(r"(set )?(the )?volume( to| at)? (.+)", s)
    if m and number(m.group(4)) is not None and 0 <= number(m.group(4)) <= 100:
        return A("vol", str(number(m.group(4))))
    if re.fullmatch(r"(what('s| is) the )?volume", s): return A("vol")

    # media
    if re.fullmatch(r"(pause|stop)( (it|the )?(music|song|video|media|playback))?", s): return A("pause")
    if re.fullmatch(r"(play|resume|continue)( (it|the )?(music|song|video|media|playback))?", s): return A("play")
    if re.fullmatch(r"(next|skip)( (song|track|video))?|skip (it|this)", s): return A("next")
    if re.fullmatch(r"(previous|last|go back)( (song|track|video))?", s): return A("prev")

    # screen
    if re.fullmatch(r"lock( (the|my))?( (screen|laptop|computer|pc))?", s): return A("lock")
    if re.fullmatch(r"(take )?(a )?screen ?shot|show me the screen|what('s| is) on the screen", s):
        return {"kind": "shot"}

    # info
    if re.fullmatch(r"(what('s| is) the |how('s| is) the |check (the )?)?battery( level| status)?", s): return A("battery")
    if re.fullmatch(r"(laptop |system )?status|how('s| is) the laptop( doing)?", s): return A("status")

    # notifications on the laptop
    m = re.fullmatch(r"(show|send|display) (a )?(message|notification)( on the laptop)?( saying| that)? (.+)", s)
    if m: return A("say", m.group(6))

    # open / close
    m = re.fullmatch(r"(open|launch|start|run) (up )?(.+)", s)
    if m:
        t = clean_target(m.group(3))
        site = as_site(t) or (as_site(re.sub(r"^(website|site) ", "", t)) if t.startswith(("website", "site")) else None)
        if site: return A("open", site)
        if t: return A("app", *t.split())
    m = re.fullmatch(r"(close|quit|exit|kill|shut) (down )?(.+)", s)
    if m:
        t = clean_target(m.group(3))
        if t: return A("close", *t.split())            # never "force" by voice

    return {"kind": "chat", "text": said.strip()}

if __name__ == "__main__":
    print(json.dumps(parse(" ".join(sys.argv[1:]))))
