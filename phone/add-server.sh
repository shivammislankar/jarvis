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
# No "laptop" host on purpose: the phone has no shell access to the laptop (laptop actions
# go through the server's restricted key). Remove an old block left by earlier versions:
if grep -q '^Host laptop$' ~/.ssh/config 2>/dev/null; then
  python3 - ~/.ssh/config <<'PY'
import re, sys; p = sys.argv[1]; s = open(p).read()
s = re.sub(r"\n(# The laptop[^\n]*\n)?Host laptop\n(  [^\n]*\n)*", "\n", s)
open(p, "w").write(s)
PY
  echo "removed the old 'laptop' entry (j sh is gone for security)"
fi
mkdir -p ~/bin && cp "$(dirname "$0")/j" ~/bin/j && chmod +x ~/bin/j && echo "updated ~/bin/j"
echo
echo "First connection: check the server fingerprint matches, then type yes."
echo "  server (jarvis): <server fingerprint: run `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the server>"
echo "Test:  j status    j \"hello\""
