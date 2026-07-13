# The Bulk Import Wizard

The wizard pairs your Spoolman and Filament DB records: it links what already matches,
creates what's missing, and writes the cross-reference IDs both systems use from then on.
It is **re-runnable** — already-linked records are skipped, so you can run it again any
time you add a batch of new filaments.

Decisions made in the wizard persist in the bridge database, so you can leave and come back
mid-flow. Nothing is written to either upstream system until the final Execute step, which
is gated behind the backup dialog.

> **Before you start (Spoolman → Filament DB):** choose a
> [variant parent mode](variant-parent-mode.md) in Settings. The wizard refuses to preview
> or execute in this direction until you do.

## Navigation

Every wizard step renders a **Back / Next** action bar at both the **top and bottom** of the
page. This means you never have to scroll to find the nav buttons on long steps. The Execute
step's forward button is red (destructive action); the Step 3 Matches bar also includes a
**↻ Rescan** button. Terminal/result views (Execute result, OpenTag done) show no nav bar.

## Step 1 — Connectivity

Verifies both APIs are reachable and shows versions and record counts. Below-minimum
version warnings appear here. You can't continue while either system is unreachable.

## Step 2 — Direction

Choose what this *import run* does: bring Spoolman data into Filament DB, or Filament DB
data into Spoolman. This is a one-time import direction only — ongoing sync direction and
conflict policy live in Settings and are configured separately.

## Step 3 — Matches

The bridge reads both databases and matches filaments:

- Records already linked by a cross-reference are matched automatically at 100%.
- Everything else is fuzzy-matched on vendor + name + color (case, whitespace, and
  hyphen differences are normalized).

Review the result in a single table you can group (by status, material, or brand), sort,
search, and filter. Per row:

- **Matched** — checked rows will be linked; uncheck to skip.
- **Ambiguous** — pick the right Filament DB candidate, or choose create/skip.
- **Unmatched (SM)** — checked rows will be created in Filament DB.
- **Unmatched (FDB)** — in the **Filament DB → Spoolman** direction these are per-record
  **"create in Spoolman"** picks (checkboxes start unchecked — tick the ones to import; only
  ticked filaments are created, the rest are skipped). In the Spoolman → Filament DB
  direction they're informational (Filament DB records with no Spoolman counterpart).
- **Master / Parent** (purple) — bridge-owned container parents; nothing to do here (they
  never sync to Spoolman directly — only their colour variants do).

Tri-state checkboxes on the header and group rows bulk-include/exclude. **Rescan**
re-reads both systems (e.g. after you fix something upstream) and prunes decisions for
records that disappeared. An **OPT** badge marks filaments already tagged by the
[OpenTag cleanup tool](opentag-cleanup.md).

## Step 4 — Variances (Spoolman → Filament DB)

This step decides the *structure* of what gets created: which colors become variants of
which line, and with what shared properties.

- **Variant groups** are suggested by clustering included filaments on
  vendor + material + finish line. The finish token (silk, matte, CF, …) comes from the
  configurable keyword list, so "PLA Silk Red" never lands in the plain-PLA group.
- Each group has a suggested **master** (most spools wins) — change it with the radio
  button. Members whose print properties conflict with the master are pre-flagged
  **suggested standalone**; you can move members between groups, pull them out as
  standalone, build manual groups from standalone rows, or **Ignore** a filament entirely
  (removes it from this import).
- If an existing Filament DB parent line matches a group, choose **attach** (new colors
  become variants of your existing parent) or **create new parent**.
- **One tare per group** — the master's empty-reel weight applies to all members, because
  Filament DB stores one tare per filament. When Spoolman has no `spool_weight` for a
  filament, the tare field is **blank and required** (red border, `required` badge) — the
  "Save & Next" button stays disabled until every tare is filled. Standalone filaments get
  their own tare field with the same gating. No 200 g default is ever written.
- **Reconcile conflicting properties** — when group members disagree on type, density,
  diameter, temps, or spool weight, pick the canonical value (master's, any member's, or
  manual). The chosen values seed the Filament DB records *and* are written back to every
  Spoolman filament in the group at execute, so both systems agree from day one.

In the Filament DB → Spoolman direction this step instead shows existing FDB variant
groups and a per-spool weight-conversion review.

## Step 5 — Preview

A read-only dry run of exactly what Execute will do, computed by the same planner Execute
uses (the two cannot drift):

- Create/match counts for filaments and spools.
- **Name collisions** — incoming names that clash with existing Filament DB records or
  with each other. Container-name collisions get an inline **rename** box and a
  **skip cluster** action; other collisions link back to Variances to fix grouping.
  Anything left colliding fails per-record at execute (the batch continues).
- **Empty/archived spools** — depleted (`remaining ≤ 0`) or archived Spoolman spools.
  The *Never import empties* setting governs both: when off (default), all spools import
  including empty/archived ones; when on, spools with `remaining ≤ 0` are skipped.
  **Archived spools always import as retired FDB spools** (only the spool is retired; the
  filament is always a normal, non-retired filament). Each archived entry shows an
  "archived → imports as retired" tag in the Preview panel.
- **Missing tare** — spools with no known tare that need user input. This flag is now a hard block: Execute is rejected (422) if any tare is still unresolved.
- **Variant groups** — the parent/variant tree about to be created.
- **Planned writes** — a field-level list of every write, filterable by target system.

## Step 6 — Execute

The only step that writes. Gated behind an explicit confirmation and the backup dialog.

What it does, in order: creates container parents (generic-container mode), creates/links
masters and standalones, creates variants with `parentId`, applies the Spoolman reconcile
write-backs and finish-tag extras, merges OpenTag identity into Filament DB where present,
then creates spools (weight, location — found-or-created by name — and purchase/opened
dates carried over) and writes the cross-reference IDs on both sides.

At every `FilamentMapping` creation site, Execute stores an **identity blob**
`{vendor, name, color_hex, material}` on the mapping. This allows Synced Records to
display spool-less filaments (filament-only rows) with meaningful labels before any
snapshot has been taken, and provides the data the conflict filament-suggestions endpoint
needs to rank candidates. The sync engine opportunistically backfills this blob for legacy
mappings created before this feature shipped.

Failures are **per-record**: a name collision or API error records a failed row and the
run continues. The result view puts **failures first** (red banner with per-record reason),
then a full table of everything created, updated, and skipped.
Each summary counter (Created / Updated / Skipped / Failed) also shows a filament/spool
split (e.g. "2f / 5s") so it's clear how many filament pairs versus individual spools
were affected.

`wizard_completed` flips on any run with at least one success (**partial success** counts),
or on a clean zero-failure run (including an empty "nothing to import" run). A **total
failure** (0 successes, ≥1 failure) leaves the flag false so the user must re-run.

### Persistent Failure Report

Every execute run (that is not a fatal 502/422/409) persists a `wizard_last_run` blob
with full per-record detail. The Dashboard shows a **yellow failure banner** when the last
run had failures (`wizard_last_failures > 0` in the sync status). Clicking "Review
failures" opens the **Wizard Import Report** page (`/wizard/report`), which renders
failures-first and includes a **Re-run wizard** button.

Re-running the wizard retries still-failed records. Already-imported records are skipped
(idempotent), so nothing is duplicated. As failures succeed on re-run, the failure count
drops to 0 and the Dashboard banner disappears.

### Idempotent re-runs — find-or-attach on 409

Execute is safe to re-run. When a `generic_container` create 409s because the record
already exists in Filament DB, Execute performs a *find-or-attach* instead of failing:

- **Container 409**: searches the live FDB filament list by the container's display name
  (case-insensitive; prefers a record with `parentId == null`). If found, the cluster
  attaches to that existing container — no failure recorded.
- **Variant/standalone 409**: searches by the intended variant name (prefers `parentId`
  matching the cluster's container). If found, links to the existing record and patches
  `parentId` if needed — no failure recorded.

This means a second Add for a record that was already imported produces **zero failures**
and the conflict resolves. A genuinely new record (no existing FDB match by name) still
creates fresh as before. The tie-break rule for name lookups: prefer the record whose
`parentId` matches the expected container for variants, or prefer `parentId == null` for
containers. First match wins among remaining ties.

Created Filament DB names always include vendor + material (+ finish) + color — e.g.
"Hatchbox PLA Light Blue" — so bare Spoolman color names ("Light Blue", "Beige") can't
collide across lines.

## After the wizard

1. Review per-category sync **direction and conflict policy** in Settings.
2. Run a **dry run** from the Dashboard and read the plan.
3. **Enable auto-sync** (Dashboard or Settings → Scheduler & Logs).
