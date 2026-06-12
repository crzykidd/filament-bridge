# filament-bridge documentation

Start with the top-level [README](../README.md) for what the bridge is and how to deploy it.

## Using the bridge

| Doc | What it covers |
|---|---|
| [configuration.md](configuration.md) | Every environment variable and runtime setting |
| [wizard.md](wizard.md) | The Bulk Import Wizard, step by step |
| [variant-parent-mode.md](variant-parent-mode.md) | `promote_color` vs `generic_container`, container naming, collision handling |
| [conflicts.md](conflicts.md) | Conflict types and what each resolution actually does |
| [opentag-cleanup.md](opentag-cleanup.md) | The OpenTag matcher, review flow, and apply semantics |
| [opentag-matching.md](opentag-matching.md) | OpenTag v2 scorer internals: token decomposition, mined lexicons, scoring weights, worked examples |
| [security.md](security.md) | Auth model, API token, lockout recovery |
| [migration-spoolman-to-filamentdb.md](migration-spoolman-to-filamentdb.md) | One-time manual migration guide (CSV-based, without the bridge) |

## How it works / reference

| Doc | What it covers |
|---|---|
| [sync-model.md](sync-model.md) | The sync engine: cycle anatomy, passes, snapshots, anti-ping-pong invariants, version gating |
| [spoolman-writes.md](spoolman-writes.md) | Every field the bridge writes to Spoolman, and when |
| [version-update-check.md](version-update-check.md) | Version badge, GitHub update check, dev channel builds |
| [prd.md](prd.md) | The full product spec (functional requirements) |
| [decisions.md](decisions.md) | The decision log — why things are the way they are |

`wizard-redesign.md` and `reconcile-backlog.md` are historical design documents kept for
context; `decisions.md` is authoritative where they disagree.
