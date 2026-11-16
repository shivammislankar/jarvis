#!/data/data/com.termux/files/usr/bin/bash
# Run once in Termux on the Moto G32.
# Get it onto the phone:  scp YOUR_LAPTOP_USER@YOUR_LAPTOP_LAN_IP:jarvis/phone/* ~/   (password works until you lock sshd)
set -euo pipefail
pkg update -y
pkg install -y openssh python termux-api
[[ -f ~/.ssh/id_ed25519 ]] || ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519   # set a passphrase: key lives on a phone
mkdir -p ~/.ssh
grep -q "Host hub" ~/.ssh/config 2>/dev/null || cat >> ~/.ssh/config <<'EOF'
Host hub
  HostName YOUR_LAPTOP_LAN_IP
  User YOUR_LAPTOP_USER
  IdentityFile ~/.ssh/id_ed25519
  ServerAliveInterval 30
EOF
echo "--- ssh settings for 'hub' (should be YOUR_LAPTOP_LAN_IP / YOUR_LAPTOP_USER):"
ssh -G hub | grep -E '^(hostname|user|identityfile) '
# Install the phone's key on the laptop (Termux's ssh-copy-id mis-parses its args, so do it by hand).
# Skips if already installed; asks for the laptop password once.
ssh hub 'umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; k="$(cat)"; grep -qxF "$k" ~/.ssh/authorized_keys || echo "$k" >> ~/.ssh/authorized_keys; command -v restorecon >/dev/null && restorecon -R ~/.ssh; echo "key installed on laptop"' < ~/.ssh/id_ed25519.pub
mkdir -p ~/bin && cp "$(dirname "$0")/j" ~/bin/j && chmod +x ~/bin/j
grep -q 'HOME/bin' ~/.bashrc 2>/dev/null || echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
echo "Done. Open a new Termux session, then:  j \"hello\"   |  j   (interactive)  |  j -v  (voice)"
echo "Voice needs the Termux:API app installed too (F-Droid)."
