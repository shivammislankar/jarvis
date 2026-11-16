#!/data/data/com.termux/files/usr/bin/bash
# Run once in Termux after installing the Termux:Widget app (F-Droid).
# Creates home-screen buttons:
#   Jarvis       — background: vibrate, listen 6 s, reply aloud + as a notification
#   Jarvis talk  — opens a terminal with `j talk` (voice conversation)
#   Laptop shot  — background: screenshot of the laptop, opened on the phone
set -euo pipefail
mkdir -p ~/.shortcuts/tasks ~/.shortcuts/icons
chmod 700 ~/.shortcuts ~/.shortcuts/tasks

cat > ~/.shortcuts/tasks/Jarvis <<'SH'
#!/data/data/com.termux/files/usr/bin/bash
# One tap: listen 6 s → Jarvis acts or answers aloud → result also shown as a notification.
# Plans ("do …") are only SHOWN here: running them needs your y in a terminal (j do …).
termux-vibrate -d 80 2>/dev/null
termux-notification --id jarvis --title "Jarvis" --content "Listening… (6 s)" --priority high 2>/dev/null
out="$(~/bin/j -v 6 2>&1 </dev/null)"
termux-vibrate -d 40 2>/dev/null
heard="$(sed -n 's/^› //p' <<<"$out" | head -1)"
reply="$(grep -vE '^(🎙|…$|› )' <<<"$out" | sed 's/^Run these .*//; s/^Not run\.$/(Not run — open Termux and use: j do …)/' | sed '/^$/d')"
termux-notification --id jarvis --title "Jarvis${heard:+ — “$heard”}" \
  --content "${reply:-No answer (is the server reachable?)}" 2>/dev/null
SH

cat > ~/.shortcuts/"Jarvis talk" <<'SH'
#!/data/data/com.termux/files/usr/bin/bash
exec ~/bin/j talk
SH

cat > ~/.shortcuts/tasks/"Laptop shot" <<'SH'
#!/data/data/com.termux/files/usr/bin/bash
termux-toast "Taking laptop screenshot…" 2>/dev/null
~/bin/j shot >/dev/null 2>&1 || termux-toast "Laptop unreachable" 2>/dev/null
SH

chmod 700 ~/.shortcuts/tasks/Jarvis ~/.shortcuts/"Jarvis talk" ~/.shortcuts/tasks/"Laptop shot"
echo "Buttons created:"; find ~/.shortcuts -type f -not -path '*/icons/*' | sed "s|$HOME/||"
echo
echo "Now: long-press your home screen → Widgets → Termux:Widget → drag it out."
echo "If buttons do nothing: Android Settings → Apps → Termux → allow 'Display over other apps'."
