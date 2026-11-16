#!/usr/bin/env bash
# Laptop SSH, locked down for Jarvis. Run once:  sudo bash ~/jarvis/setup/01-ssh.sh
# The laptop's sshd only needs to accept the Jarvis reverse tunnel, which arrives on 127.0.0.1.
# So: keys only, no passwords, no root, your user only, and it listens on 127.0.0.1 only —
# unreachable from any Wi-Fi or LAN, even with the firewall off. Nobody gets a laptop shell
# from the network; the server's key (added later) is further limited to bin/ctl-gate.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
U="${SUDO_USER:?run via sudo from your own account}"
CONF=/etc/ssh/sshd_config.d/10-jarvis.conf

dnf -y -q install openssh-server
cat > "$CONF" <<EOF
# Jarvis: sshd only for the reverse tunnel (which connects to 127.0.0.1)
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
AllowUsers $U
ListenAddress 127.0.0.1
EOF
sshd -t
systemctl enable sshd >/dev/null 2>&1
systemctl restart sshd
# Nothing outside needs port 22 on the laptop
firewall-cmd -q --permanent --remove-service=ssh 2>/dev/null || true
firewall-cmd -q --reload 2>/dev/null || true
echo "sshd: keys only, user $U only, listening on 127.0.0.1 only:"
ss -tln | awk '$4 ~ /:22$/ {print "  " $4}'
