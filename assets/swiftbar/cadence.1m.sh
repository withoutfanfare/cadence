#!/usr/bin/env bash
# <xbar.title>Cadence loop monitor</xbar.title>
# <xbar.desc>Ambient menu-bar status for the Cadence agent loops, across every registered project.</xbar.desc>
# <xbar.author>Cadence</xbar.author>
#
# SwiftBar/xbar plugin. The refresh interval lives in the filename (.1m.).
# The menu-bar glyph aggregates health across all registered projects; the
# dropdown shows one section per project from `cadence overview --json`, with
# per-project pause/run/logs actions scoped by --config.

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
CADENCE="$(command -v cadence || echo "$HOME/.local/bin/cadence")"

json="$("$CADENCE" overview --json 2>/dev/null)"

# Pass JSON via env (not a pipe): `python3 -` already consumes stdin for the script.
CADENCE_OVERVIEW_JSON="$json" python3 - "$CADENCE" <<'PY'
import json, os, sys

CAD = sys.argv[1]
GLYPH = {"ok": "✅", "failed": "❌", "paused": "⏸", "idle": "·"}
STAGES = ["triage", "spec", "build", "revise", "advance", "conduct"]

try:
    data = json.loads(os.environ.get("CADENCE_OVERVIEW_JSON") or "null")
except Exception:
    data = None

projects = (data or {}).get("projects") or []

# Menu-bar glyph: worst state wins (failed > paused > ok > idle).
healths = [p["health"] for p in projects]
if not projects:
    print(" | sfimage=arrow.triangle.2.circlepath color=#9aa0a6")
elif "failed" in healths:
    n = healths.count("failed")
    print(" %d | sfimage=exclamationmark.triangle.fill color=#d0021b" % n)
elif "paused" in healths:
    print(" | sfimage=pause.circle.fill color=#e0a000")
elif "ok" in healths:
    print(" | sfimage=arrow.triangle.2.circlepath color=#2e7d32")
else:
    print(" | sfimage=arrow.triangle.2.circlepath color=#9aa0a6")

print("---")

if not projects:
    print("No registered projects | color=#888888")
    print("Register one: | size=11 color=#888888")
    print("cadence schedule register <path> | font=Menlo size=11 color=#888888")
    print("Refresh now | refresh=true")
    sys.exit()

for p in projects:
    glyph = GLYPH.get(p["health"], "?")
    flags = []
    if not p["scheduled"]:
        flags.append("not scheduled")
    if p["paused"]:
        flags.append("PAUSED")
    team = ("  · " + p["team_name"]) if p.get("team_name") else ""
    suffix = ("   [" + ", ".join(flags) + "]") if flags else ""
    print("%s %s%s%s | font=Menlo size=13" % (glyph, p["name"], team, suffix))

    cells = []
    for s in STAGES:
        st = p["stages"].get(s)
        cells.append("%s=%s" % (s, st["result"] if st else "—"))
    print("--%s | font=Menlo size=11 trim=false" % "  ".join(cells))
    if p.get("last_activity"):
        print("--%s | font=Menlo size=11 trim=false" % p["last_activity"].replace("|", "│"))

    cfg = p["config"]
    if p["paused"]:
        print('--▶ Resume | bash="%s" param1=--config param2="%s" param3=resume terminal=false refresh=true' % (CAD, cfg))
    else:
        print('--⏸ Pause | bash="%s" param1=--config param2="%s" param3=pause terminal=false refresh=true' % (CAD, cfg))
    for s in ("triage", "spec", "build", "revise"):
        print('--Run %s now | bash="%s" param1=--config param2="%s" param3=run param4=%s terminal=true' % (s, CAD, cfg, s))
    print('--View logs | bash="%s" param1=--config param2="%s" param3=logs terminal=true' % (CAD, cfg))

print("---")
print("Open Linear | href=https://linear.app/")
print("Refresh now | refresh=true")
PY
