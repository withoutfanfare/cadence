#!/usr/bin/env bash
# SwiftBar click-action wrapper for granting a gate.
#
# SwiftBar runs `bash=` actions with a minimal PATH (no shell profile), so a
# bare `cadence` call picks up a python3 without CA certificates and every
# Linear request dies with SSL CERTIFICATE_VERIFY_FAILED — silently, because
# actions run with terminal=false. Force a PATH whose python3 has certs, run
# the grant, and log the outcome so a failure is never invisible again.
#
# Usage: cadence-grant.sh <ISSUE-IDENTIFIER> <label-to-add>
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

log="${CADENCE_STATE_DIR:-$HOME/.cadence}/logs/swiftbar-grant.log"
out="$(cadence linear bulk-label "$1" --add "$2" -y 2>&1)"
rc=$?
printf '%s  %s +%s  rc=%s  %s\n' \
  "$(date -u +%FT%TZ)" "$1" "$2" "$rc" \
  "$(printf '%s' "$out" | tr -d '\n' | cut -c1-200)" >> "$log" 2>/dev/null
exit "$rc"
