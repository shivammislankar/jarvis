#!/usr/bin/env bash
# Phase 1 — the wire. Run:  sudo bash ~/jarvis/setup/01-ssh.sh
# Step A (default): enable sshd with passwords TEMPORARILY so the phone can ssh-copy-id.
# Step B:           sudo bash ~/jarvis/setup/01-ssh.sh lock   -> key-only, no root login.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
CONF=/etc/ssh/sshd_config.d/10-jarvis.conf

if [[ "${1:-}" == "lock" ]]; then
  U="${SUDO_USER:?run via sudo}"
  [[ -s /home/$U/.ssh/authorized_keys ]] || { echo "no authorized_keys for $U yet — run ssh-copy-id from the phone first"; exit 1; }
  cat > "$CONF" <<EOF
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
AllowUsers $U
EOF
  sshd -t && systemctl restart sshd
  echo "sshd locked: key auth only, user $U only."
  exit 0
fi

dnf -y install openssh-server
cat > "$CONF" <<EOF
PasswordAuthentication yes
PermitRootLogin no
EOF
systemctl enable --now sshd
firewall-cmd --permanent --add-service=ssh && firewall-cmd --reload
echo "sshd up (password auth TEMPORARILY on). Now from Termux run phone/setup-termux.sh,"
echo "then lock it:  sudo bash ~/jarvis/setup/01-ssh.sh lock"
