# Jarvis

A private, self-hosted voice and chat assistant you control from an Android phone.
Local AI models run on your own (free) cloud server; Claude is used only when you ask for it;
and your laptop can be controlled from anywhere — over a private network that only your
three devices can reach.

```
Phone (Termux) ──WireGuard──► Server ──► local models (Dolphin / Qwen), Whisper, notes, reminders
                                  │──► Claude (only for "c:" / "ask Claude")
                                  └──reverse tunnel opened by the laptop──► Laptop (apps, volume, lock, screenshot)
```

## What it does
- **Browser chat UI**: open `http://10.66.0.1:8088` from your phone or laptop (private network only, token-protected); streams replies, same brains and memory as the phone. Separate conversations with a ChatGPT-style sidebar (create, switch, rename, delete), each with its own memory; a conversation with no interaction (no new message and not opened) for 45 days is auto-deleted (`JARVIS_CHAT_DAYS`)
- **Chat** with a fast local model by default (Qwen3-4B, `f:`), the bigger Dolphin 8B (`d:`), Qwen3 8B (`q:`) or Claude (`c:`)
  Each model keeps its own memory; a message with no prefix continues whichever you last used (reverts to the default after ~30 min idle, set by `JARVIS_STICKY_SECONDS`)
- **Voice**: one-tap home-screen button or `j -v` / `j talk`; speech is recognised offline (Whisper)
- **Control the laptop**: open/close apps, volume, media, lock, screenshots, websites, notifications
- **AI plans with confirm-before-run**: "I'm going to sleep" → proposed actions, run only if you answer **y**
- **Notes and reminders**: reminders ring through the phone's own Clock app (works offline)
- **Morning brief** at 8 AM and **health alerts** on the phone when something stays broken

## What you need
| Device | Tested with |
|---|---|
| Server | Oracle Cloud Always Free, Ampere A1, 2 OCPU / 12 GB, Oracle Linux 9 (any ~12 GB Linux box works) |
| Laptop | Fedora with GNOME (Wayland), NetworkManager |
| Phone | Android with **Termux**, **Termux:API**, **Termux:Widget** and **WireGuard**, all from F-Droid |
| Optional | A Claude Pro plan, for the `c:` brain via Claude Code |

## Files
| Path | Runs on | What it is |
| --- | --- | --- |
| `jarvis.py` | server | Router: `f:` fast (default on the server), `d:` Dolphin, `q:` Qwen, `c:` Claude |
| `bin/brain.sh` | server | Starts a llamafile model server (systemd `jarvis-brain@<name>`) |
| `bin/voice`, `bin/intent.py` | server | Speech → text (Whisper) → action, plan, note, reminder or chat |
| `bin/plan.py` | server | AI proposes allowlisted laptop actions (never runs them) |
| `bin/memo.py`, `bin/brief`, `bin/health` | server | Notes/reminders, morning brief, health checks |
| `bin/web.py` | server | Browser chat UI on the private network (systemd `jarvis-web`) |
| `bin/ctl-server` | server (as `bin/ctl`) | Relays laptop actions down the tunnel, logs each one |
| `bin/ctl`, `bin/apps.py` | laptop | The laptop actions themselves (fixed list) |
| `bin/ctl-gate` | laptop | Forced command: the server's key can only run `ctl` |
| `phone/` | phone | The `j` client, home-screen buttons, health watcher, setup scripts |
| `setup/` | — | Install scripts, systemd units, `deploy-server.sh` |

## Setup (outline)
Replace the placeholders as you go: `YOUR_SERVER_PUBLIC_IP`, `YOUR_LAPTOP_USER`, `YOUR_LAPTOP_LAN_IP`.

1. **Server** — clone to `~/jarvis`, run `bash setup/02-brains.sh` (downloads ~10 GB of models), then
   ```
   printf 'JARVIS_STT_MODEL=tiny.en-q5_1\nJARVIS_NO_MMAP=1\nJARVIS_LAPTOP_USER=YOUR_LAPTOP_USER\nJARVIS_DEFAULT_BRAIN=f\nJARVIS_PLAN_PORT=8082\n' > ~/jarvis/local.env
   systemctl --user enable --now jarvis-brain@fast jarvis-brain@dolphin
   cp setup/systemd/jarvis-web.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now jarvis-web
   ```
   Optional: install Claude Code and sign in for the `c:` brain.
2. **Private network** — WireGuard `10.66.0.0/24`: server `10.66.0.1` (UDP 51820), laptop `10.66.0.2`
   (a NetworkManager WireGuard connection), phone `10.66.0.3` (WireGuard app, always-on, AllowedIPs
   `10.66.0.1/32`). Then close public SSH: allow only UDP 51820 in the cloud firewall and in firewalld.
3. **Laptop** — clone to `~/jarvis` (needs `bin/ctl`, `bin/apps.py`, `bin/ctl-gate`), then
   `sudo bash setup/01-ssh.sh` (sshd: keys only, listening on 127.0.0.1 only — the tunnel's way in).
   Install `setup/systemd/jarvis-tunnel.service` as a user service, and give the server its own key in
   `~/.ssh/authorized_keys` as `restrict,command="/home/YOUR_LAPTOP_USER/jarvis/bin/ctl-gate" ssh-ed25519 …`.
4. **Phone** — in Termux: `bash setup-termux.sh` (prints the phone's public key) → on the laptop
   `bash setup/add-phone-key.sh '<that key>'` (authorises it on the **server only**) → turn on the
   WireGuard tunnel → `bash add-server.sh`, `bash add-widgets.sh`, `bash add-health.sh`.
   The phone never gets SSH access to the laptop; use a strong screen lock on it.

After a code change on the laptop: `git commit` → `bash setup/deploy-server.sh`.

## Security model
- The server answers **only WireGuard packets signed by your laptop's or phone's key**; public SSH is closed.
- SSH is key-only, no root login, post-quantum key exchange.
- The server's key on the laptop is restricted to `ctl` (a fixed action list) — never a shell.
- AI-proposed actions are allowlisted, re-validated in code and run only after you answer **y**;
  every laptop action is logged.
- Local models and voice run on your server; only `c:` / "ask Claude" messages go to Anthropic.

## Licence
MIT — see `LICENSE`.
