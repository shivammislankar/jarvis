#!/data/data/com.termux/files/usr/bin/bash
# Run once in Termux: lets the phone reach the Jarvis server (Oracle) as "jarvis".
# The phone's existing key (~/.ssh/id_ed25519) is already authorised on the server.
# Needs the WireGuard app's "jarvis" tunnel ON: the server only answers on the private network.
set -euo pipefail
mkdir -p ~/.ssh
if grep -q '^Host jarvis$' ~/.ssh/config 2>/dev/null; then
  echo "'jarvis' is already in ~/.ssh/config"
else
  cat >> ~/.ssh/config <<'EOF'

Host jarvis
  HostName 10.66.0.1
  HostKeyAlias YOUR_SERVER_PUBLIC_IP
  User opc
  IdentityFile ~/.ssh/id_ed25519
  ServerAliveInterval 30
EOF
  echo "added 'jarvis' to ~/.ssh/config"
fi
if grep -q '^Host laptop$' ~/.ssh/config 2>/dev/null; then
  echo "'laptop' is already in ~/.ssh/config"
else
  cat >> ~/.ssh/config <<'CONF'

# The laptop, via its reverse tunnel on the server (works from anywhere; used by `j sh`)
Host laptop
  HostName 127.0.0.1
  Port 2222
  User YOUR_LAPTOP_USER
  ProxyJump jarvis
  HostKeyAlias jarvis-laptop
  IdentityFile ~/.ssh/id_ed25519
CONF
  echo "added 'laptop' to ~/.ssh/config"
fi
mkdir -p ~/bin && cp "$(dirname "$0")/j" ~/bin/j && chmod +x ~/bin/j && echo "updated ~/bin/j"
echo
echo "First connections: check the fingerprints match, then type yes."
echo "  server (jarvis): <server fingerprint: run `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the server>"
echo "  laptop (j sh):   <laptop fingerprint: run `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the laptop>"
echo "Test:  j status    j \"hello\"    j sh"
