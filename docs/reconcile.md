# Reconcile

The **Reconcile** page (nav: *Reconcile*, route `/reconcile`) is a **read-only** cross-system
report. It compares every filament in Spoolman against every filament in Filament DB and shows
you, at a glance, what is paired and what is not — without changing anything in either system.

Use it to answer "did the two systems actually line up?" after an import, or to find filaments
that exist on only one side. It writes nothing, links nothing, and resolves nothing — acting on a
missing item is the [Bulk Import Wizard](wizard.md)'s job.

## What it shows

The report runs the **same matcher the wizard uses** (vendor + name + color, plus any existing
cross-reference) and sorts every filament into four buckets, each with a count badge:

| Bucket | Meaning |
|---|---|
| **Matched** | Filaments paired on both sides — either by a stored cross-reference (badge **linked**) or by a fresh name match (badge **name match**). |
| **Only in Spoolman** | Spoolman filaments with no Filament DB counterpart. |
| **Only in Filament DB** | Filament DB filaments with no Spoolman counterpart. Master / container-parent filaments are **excluded** — they have no Spoolman counterpart by design and should never look "missing". |
| **Ambiguous** | One Spoolman filament that matches **multiple** Filament DB candidates. Each candidate is listed with its ID so you can tell them apart. |

A summary header shows the totals: Spoolman filament count, Filament DB filament count, the matched
count, and the count in each unmapped/ambiguous bucket (missing counts are amber, ambiguous red).

Each row carries a **spool count and rolled-up weight** for its side, a variant-of annotation for
Filament DB variants, and [deep links](upstream-apis.md#deep-links-ui-requirement) that open the
record in each upstream system in a new tab.

## How to use it

1. Open **Reconcile** and click **Refresh** to run the report (it fetches on demand — nothing runs
   in the background). A *Loading…* state shows while both systems are queried.
2. Read the buckets:
   - **Only in Spoolman / Only in Filament DB** — these filaments exist on one side only. To bring
     a missing filament across, use the **Bulk Import Wizard** (the page footer points you there).
   - **Ambiguous** — the matcher can't safely auto-pair these. Resolve them by importing through
     the wizard, which lets you choose the right target.
   - **Matched** — no action needed. The **linked** vs **name match** badge tells you whether the
     pair is backed by a stored cross-reference or only by a name heuristic.

Because it is read-only, running Reconcile is always safe — it never mutates upstream data or the
bridge's mappings.

## API

- `GET /api/reconcile` → `ReconcileResponse` (summary + `matched`, `only_in_spoolman`,
  `only_in_filamentdb`, `ambiguous` arrays). Auth-gated like the rest of the app.

See also: [wizard.md](wizard.md) (importing missing filaments), [sync-model.md](sync-model.md)
(how ongoing pairing works), and the historical design notes in `reconcile-backlog.md`
(`decisions.md` is authoritative where they disagree).
