#!/usr/bin/env bash
# Phase 5 — always-on. Run:  sudo bash ~/jarvis/setup/03-wol.sh
# Enables Wake-on-LAN (magic packet) on the Ethernet port, persistently,
# and stops the lid from suspending the laptop while it's on AC power.
# Undo: sudo bash ~/jarvis/setup/03-wol.sh off
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
IF=eno1
CONN="$(nmcli -t -f NAME,DEVICE con show --active | awk -F: -v i="$IF" '$2==i{print $1}')"
[[ -n "$CONN" ]] || { echo "no active connection on $IF — plug in the Ethernet cable"; exit 1; }
UDEV=/etc/udev/rules.d/90-jarvis-wol.rules
LID=/etc/systemd/logind.conf.d/90-jarvis.conf

if [[ "${1:-}" == "off" ]]; then
  nmcli con modify "$CONN" 802-3-ethernet.wake-on-lan default
  rm -f "$UDEV" "$LID"
  echo disabled > "/sys/class/net/$IF/device/power/wakeup"
  echo "Wake-on-LAN and lid override removed (reboot to fully reset logind)."; exit 0
fi

echo "--- NIC capability:"
ethtool "$IF" | grep -E 'Supports Wake-on|^\s+Wake-on'
ethtool "$IF" | grep -q 'Supports Wake-on:.*g' || { echo "this NIC does not support magic-packet wake"; exit 1; }

# 1. NetworkManager re-arms WoL every time the link comes up (survives reboots)
nmcli con modify "$CONN" 802-3-ethernet.wake-on-lan magic
ethtool -s "$IF" wol g                                   # arm it right now too

# 2. Let the Ethernet controller wake the system from sleep (persist via udev)
cat > "$UDEV" <<EOF
ACTION=="add", SUBSYSTEM=="net", KERNEL=="$IF", RUN+="/bin/sh -c 'echo enabled > /sys/class/net/$IF/device/power/wakeup'"
EOF
echo enabled > "/sys/class/net/$IF/device/power/wakeup"

# 3. Hub mode: closing the lid on AC power doesn't suspend (on battery it still does)
mkdir -p "${LID%/*}"
cat > "$LID" <<EOF
[Login]
HandleLidSwitchExternalPower=ignore
EOF
systemctl kill -s HUP systemd-logind                     # reload config without logging you out

echo "--- result:"
ethtool "$IF" | grep -E '^\s+Wake-on'
echo "device wakeup: $(cat /sys/class/net/$IF/device/power/wakeup)"
echo "MAC for the phone: $(cat /sys/class/net/$IF/address)"
echo "Done. Test: systemctl suspend  → then on the phone:  j \"hello\""
