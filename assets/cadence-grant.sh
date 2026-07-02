#!/usr/bin/env bash
# SwiftBar click-action wrapper: apply an add/remove label set to a task on the
# right backend.
#
# SwiftBar runs `bash=` actions with a minimal PATH (no shell profile), so a bare
# `cadence` call can pick up a python3 without CA certificates and every Linear
# request dies with SSL CERTIFICATE_VERIFY_FAILED — silently, because actions run
# with terminal=false. Force a PATH whose python3 has certs, apply the label
# changes, and log the outcome so a failure is never invisible.
#
# Usage: cadence-grant.sh <backend> <config> <id> <add-csv> <remove-csv>
#   backend    linear | file
#   config     config path to scope a project (may be empty)
#   id         task/issue identifier
#   add-csv    comma-separated labels to add    (may be empty)
#   remove-csv comma-separated labels to remove (may be empty)
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

backend="${1:-linear}"; cfg="${2:-}"; id="$3"; adds="${4:-}"; rems="${5:-}"

cfg_args=()
[ -n "$cfg" ] && cfg_args=(--config "$cfg")

label_args=()
IFS=',' read -ra add_arr <<< "$adds"
for l in "${add_arr[@]}"; do [ -n "$l" ] && label_args+=(--add-label "$l"); done
IFS=',' read -ra rem_arr <<< "$rems"
for l in "${rem_arr[@]}"; do [ -n "$l" ] && label_args+=(--remove-label "$l"); done

if [ "$backend" = "file" ]; then
  out="$(cadence "${cfg_args[@]}" tasks update "$id" "${label_args[@]}" 2>&1)"
else
  out="$(cadence "${cfg_args[@]}" linear issue-update "$id" "${label_args[@]}" 2>&1)"
fi
rc=$?

log="${CADENCE_STATE_DIR:-$HOME/.cadence}/logs/swiftbar-grant.log"
printf '%s  %s  +[%s] -[%s]  %s/%s  rc=%s  %s\n' \
  "$(date -u +%FT%TZ)" "$id" "$adds" "$rems" "$backend" "${cfg:-default}" "$rc" \
  "$(printf '%s' "$out" | tr -d '\n' | cut -c1-200)" >> "$log" 2>/dev/null
exit "$rc"
