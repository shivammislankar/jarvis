#!/usr/bin/env bash
# Phase 2+3 — local brains + router. No sudo.  Run:  bash ~/jarvis/setup/02-brains.sh
# Downloads ~10.3 GB to the internal disk (~/jarvis/models), resumable.
set -euo pipefail
J="$HOME/jarvis"; cd "$J"; mkdir -p models bin
# Idempotent + resumable: finished files are skipped, partial ones resume from <file>.part.
# Every file is checked against a pinned SHA-256 before it is used; a mismatch is deleted, never run.
# Hashes = the publishers' own (GitHub release digests, Hugging Face LFS hashes at the pinned commit).
dl() {   # dl <url> <path> <sha256>
  if [[ -s "$2" ]]; then
    echo "$3  $2" | sha256sum -c --quiet >/dev/null 2>&1 && { echo "✓ $2 (already here, hash OK)"; return; }
    echo "✗ $2 exists but its hash is wrong — downloading again" >&2; rm -f "$2"
  fi
  echo "↓ $2"
  curl -L --fail --retry 10 --retry-all-errors -C - -sS -o "$2.part" "$1"
  if echo "$3  $2.part" | sha256sum -c --quiet >/dev/null 2>&1; then mv "$2.part" "$2"
  else echo "✗ $2: SHA-256 mismatch — refusing to use it (deleted)" >&2; rm -f "$2.part"; exit 1; fi
}

GH=https://github.com/mozilla-ai/llamafile/releases/download/0.10.6
HF=https://huggingface.co
DOLPHIN_REV=a6274707ba8c5f12d4521eabbce1b318bb2f27f5    # pinned commits: files can't change under us
QWEN_REV=7c41481f57cb95916b40956ab2f0b139b296d974
WHISPER_REV=5359861c739e955e79d9a303bcbc70fb988958b1

# Sequential on purpose: bandwidth is shared, so this gets the default brain (Dolphin) usable first.
dl $GH/llamafile-0.10.6 bin/llamafile d579f61dcd3a306f518e6d90e599d77793ed5f09543023d09c96ad35fcfa63f0
dl $HF/bartowski/Dolphin3.0-Llama3.1-8B-GGUF/resolve/$DOLPHIN_REV/Dolphin3.0-Llama3.1-8B-Q4_K_M.gguf \
   models/Dolphin3.0-Llama3.1-8B-Q4_K_M.gguf 268390e07edd407ad93ea21a868b7ae995b5950e01cad0db9e1802ae5049d405
dl $HF/Qwen/Qwen3-8B-GGUF/resolve/$QWEN_REV/Qwen3-8B-Q4_K_M.gguf \
   models/Qwen3-8B-Q4_K_M.gguf d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785
# Fast default brain: answers ~40% sooner than Dolphin on 2 ARM cores (and got the arithmetic test right)
dl $HF/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/a06e946bb6b655725eafa393f4a9745d460374c9/Qwen3-4B-Instruct-2507-Q4_K_M.gguf \
   models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf 3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597
# Voice: offline speech recognition (small = accurate on a fast CPU; tiny = for a 2-CPU server)
dl $GH/whisperfile-0.10.6 bin/whisperfile deafc9e1028b5c4e2431326593c130c25c9990b62336330df63bb14e7e2596f8
dl $HF/ggerganov/whisper.cpp/resolve/$WHISPER_REV/ggml-small.en-q5_1.bin \
   models/ggml-small.en-q5_1.bin bfdff4894dcb76bbf647d56263ea2a96645423f1669176f4844a1bf8e478ad30
dl $HF/ggerganov/whisper.cpp/resolve/$WHISPER_REV/ggml-tiny.en-q5_1.bin \
   models/ggml-tiny.en-q5_1.bin c77c5766f1cef09b6b7d47f21b546cbddd4157886b3b5d6d4f709e91e66c7c2b
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
