#!/data/data/com.termux/files/usr/bin/bash
# Run once in Termux: check Jarvis every 30 min in the background, notify only on problems.
#   bash ~/add-health.sh        (re-run any time; it replaces the old schedule)
#   bash ~/add-health.sh off    (stop the checks)
set -euo pipefail
JOB=7     # fixed id so re-running replaces the schedule instead of adding a second one
if [[ "${1:-}" == off ]]; then
  termux-job-scheduler --cancel --job-id $JOB && echo "health checks stopped"; exit 0
fi
mkdir -p ~/bin && cp "$(dirname "$0")/jarvis-health" ~/bin/jarvis-health && chmod 700 ~/bin/jarvis-health
termux-job-scheduler --job-id $JOB --script ~/bin/jarvis-health \
  --period-ms 1800000 --persisted true --network any >/dev/null
echo "Scheduled: every 30 min, also after reboots (job $JOB)."
termux-job-scheduler --pending | grep -A3 "\"id\": $JOB" || true
echo
echo "Running one check now…"; ~/bin/jarvis-health && echo "done (last check: $(cat ~/.cache/jarvis-health/checked))"
echo "If Android asks about battery optimisation for Termux:API, choose 'Don't optimise'."
