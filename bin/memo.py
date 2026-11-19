#!/usr/bin/env python3
"""Jarvis notes + reminders (server side). Stored in ~/.local/state/jarvis/memo.json.

  memo.py note add <text>          memo.py note list [search]      memo.py note del <n>
  memo.py remind add <sentence>    memo.py remind list              memo.py remind del <n>
  memo.py remind due               reminders due within 24 h whose phone alarm isn't set yet
  memo.py remind ack <id>          the phone has set the alarm for <id>

Every command prints one JSON object. Times are parsed by fixed rules (no AI), in the
server's time zone (Asia/Kolkata): "in 20 minutes", "at 6 pm", "at 6:30", "tomorrow at 9",
"tonight at 8", "on friday at 5 pm", "tomorrow" (= 9 am).
"""
import fcntl, json, re, sys, time
from datetime import datetime, timedelta
from pathlib import Path

import os
# JARVIS_MEMO_DB points tests at a scratch file so they never touch your real notes
DB = Path(os.environ.get("JARVIS_MEMO_DB") or Path.home() / ".local/state/jarvis/memo.json")
DAY = 86400
NUM = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve "
                                   "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
NUM.update({"a": 1, "an": 1, "thirty": 30, "forty": 40, "forty five": 45, "fifty": 50, "sixty": 60, "ninety": 90,
            "half an": 0.5, "half a": 0.5})
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


# ---------- storage (locked, so voice + phone can't clobber each other) ----------
class Store:
    def __enter__(self):
        DB.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(DB, "a+"); fcntl.flock(self.f, fcntl.LOCK_EX); self.f.seek(0)
        raw = self.f.read()
        self.d = json.loads(raw) if raw.strip() else {}
        self.d.setdefault("notes", []); self.d.setdefault("reminders", []); self.d.setdefault("next", 1)
        self.d.setdefault("todos", []); self.d.setdefault("events", [])
        return self.d

    def __exit__(self, *exc):
        if exc[0] is None:
            self.f.seek(0); self.f.truncate(); json.dump(self.d, self.f, indent=1)
            # daily snapshot (kept 14 days): an accidental delete loses at most today's changes
            snaps = DB.parent / "memo-snapshots"; snaps.mkdir(exist_ok=True)
            (snaps / f"memo-{time.strftime('%Y-%m-%d')}.json").write_text(json.dumps(self.d, indent=1))
            for old in sorted(snaps.glob("memo-*.json"))[:-14]: old.unlink()
        fcntl.flock(self.f, fcntl.LOCK_UN); self.f.close()


def new_id(d):
    d["next"] += 1
    return d["next"] - 1


def when_words(ts):
    t = datetime.fromtimestamp(ts); now = datetime.now()
    day = ("today" if t.date() == now.date() else "tomorrow" if t.date() == (now + timedelta(days=1)).date()
           else t.strftime("%A %-d %b"))
    return f"{day} at {t.strftime('%-I:%M %p')}"


# ---------- time parsing ----------
def num(s):
    s = s.strip()
    if re.fullmatch(r"\d+(\.\d+)?", s): return float(s)
    return NUM.get(s)


def clock(h, m, ap, base):
    """Next occurrence of h:m (am/pm optional) on/after `base` date's day; None if invalid."""
    h, m = int(h), int(m or 0)
    if not (0 <= m < 60) or not (0 <= h <= 23) or (ap and not 1 <= h <= 12): return None
    if ap == "pm" and h != 12: h += 12
    if ap == "am" and h == 12: h = 0
    # no am/pm: 1–6 almost always means afternoon/evening ("at 2" = 2 pm); 7–11 = next one of am/pm
    cands = [h] if (ap or h > 12 or h == 0) else [h + 12] if h <= 6 else [h, h + 12] if h < 12 else [12]
    return [base.replace(hour=x, minute=m, second=0, microsecond=0) for x in cands]


def parse(sentence, now=None):
    """'remind me at 6 pm to call mom' → (epoch, 'call mom') or raise ValueError(why)."""
    now = now or datetime.now()
    s = sentence.strip().rstrip(".!?").strip()
    s = re.sub(r"\b([ap])\.\s?m\.?", r"\1m", s, flags=re.I)              # "6 p.m." → "6 pm"
    s = re.sub(r"^(hey |ok |okay )?(jarvis[, ]*)?(please |can you |could you )*", "", s, flags=re.I)
    s = re.sub(r"^(set a )?remind(er)?( me)?[ ,:]*", "", s, flags=re.I)
    low = s.lower()                     # same length as s: match on low, cut the task from s
    T = r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)?"
    due, span = None, None

    m = re.search(r"\bin (?P<n>\d+(?:\.\d+)?|half an|half a|an|a|[a-z]+(?: [a-z]+)?) (?P<u>minutes?|mins?|hours?|hrs?|days?)\b", low)
    if m and num(m.group("n")) is not None:
        n, u = num(m.group("n")), m.group("u")
        due = now + timedelta(minutes=n) if u.startswith("min") else \
              now + timedelta(hours=n) if u.startswith(("hour", "hr")) else now + timedelta(days=n)
        span = m.span()
    if due is None:
        m = re.search(rf"\b(?:(?P<rel>tomorrow|today|tonight)\s*)?(?:(?:on |this |next )?(?P<wd>{'|'.join(DAYS)})\s*)?"
                      rf"(?:(?:at|by)\s+{T}|(?P<h2>\d{{1,2}})(?::(?P<m2>\d{{2}}))?\s*(?P<ap2>am|pm))", low)
        rel_only = None
        if not m:
            rel_only = re.search(rf"\b(?P<rel>tomorrow|tonight)\b|\b(?:on |this |next )?(?P<wd>{'|'.join(DAYS)})\b", low)
        if m:
            h = m.group("h") or m.group("h2"); mi = m.group("m") or m.group("m2"); ap = m.group("ap") or m.group("ap2")
            rel, wd = m.group("rel"), m.group("wd")
            if rel == "tonight" and not ap: ap = "pm"
            base = now
            if rel == "tomorrow" and now.hour >= 5: base = now + timedelta(days=1)   # at 3 am, "tomorrow" = this morning
            if wd: base = now + timedelta(days=(DAYS.index(wd) - now.weekday()) % 7 or 7)
            opts = clock(h, mi, ap, base)
            if not opts: raise ValueError(f"I didn't understand the time '{m.group(0)}'")
            future = [o for o in opts if o > now]
            if future: due = min(future)
            elif not rel and not wd: due = min(opts) + timedelta(days=1)       # "at 6" after 6 pm → tomorrow
            else: raise ValueError("that time has already passed")
            span = m.span()
        elif rel_only:
            rel, wd = rel_only.group("rel"), rel_only.group("wd")
            base = now + timedelta(days=1 if now.hour >= 5 else 0) if rel == "tomorrow" else \
                   now + timedelta(days=(DAYS.index(wd) - now.weekday()) % 7 or 7) if wd else now
            due = base.replace(hour=20 if rel == "tonight" else 9, minute=0, second=0, microsecond=0)
            span = rel_only.span()
    if due is None:
        raise ValueError("when? Say e.g. 'in 20 minutes', 'at 6 pm' or 'tomorrow at 9'")
    if due <= now:
        raise ValueError("that time has already passed")
    task = (s[:span[0]] + " " + s[span[1]:])
    task = re.sub(r"^\s*(to|that|about)\s+|\s+(to|that)\s*$", " ", task, flags=re.I)
    task = re.sub(r"\s+", " ", re.sub(r"^\s*((for|to|that|about)\s+)+", "", task.strip(), flags=re.I)).strip(" ,.")
    if not task:
        raise ValueError("remind you about what?")
    return int(due.timestamp()), task[:1].upper() + task[1:]


# ---------- commands ----------
def main(argv):
    if len(argv) < 2: raise SystemExit(__doc__)
    kind, cmd, rest = argv[0], argv[1], " ".join(argv[2:]).strip()
    with Store() as d:
        now = time.time()
        d["reminders"] = [r for r in d["reminders"] if r["due"] > now - 7 * DAY]   # keep a week of history
        if kind == "note":
            if cmd == "add":
                if not rest: return {"ok": False, "reply": "Remember what?"}
                d["notes"].append({"id": new_id(d), "text": rest, "at": int(now)})
                return {"ok": True, "reply": "Noted."}
            if cmd == "list":
                ns = [n for n in d["notes"] if rest.lower() in n["text"].lower()]
                return {"ok": True, "items": [{"n": i + 1, "id": x["id"], "text": x["text"],
                                               "at": datetime.fromtimestamp(x["at"]).strftime("%-d %b")}
                                              for i, x in enumerate(ns)]}
            if cmd == "del":
                try: x = d["notes"].pop(int(rest) - 1)
                except (ValueError, IndexError): return {"ok": False, "reply": f"No note number {rest}."}
                return {"ok": True, "reply": f"Forgot: {x['text']}"}
        if kind == "remind":
            upcoming = sorted([r for r in d["reminders"] if r["due"] > now], key=lambda r: r["due"])
            if cmd == "add":
                try: due, task = parse(rest)
                except ValueError as e: return {"ok": False, "reply": f"Sorry, {e}."}
                r = {"id": new_id(d), "due": due, "text": task, "alarm": False}
                d["reminders"].append(r)
                return {"ok": True, "id": r["id"], "due": due, "text": task,
                        "reply": f"I'll remind you {when_words(due)}: {task}."}
            if cmd == "list":
                return {"ok": True, "items": [{"n": i + 1, "id": r["id"], "text": r["text"], "when": when_words(r["due"]),
                                               "due": r["due"], "alarm": r["alarm"]} for i, r in enumerate(upcoming)]}
            if cmd == "del":
                try: r = upcoming[int(rest) - 1]
                except (ValueError, IndexError): return {"ok": False, "reply": f"No reminder number {rest}."}
                d["reminders"].remove(r)
                extra = " If its phone alarm was already set, also turn it off in the Clock app." if r["alarm"] else ""
                return {"ok": True, "reply": f"Cancelled: {r['text']} ({when_words(r['due'])}).{extra}"}
            if cmd == "due":
                return {"ok": True, "items": [{"id": r["id"], "due": r["due"], "text": r["text"]}
                                              for r in upcoming if not r["alarm"] and r["due"] - now < DAY]}
            if cmd == "ack":
                for r in d["reminders"]:
                    if str(r["id"]) == rest: r["alarm"] = True
                return {"ok": True}
        if kind == "todo":                                     # untimed checklist
            open_todos = [t for t in d["todos"] if not t["done"]]
            if cmd == "add":
                if not rest: return {"ok": False, "reply": "Add what to your list?"}
                d["todos"].append({"id": new_id(d), "text": rest, "done": False, "at": int(now)})
                return {"ok": True, "reply": f"Added to your list: {rest}."}
            if cmd == "list":
                return {"ok": True, "items": [{"n": i + 1, "id": t["id"], "text": t["text"]}
                                              for i, t in enumerate(open_todos)]}
            if cmd == "done":
                try: t = open_todos[int(rest) - 1]
                except (ValueError, IndexError): return {"ok": False, "reply": f"No item number {rest}."}
                t["done"] = True
                d["todos"] = [x for x in d["todos"] if not x["done"] or now - x["at"] < 7 * DAY]  # keep a week
                return {"ok": True, "reply": f"Done: {t['text']}"}
            if cmd == "del":
                try: t = open_todos[int(rest) - 1]
                except (ValueError, IndexError): return {"ok": False, "reply": f"No item number {rest}."}
                d["todos"].remove(t)
                return {"ok": True, "reply": f"Removed: {t['text']}"}
        if kind == "event":                                    # dated calendar entry (no phone alarm)
            d["events"] = [e for e in d["events"] if e["at"] > now - DAY]   # drop day-old past events
            upcoming = sorted([e for e in d["events"] if e["at"] > now], key=lambda e: e["at"])
            if cmd == "add":
                try: when, what = parse(rest)
                except ValueError as e: return {"ok": False, "reply": f"Sorry, {e}."}
                d["events"].append({"id": new_id(d), "at": when, "text": what})
                return {"ok": True, "reply": f"Added to your calendar: {what}, {when_words(when)}."}
            if cmd == "list":
                return {"ok": True, "items": [{"n": i + 1, "id": e["id"], "text": e["text"],
                                               "when": when_words(e["at"]), "at": e["at"]}
                                              for i, e in enumerate(upcoming)]}
            if cmd == "del":
                try: e = upcoming[int(rest) - 1]
                except (ValueError, IndexError): return {"ok": False, "reply": f"No event number {rest}."}
                d["events"].remove(e)
                return {"ok": True, "reply": f"Removed: {e['text']} ({when_words(e['at'])})."}
    return {"ok": False, "reply": f"unknown command: {kind} {cmd}"}


def human(r):
    """Plain sentences for the phone / text-to-speech (memo.py --text …)."""
    if "items" not in r: return r.get("reply", "")
    its = r["items"]
    if not its: return "Nothing here."
    if "when" in its[0]:
        return "\n".join(f"{i['n']}. {i['when']}: {i['text']}" for i in its)
    if "at" in its[0]:                                  # notes carry a date; to-dos don't
        return "\n".join(f"{i['n']}. {i['text']}  ({i['at']})" for i in its)
    return "\n".join(f"{i['n']}. {i['text']}" for i in its)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--text"]:
        r = main(args[1:])
        if r.get("items") == [] and args[1:2] == ["remind"]: print("No reminders coming up.")
        else: print(human(r))
    else:
        print(json.dumps(main(args)))
