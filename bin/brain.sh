#!/usr/bin/env bash
# Start one local brain as an OpenAI-compatible server on localhost only.
# Usage: brain.sh fast|dolphin|qwen      (normally run by systemd: jarvis-brain@<name>)
set -euo pipefail
J="$HOME/jarvis"
[[ -f "$J/local.env" ]] && . "$J/local.env"     # per-machine settings (see voice for the format)
case "${1:-}" in
  fast)    MODEL="$J/models/${JARVIS_FAST_MODEL:-Qwen3-4B-Instruct-2507-Q4_K_M}.gguf"; PORT=8082 ;;
  dolphin) MODEL="$J/models/Dolphin3.0-Llama3.1-8B-Q4_K_M.gguf"; PORT=8080 ;;
  qwen)    MODEL="$J/models/Qwen3-8B-Q4_K_M.gguf";               PORT=8081 ;;
  *) echo "usage: $0 fast|dolphin|qwen" >&2; exit 2 ;;
esac
# RTX 2050 = 4 GB VRAM; an 8B Q4 model is ~4.9 GB, so only part fits on the GPU.
# By default llamafile measures free VRAM and picks the layer count itself.
# Override with JARVIS_NGL=<n> (lower it if you hit CUDA out-of-memory).
NGL_ARGS=(); [[ -n "${JARVIS_NGL:-}" ]] && NGL_ARGS=(-ngl "$JARVIS_NGL")
CTX="${JARVIS_CTX:-4096}"
THREADS="${JARVIS_THREADS:-$(nproc)}"; (( THREADS > 8 )) && THREADS=8   # 8 = laptop physical cores; server has 2
# JARVIS_NO_MMAP=1 loads the model into real RAM instead of mapping the file. Used on the Oracle
# server: mapped pages count as "cache", so the VM looked <20% memory-used and could be reclaimed
# as idle under Always Free rules. Loaded normally, it reads ~55% — the model really is resident.
MMAP_ARGS=(); [[ "${JARVIS_NO_MMAP:-0}" == 1 ]] && MMAP_ARGS=(--no-mmap)
# Local API key: blocks browser pages from hitting the server (it allows CORS '*').
KEY="$HOME/.local/state/jarvis/api-key"
[[ -s "$KEY" ]] || { mkdir -p "${KEY%/*}"; (umask 077; head -c 24 /dev/urandom | base64 | tr -d '/+=' > "$KEY"); }
exec "$J/bin/llamafile" --server --gpu "${JARVIS_GPU:-auto}" --api-key-file "$KEY" \
  -m "$MODEL" --host 127.0.0.1 --port "$PORT" \
  "${NGL_ARGS[@]}" "${MMAP_ARGS[@]}" -c "$CTX" --threads "$THREADS"
