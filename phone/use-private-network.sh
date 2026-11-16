#!/data/data/com.termux/files/usr/bin/bash
# Run once in Termux after the WireGuard app's "jarvis" tunnel is on:
# points the "jarvis" SSH alias at the server's private address 10.66.0.1.
# (Server identity is unchanged; HostKeyAlias keeps the saved fingerprint.)
#   bash ~/use-private-network.sh        switch to the private network
#   bash ~/use-private-network.sh undo   back to the public IP (only works while port 22 is still open)
set -euo pipefail
C=~/.ssh/config
cp "$C" "$C.bak"
if [[ "${1:-}" == undo ]]; then
  python3 - "$C" <<'PY'
import sys; p=sys.argv[1]; s=open(p).read()
s=s.replace("Host jarvis\n  HostName 10.66.0.1\n  HostKeyAlias YOUR_SERVER_PUBLIC_IP\n","Host jarvis\n  HostName YOUR_SERVER_PUBLIC_IP\n",1)
open(p,"w").write(s)
PY
  echo "jarvis → public IP again"; exit 0
fi
python3 - "$C" <<'PY'
import sys; p=sys.argv[1]; s=open(p).read()
old="Host jarvis\n  HostName YOUR_SERVER_PUBLIC_IP\n"
if "Host jarvis\n  HostName 10.66.0.1\n" in s: print("already on the private network")
elif old in s:
    open(p,"w").write(s.replace(old,"Host jarvis\n  HostName 10.66.0.1\n  HostKeyAlias YOUR_SERVER_PUBLIC_IP\n",1)); print("jarvis → 10.66.0.1 (private network)")
else: sys.exit("couldn't find the 'Host jarvis' block in ~/.ssh/config — tell Claude")
PY
ssh -o ConnectTimeout=8 jarvis 'echo "OK: reached $(hostname) over $(echo $SSH_CONNECTION | cut -d" " -f3)"' \
  || echo "Not reachable — is the WireGuard 'jarvis' tunnel switched on?"
