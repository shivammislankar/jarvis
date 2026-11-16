#!/usr/bin/env bash
# Run on the LAPTOP: authorise a phone's public key on the Jarvis server (only the server —
# the phone never gets access to the laptop).   bash setup/add-phone-key.sh 'ssh-ed25519 AAAA… name'
# To revoke a lost phone: remove its line from ~/.ssh/authorized_keys on the server (ssh oracle),
# and its [Peer] from /etc/wireguard/wg0.conf.
set -euo pipefail
KEY="${1:?usage: add-phone-key.sh 'ssh-ed25519 AAAA… name'}"
[[ "$KEY" =~ ^ssh-ed25519\ [A-Za-z0-9+/]{68}(\ [A-Za-z0-9@._-]+)?$ ]] \
  || { echo "That doesn't look like one ed25519 public key line." >&2; exit 1; }
printf '%s\n' "$KEY" | ssh oracle 'umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys
  k="$(cat)"; grep -qxF "$k" ~/.ssh/authorized_keys && echo "already authorised" \
  || { echo "$k" >> ~/.ssh/authorized_keys; echo "phone key authorised on the server"; }
  ssh-keygen -lf ~/.ssh/authorized_keys | tail -1'
