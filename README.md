# Cadence

Most automation does too little — pinging you with reminders — or too much,
quietly merging code you never read. Cadence sits in between. It runs a small
team of AI agents that pick up your Linear issues, triage them, write the spec,
build the change in an isolated branch, and open a draft pull request — then
stop and hand the decision back to you. Every gate between stages is yours to
grant. The agents do the legwork around the clock; you stay the one who says
"ship it".

Cadence is a human-gated agent loop for Linear projects. It moves issues through
four stages:

```text
triage -> spec -> build -> revise
```

The loops can run unattended, but authority stays with a person. Agents can tidy
issues, write specs, create draft PRs, and push revisions; they do not approve
their own work, grant the next gate, mark PRs ready, merge PRs, or act outside
the configured Linear project.

## What it does

| Loop | Trigger | What it does | Stops at |
| --- | --- | --- | --- |
| `triage` | No human gate | Fills missing metadata, flags stale work, proposes duplicate clusters | `agent:triaged` or `agent:needs-human` |
| `spec` | Human adds `agent:spec` | Writes a spec document and validates duplicate candidates | `agent:specced` |
| `build` | Human adds `agent:build` | Creates an isolated worktree, delegates code changes, runs gates, opens a draft PR | `agent:pr-open` |
| `revise` | Human adds `agent:revise` | Pushes review changes to the same draft PR | `agent:revised` |

Each loop consumes its trigger and leaves a "your move" label. A human decides
when to move an issue through the next gate.

### Lifecycle of one issue

The four stages above are a relay. Each agent does its part, then leaves a label
and waits for you to grant the next gate:

```text
triage   →  agent fills metadata, leaves `agent:triaged`          ·  you review
you      →  add `agent:spec`
spec     →  agent writes a spec document, leaves `agent:specced`  ·  you read it
you      →  add `agent:build`
build    →  agent codes in a worktree, opens a DRAFT PR,
            leaves `agent:pr-open`                                ·  you review the PR
you      →  merge it yourself — or add `agent:revise` for changes
revise   →  agent pushes fixes to the same PR, leaves `agent:revised`
```

Nothing advances without a human adding the next gate label. See
[docs/OPERATING.md](docs/OPERATING.md) for the day-to-day commands.

## Autonomous mode (opt-in)

Cadence can also run *without* a human granting each gate. Tag issues `agent:auto`
(or let the conductor pick them) and turn it on:

```bash
cadence autonomous on      # set AUTONOMOUS + schedule the advancer (hourly) and conductor (3-hourly)
cadence autonomous status  # show the flag and whether both jobs are loaded
cadence autonomous off     # reverse both — sets AUTONOMOUS=0 and unloads the jobs
```

The advancer grants gates on your behalf and the conductor decides what to work on
next, but the safety floor is unchanged: work still stops at a **draft** PR for you
to merge, and nothing acts outside the configured project. Off by default. Full
rollout guidance is in
[docs/OPERATING.md](docs/OPERATING.md#autonomous-mode-opt-in).

## Requirements

Cadence currently targets macOS for scheduled runs because it uses `launchd`.
Manual runs work anywhere with the required command-line tools, but the included
scheduler docs are macOS-specific.

You need:

- `bash`, `git`, and `python3`.
- A Linear personal API key.
- One orchestrator CLI on `PATH`: `claude`, `codex`, `kimi`, or `opencode`.
- Optional implementer CLIs if you choose them: `claude`, `kimi`, `opencode`, or `codex`.
- `gh` if you want the build loop to open or back-fill GitHub PR information.

There are no package dependencies to install for the engine itself; the Python
adapters use the standard library.

Lead loop providers are configured per stage with `cadence providers set`, which
updates `.env` for you. Use `cadence providers roles` to see what each slot
does, and see
[configuration provider examples](docs/CONFIGURATION.md#provider-switching-examples)
for all-Codex, mixed-provider, Kimi, and OpenCode examples.

## Quick Install

```bash
git clone https://github.com/withoutfanfare/cadence.git
cd cadence

mkdir -p "$HOME/.local/bin"
ln -s "$PWD/bin/cadence" "$HOME/.local/bin/cadence"

# Make sure this is in your shell startup file if it is not already.
export PATH="$HOME/.local/bin:$PATH"

cp .env.example .env
$EDITOR .env
cadence doctor
```

After `cadence doctor` passes, create the required Linear labels in one step:

```bash
cadence labels init
```

This creates the full `agent:*` label set on the team (and `Stale`). It is
idempotent — existing labels are left alone.

Then pause the system while you inspect the setup:

```bash
cadence pause
cadence status
```

When you are ready for one deliberate live triage run, resume, run it, then pause
again while you inspect the result:

```bash
cadence resume
cadence run triage
cadence pause
cadence logs triage
```

Important: `cadence run <stage>` is live. Triage is invoked with `--live`, and
`spec`, `build`, and `revise` write by default. A paused system skips manual runs
as well as scheduled runs, so resume only for the specific run you intend to make.

For the full walkthrough, including how to find Linear IDs and schedule the
loops, read [docs/INSTALL.md](docs/INSTALL.md).

## Documentation

Start with [docs/README.md](docs/README.md), or jump directly to:

- [Installation](docs/INSTALL.md) - step-by-step setup for a new machine.
- [Configuration](docs/CONFIGURATION.md) - every `.env` value explained.
- [Operating Cadence](docs/OPERATING.md) - day-to-day commands and recovery.
- [Architecture](docs/ARCHITECTURE.md) - gates, labels, state, and invariants.
- [Agent Labels](docs/LABELS.md) - the full Linear label vocabulary.
- [Implementers](docs/IMPLEMENTERS.md) - how build delegation works.

## Safety Model

Cadence is designed around three constraints:

- Project scope comes from `.env`; the engine contains no project IDs.
- Every loop checks the pause flag before doing work.
- Agents never set downstream gate labels or merge PRs.

Use `cadence pause` whenever you want all loops to stop immediately. It creates
`$CADENCE_STATE_DIR/runs/PAUSED`; deleting that file or running `cadence resume`
allows loops to run again.

## Licence

MIT - see [LICENSE](LICENSE).
