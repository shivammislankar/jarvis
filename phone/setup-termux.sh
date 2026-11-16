#!/data/data/com.termux/files/usr/bin/bash
# Run once in Termux. Installs what the phone needs and makes the phone's SSH key.
# The phone only ever talks to the Jarvis SERVER (never directly to the laptop), so the key
# goes on the server — added from the laptop with setup/add-phone-key.sh (see the end).
set -euo pipefail
pkg update -y
pkg install -y openssh python termux-api
mkdir -p ~/.ssh ~/bin
if [[ ! -f ~/.ssh/id_ed25519 ]]; then
  echo "Making the phone's key. Background jobs use it, so it can't have a passphrase:"
  echo "protect the phone with a strong screen lock instead."
  ssh-keygen -q -t ed25519 -N "" -C "jarvis-phone" -f ~/.ssh/id_ed25519
fi
cp "$(dirname "$0")/j" ~/bin/j && chmod +x ~/bin/j
grep -q 'HOME/bin' ~/.bashrc 2>/dev/null || echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
termux-clipboard-set < ~/.ssh/id_ed25519.pub 2>/dev/null && copied=" (also copied to the clipboard)" || copied=""
echo
echo "The phone's PUBLIC key$copied — safe to share, it's not a secret:"
echo
cat ~/.ssh/id_ed25519.pub
echo
echo "Next:"
echo "  1. Get that line to the laptop (e.g. PairDrop, or email it to yourself)."
echo "  2. On the laptop:   bash ~/jarvis/setup/add-phone-key.sh 'ssh-ed25519 AAAA… jarvis-phone'"
echo "  3. Here, after the WireGuard tunnel is on:   bash ~/add-server.sh"
