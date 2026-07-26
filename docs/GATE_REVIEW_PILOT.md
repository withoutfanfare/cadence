# Pilot decision briefs before expanding gate tooling

| Field | Value |
|---|---|
| Date | 2026-07-26 |
| Status | Active |
| Confidence | Medium |
| Revisit | 2026-08-02 |
| Scope | Cadence; Modern Printworks Linear project |
| Tags | cadence, linear, gate-review, decision-brief, pilot |

## Context

Tasks 1–3 of the [gate review cost plan](superpowers/plans/2026-07-25-gate-review-cost.md)
are implemented on `codex/gate-review-cost`: the brief renderer/parser, risk
scoring, and brief comments at the four normal loop hand-backs. Offline tests
pass, but live Linear, mobile, and real-PR behaviour remains unverified.

The existing menu bar lists resting issues and can grant the next gate, but it
does not fetch or display Linear comments. For now, Linear is the evidence
surface and the menu bar is the action surface.

## Options considered

### Expand the tooling now

- **Pros:** Adds queue ordering, batch gating, autonomous risk limits, a combined
  review screen, or direct menu-bar brief display immediately.
- **Cons:** Builds around assumed friction before the core brief has been tried
  on real work; risks adding software that the Linear and menu-bar flow already
  makes unnecessary.

### Run a one-week Modern Printworks pilot

- **Pros:** Tests the plan's central claim with the smallest current system and
  shows which remaining cost is real.
- **Cons:** Review still requires opening Linear, and convenience work remains
  deferred for a week.

## Decision

Run the decision briefs on the Modern Printworks Linear project for one week
before expanding the implementation. Use Linear to read each brief and the
existing menu bar or Linear label picker to grant the next gate.

Do not start Tasks 7 or 8, or direct menu-bar brief presentation, without pilot
evidence. Tasks 4 or 5 remain available earlier only if queue choice or batch
gating becomes an observed problem.

## Expected outcome

- A human can understand each normal hand-back from its five-line brief.
- The named uncertainty and `check_first` field make deeper review selective.
- Risk bands broadly match human judgement.
- Gate decisions spend less time waiting because opening the spec or diff is no
  longer the default.
- The pilot identifies the actual remaining friction: queue ordering, batch
  gating, phone access, autonomous risk, deeper review, or menu-bar presentation.

## Revisit checklist

On 2026-08-02, review:

- Were briefs posted successfully at the hand-backs exercised during the week?
- Were the three sentences specific, concise, and useful?
- Were risk bands credible, including sensitive paths and blocking reviews?
- Did decisions happen sooner or with fewer Linear/GitHub hops?
- Was opening Linear still the dominant cost?
- Which, if any, of Tasks 4–8 now has evidence behind it?
- Is a read-only brief panel in the menu bar justified?

## Outcome log

<!-- Append the 2026-08-02 review here. -->
