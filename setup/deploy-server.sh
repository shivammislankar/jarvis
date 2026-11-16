#!/usr/bin/env bash
# Push Jarvis code from this laptop (the source of truth) to the Oracle server.
#   bash ~/jarvis/setup/deploy-server.sh
# Copies code only — models, binaries and the server's local.env stay as they are.
set -euo pipefail
cd "$(dirname "$0")/.."
rsync -a --relative -e "ssh -o BatchMode=yes" \
  jarvis.py bin/brain.sh bin/voice bin/intent.py bin/plan.py bin/health bin/memo.py bin/brief \
  setup/02-brains.sh phone/j phone/add-server.sh phone/add-widgets.sh phone/add-health.sh phone/jarvis-health phone/use-private-network.sh phone/setup-termux.sh \
  oracle:jarvis/
# The server's ctl is the relay to the laptop, not the laptop's ctl
rsync -a -e "ssh -o BatchMode=yes" bin/ctl-server oracle:jarvis/bin/ctl
ssh -o BatchMode=yes oracle 'chmod +x ~/jarvis/jarvis.py ~/jarvis/bin/*; python3 -m py_compile ~/jarvis/jarvis.py ~/jarvis/bin/*.py && echo "server updated"'
