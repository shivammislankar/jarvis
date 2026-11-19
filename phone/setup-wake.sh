#!/data/data/com.termux/files/usr/bin/bash
# One-time setup for the on-device "Hey Jarvis" wake word (Termux).
# The wake model runs on the phone; audio only leaves the phone AFTER "Hey Jarvis" is heard.
set -uo pipefail
echo "== Installing packages…"
pkg update -y && pkg install -y pulseaudio python termux-api || exit 1
pip install --upgrade pip >/dev/null 2>&1

echo "== Installing openWakeWord (this is the part that may fail on Termux)…"
if pip install numpy openwakeword; then
  python -c "import openwakeword.utils as u; u.download_models(['hey_jarvis'])" \
    && echo "openWakeWord + hey_jarvis model ready." \
    || echo "! model download failed — retry with internet on."
else
  echo "!! openWakeWord/onnxruntime did NOT install on this phone."
  echo "   This is the known hard part (Termux uses a non-standard C library)."
  echo "   Copy the error above and send it to Claude — we'll pick another route."
fi

cp "$(dirname "$0")/jarvis-listen.py" ~/jarvis-listen.py && chmod +x ~/jarvis-listen.py
cp "$(dirname "$0")/wake-run.sh" ~/wake-run.sh && chmod +x ~/wake-run.sh

echo; echo "== Microphone permission: tap Allow on the prompt ('While using the app' is fine)."
termux-microphone-record -d >/dev/null 2>&1; sleep 1; termux-microphone-record -q >/dev/null 2>&1

cat <<'EOF'

== Test (turn the WireGuard tunnel on first):
    bash ~/wake-run.sh
  then say:  Hey Jarvis … what is the battery

== Start automatically on boot:
  1) Install Termux:Boot from F-Droid, open it once.
  2) mkdir -p ~/.termux/boot && \
     printf '#!/data/data/com.termux/files/usr/bin/bash\ntermux-wake-lock\nbash ~/wake-run.sh\n' > ~/.termux/boot/jarvis-wake && \
     chmod +x ~/.termux/boot/jarvis-wake

== So it keeps listening with the screen off:
  Android Settings → Apps → Termux and Termux:API → Battery → Unrestricted,
  and allow their Microphone permission "all the time".
  Note: always-listening uses noticeable battery — best while charging.
EOF
