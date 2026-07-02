#!/usr/bin/env bash
# SwiftBar click-action wrapper for granting a gate.
#
# SwiftBar runs `bash=` actions with a minimal PATH (no shell profile), so a
# bare `cadence` call picks up a python3 without CA certificates and every
# Linear request dies with SSL CERTIFICATE_VERIFY_FAILED — silently, because
# actions run with terminal=false. Force a PATH whose python3 has certs, run
# the grant, and log the outcome so a failure is never invisible again.
#
# Usage: cadence-grant.sh <ISSUE-IDENTIFIER> <label-to-add> [config-path] [backend]
# config-path scopes the grant to a project (multi-project menu bar); backend is
# `linear` (default) or `file` — a file project grants via `tasks update` rather
# than `linear bulk-label`.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

issue="$1"; label="$2"; cfg="${3:-}"; backend="${4:-linear}"
cfg_args=()
[ -n "$cfg" ] && cfg_args=(--config "$cfg")

if [ "$backend" = "file" ]; then
  out="$(cadence "${cfg_args[@]}" tasks update "$issue" --add-label "$label" 2>&1)"
else
  out="$(cadence "${cfg_args[@]}" linear bulk-label "$issue" --add "$label" -y 2>&1)"
fi
rc=$?

log="${CADENCE_STATE_DIR:-$HOME/.cadence}/logs/swiftbar-grant.log"
printf '%s  %s +%s  %s/%s  rc=%s  %s\n' \
  "$(date -u +%FT%TZ)" "$issue" "$label" "$backend" "${cfg:-default}" "$rc" \
  "$(printf '%s' "$out" | tr -d '\n' | cut -c1-200)" >> "$log" 2>/dev/null
exit "$rc"
