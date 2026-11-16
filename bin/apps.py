#!/usr/bin/env python3
"""Find installed desktop apps by loose name.  Used by `ctl app` / `ctl apps`.

  apps.py list            names of launchable apps
  apps.py find <query>    print the .desktop file of the best match (exit 1 + suggestions if none/ambiguous)
  apps.py close <query> [force]   close it gracefully (save prompts still appear); force = kill

Only real installed applications (.desktop entries GNOME shows) can match —
never arbitrary commands — so this is safe to expose to the phone.
"""
import re, sys
import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio

def apps():
    return [a for a in Gio.AppInfo.get_all()
            if hasattr(a, "get_filename") and a.should_show() and a.get_filename()]

def words(s): return re.findall(r"[a-z0-9]+", (s or "").lower())

def score(a, q):
    name = a.get_display_name().lower()
    stem = a.get_id().removesuffix(".desktop").lower()
    tail = stem.rsplit(".", 1)[-1]                       # org.gnome.Nautilus → nautilus
    nw, gw = words(name), words(a.get_generic_name())
    kw = [k.lower() for k in (a.get_keywords() or [])]
    if q in (name, stem, tail): return 100
    if q in nw: return 90
    if any(w.startswith(q) for w in nw) or name.startswith(q): return 80
    if q in name: return 70
    if q == " ".join(gw) or q in gw or q in kw: return 60   # "browser", "editor", "music"
    if q in tail: return 50
    if any(q in k for k in kw): return 30
    return 0

def main():
    cmd, q = (sys.argv[1:2] or ["list"])[0], " ".join(sys.argv[2:]).strip().lower()
    if cmd == "list":
        print("\n".join(sorted({a.get_display_name() for a in apps()}, key=str.lower))); return
    force = q.endswith(" force") and cmd == "close"
    if force: q = q.removesuffix(" force").strip()
    if cmd not in ("find", "close") or not q:
        sys.exit("usage: apps.py list | find <name> | close <name> [force]")
    if cmd == "find":
        a = resolve(q); print(a.get_filename()); print(a.get_display_name())
    else:
        close(resolve(q, prefer=is_open), force, q)

def resolve(q, prefer=None):
    ranked = sorted(((score(a, q), a) for a in apps()), key=lambda t: -t[0])
    ranked = [(s, a) for s, a in ranked if s > 0]
    if not ranked:
        sys.exit(f"no app matching '{q}' — try: j apps")
    top = list({a.get_id(): a for s, a in ranked if s == ranked[0][0]}.values())
    if len(top) > 1 and prefer:                      # "close writer": pick the one that's open
        top = [a for a in top if prefer(a)] or top
    if len(top) > 1:
        names = ", ".join(sorted(a.get_display_name() for a in top))
        sys.exit(f"'{q}' matches several apps: {names} — be more specific")
    return top[0]

# ---------- closing ----------
# Graceful first: GTK/GNOME apps get their own "quit" action (shows save prompts);
# everything else gets SIGTERM on its main process (Firefox/VS Code/LibreOffice quit cleanly).
# "force" = SIGKILL, for frozen apps.
import os, signal, time
from gi.repository import GLib
BUS = None
WRAPPERS = {"libreoffice": "soffice.bin"}            # launcher script → real process name

def bus():
    global BUS
    BUS = BUS or Gio.bus_get_sync(Gio.BusType.SESSION)
    return BUS

def dbus(method, *args, sig="(s)"):
    return bus().call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                           method, GLib.Variant(sig, args), None, 0, 3000, None).unpack()[0]

def app_name(a): return a.get_id().removesuffix(".desktop")

def gtk_quit_path(a):
    """Object path exporting a 'quit' action if the app is a running GApplication, else None."""
    name = app_name(a)
    if not dbus("NameHasOwner", name): return None
    path = "/" + name.replace(".", "/").replace("-", "_")
    try:
        acts = bus().call_sync(name, path, "org.gtk.Actions", "List", None, None, 0, 3000, None).unpack()[0]
        return path if "quit" in acts else None
    except GLib.Error:
        return None

def comm(pid):
    try: return open(f"/proc/{pid}/comm").read().strip()
    except OSError: return None

def main_pids(a):
    """User-owned main processes of the app (children with the same name are skipped)."""
    pids = set()
    name = app_name(a)
    if dbus("NameHasOwner", name):
        pids.add(dbus("GetConnectionUnixProcessID", name))
    exe = (a.get_commandline() or "").split()
    exe = os.path.basename(exe[0]) if exe else ""
    exe = WRAPPERS.get(exe, exe)[:15]
    if exe and exe not in ("flatpak", "env", "sh", "bash"):
        uid = os.getuid()
        for d in os.listdir("/proc"):
            if d.isdigit() and comm(d) == exe and os.stat(f"/proc/{d}").st_uid == uid:
                ppid = open(f"/proc/{d}/stat").read().rsplit(")", 1)[1].split()[1]
                if comm(ppid) != exe: pids.add(int(d))
    return {p for p in pids if p != os.getpid()}

def is_open(a): return bool(main_pids(a))

def alive(pids): return {p for p in pids if comm(p) is not None}

def close(a, force, q):
    label = a.get_display_name()
    pids = main_pids(a)
    if not pids:
        print(f"{label} isn't open"); return
    if WRAPPERS.get(os.path.basename((a.get_commandline() or "x").split()[0])):
        label += " (and its other windows — they share one process)"
    if force:
        for p in pids: os.kill(p, signal.SIGKILL)
        print(f"force-closed {label}"); return
    path = gtk_quit_path(a)
    if path:
        bus().call_sync(app_name(a), path, "org.gtk.Actions", "Activate",
                        GLib.Variant("(sava{sv})", ("quit", [], {})), None, 0, 3000, None)
    else:
        for p in pids: os.kill(p, signal.SIGTERM)
    for _ in range(16):                                # wait up to ~8 s
        time.sleep(0.5)
        if not alive(pids): print(f"closed {label}"); return
    print(f"asked {label} to close, but it's still open — it's probably asking about unsaved work "
          f"on the laptop screen. Use 'j close {q} force' to kill it.")
    sys.exit(3)

if __name__ == "__main__":
    main()
