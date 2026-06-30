#!/usr/bin/env bash
# <xbar.title>Cadence loop monitor</xbar.title>
# <xbar.desc>Ambient menu-bar status for the Cadence agent loops.</xbar.desc>
# <xbar.author>Cadence</xbar.author>
#
# SwiftBar/xbar plugin. The refresh interval lives in the filename (.1m.).
# Health dot is read from launchd directly; the dropdown shows `cadence status`
# verbatim. ponytail: dropdown body is coupled to status.sh output formatting.

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
CADENCE="$(command -v cadence || echo "$HOME/.local/bin/cadence")"
STATE="${CADENCE_STATE_DIR:-$HOME/.cadence}"
PAUSED="$STATE/runs/PAUSED"

# Health from launchd: column 2 is each job's last exit code (- = never run).
jobs="$(launchctl list 2>/dev/null | grep com.cadence)"
failed="$(printf '%s\n' "$jobs" | awk '$2 != 0 && $2 != "-" {print}')"

# Menu-bar glyph: an SF Symbol (vector, crisp, tintable) chosen by health.
# The cadence loop motif normally; a loud warning when a stage failed.
if [ -f "$PAUSED" ]; then
  echo " | sfimage=pause.circle.fill color=#e0a000"           # paused
elif [ -z "$jobs" ]; then
  echo " | sfimage=arrow.triangle.2.circlepath color=#9aa0a6" # jobs not loaded
elif [ -n "$failed" ]; then
  echo " | sfimage=exclamationmark.triangle.fill color=#d0021b" # a stage failed
else
  echo " | sfimage=arrow.triangle.2.circlepath color=#2e7d32" # healthy loop
fi

echo "---"

# Full status verbatim, monospaced so the columns line up.
"$CADENCE" status 2>&1 | while IFS= read -r line; do
  echo "${line} | font=Menlo size=11 trim=false"
done

echo "---"

if [ -f "$PAUSED" ]; then
  echo "▶ Resume loops | bash=\"$CADENCE\" param1=resume terminal=false refresh=true"
else
  echo "⏸ Pause loops | bash=\"$CADENCE\" param1=pause terminal=false refresh=true"
fi

echo "Run a stage now"
for s in triage spec build revise; do
  echo "--$s | bash=\"$CADENCE\" param1=run param2=$s terminal=true"
done

echo "View logs"
for s in triage spec build revise; do
  echo "--$s | bash=\"$CADENCE\" param1=logs param2=$s terminal=true"
done

echo "Open Linear board | href=https://linear.app/"
echo "Refresh now | refresh=true"
