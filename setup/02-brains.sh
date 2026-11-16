#!/usr/bin/env bash
# Phase 2+3 — local brains + router. No sudo.  Run:  bash ~/jarvis/setup/02-brains.sh
# Downloads ~10.3 GB to the internal disk (~/jarvis/models), resumable.
set -euo pipefail
J="$HOME/jarvis"; cd "$J"; mkdir -p models bin
# Idempotent + resumable: finished files are skipped, partial ones resume from <file>.part
dl() {
  [[ -s "$2" ]] && { echo "✓ $2 (already here)"; return; }
  echo "↓ $2"
  curl -L --fail --retry 10 --retry-all-errors -C - -sS -o "$2.part" "$1" && mv "$2.part" "$2"
}

# Sequential on purpose: bandwidth is shared, so this gets the default brain (Dolphin) usable first.
dl https://github.com/mozilla-ai/llamafile/releases/download/0.10.6/llamafile-0.10.6 bin/llamafile
dl https://huggingface.co/bartowski/Dolphin3.0-Llama3.1-8B-GGUF/resolve/main/Dolphin3.0-Llama3.1-8B-Q4_K_M.gguf models/Dolphin3.0-Llama3.1-8B-Q4_K_M.gguf
dl https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/main/Qwen3-8B-Q4_K_M.gguf models/Qwen3-8B-Q4_K_M.gguf
# Voice: offline speech recognition
dl https://github.com/mozilla-ai/llamafile/releases/download/0.10.6/whisperfile-0.10.6 bin/whisperfile
dl https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en-q5_1.bin models/ggml-small.en-q5_1.bin
chmod +x bin/llamafile bin/whisperfile bin/brain.sh bin/voice bin/intent.py jarvis.py

# systemd user unit — brains start on demand from the router
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/jarvis-brain@.service <<EOF
[Unit]
Description=Jarvis local brain (%i)

[Service]
ExecStart=%h/jarvis/bin/brain.sh %i
Restart=on-failure

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
loginctl enable-linger "$USER" || echo "(linger failed — brains will only run while you're logged in; fix: sudo loginctl enable-linger $USER)"

# 'jarvis' on PATH
mkdir -p ~/.local/bin && ln -sf "$J/jarvis.py" ~/.local/bin/jarvis
echo "Done. Test:  jarvis \"d: hello\"   then   jarvis \"c: hello\""
