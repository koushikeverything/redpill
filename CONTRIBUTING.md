# Contributing to Red Pill

Thanks for helping improve Red Pill. This is a small, focused project — a Claude
Skill plus a dependency-free Python engine — so the contribution loop is short.

## Repo layout

| Path | What it is |
|---|---|
| `.claude-plugin/` | Marketplace + plugin manifests that make this repo installable via `/plugin`. |
| `skills/redpill-inventory/` | **Source of truth** for the Skill. Edit here. |
| `skills/redpill-inventory/SKILL.md` | The workflow Claude follows. |
| `skills/redpill-inventory/references/formulas.md` | Authoritative formula + status spec. |
| `skills/redpill-inventory/references/report-template.md` | Report + demand-plan layout. |
| `skills/redpill-inventory/scripts/redpill_engine.py` | Deterministic calculator. |
| `scripts/build_skill.sh` | Packages `skills/` → `dist/redpill-inventory.skill`. |
| `scripts/sync_from_skill.sh` | Unpacks an edited `.skill` back into `skill/`. |
| `dist/` | Generated `.skill` package. |

## The one rule

**Never store or trust derived values — recompute everything from raw inputs every
run.** A defaulted lead time of `0`, or an `"N/A"` read as `0`, produces confidently
wrong statuses and phantom orders. If data is missing, quarantine the row and ask;
don't guess. This invariant is what makes Red Pill trustworthy.

## Make targets

```bash
make build                       # skill/ → dist/redpill-inventory.skill
make sync SKILL=path/to.skill    # unpack an edited .skill into skill/
make test                        # run the engine on examples/sample_mis.csv
make clean                       # remove generated computed.csv/summary.json/etc.
```

## Change → sync → commit

1. Edit files under `skills/redpill-inventory/` (or `make sync` a Claude-edited bundle).
2. `make test` to confirm the engine still runs and the numbers look right.
3. `make build` to refresh `dist/redpill-inventory.skill`.
4. `git add -A && git commit && git push`.

## Optional: auto-build on push

`.github/workflows/build-skill.yml` (if enabled) repackages the `.skill` on every push
that touches `skills/**`, so the downloadable bundle is always current. It commits the
rebuilt `dist/redpill-inventory.skill` back to the branch.

## Formula or status changes

If you change any formula or the status decision order, update **both**
`references/formulas.md` and the `SKILL.md` summary so the spec and the workflow never
drift apart. The evaluation order (OUT OF STOCK → INCOMING → CRITICAL → REORDER →
OVERSTOCK → OPTIMAL, first match wins) is load-bearing — a known Excel v1 bug came from
getting rules 1 and 2 out of order.

## Standing rules (v2)

- **The engine owns every number.** Parsing, validation, math, statuses, transfers, totals
  live in `redpill_engine.py` and are emitted via `report.json`. No calculation logic in
  SKILL.md, commands, or the cockpit template (the row-level what-if mirror is the one
  documented exception).
- **`make test` must be green before any commit.** The suite pins the SPEC.md §1 reference
  numbers exactly; if you intend to change behavior, change SPEC.md and the goldens in the
  same commit and say why.
