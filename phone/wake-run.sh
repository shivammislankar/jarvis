#!/data/data/com.termux/files/usr/bin/bash
# Start the always-on "Hey Jarvis" listener (on-device). Run to test, or via Termux:Boot.
# Needs: setup-wake.sh done once, and the WireGuard tunnel on (so 'jarvis' is reachable).
set -uo pipefail
cleanup(){ termux-microphone-record -q >/dev/null 2>&1; termux-wake-unlock 2>/dev/null; }
trap cleanup EXIT INT TERM
termux-wake-lock
pulseaudio --check 2>/dev/null || pulseaudio --start --exit-idle-time=-1 >/dev/null 2>&1
pactl list sources short 2>/dev/null | grep -q sles || pactl load-module module-sles-source >/dev/null 2>&1
echo "Jarvis listener running — say \"Hey Jarvis …\". Ctrl-C to stop."
parec --rate=16000 --channels=1 --format=s16le 2>/dev/null | ~/jarvis-listen.py
