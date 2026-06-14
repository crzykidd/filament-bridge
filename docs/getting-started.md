# Getting started

This guide explains **why filament-bridge exists**, helps you pick **one of two ways to
use it**, and walks you through the first run for each. If you just want the deployment
command, see [Quick start](../README.md#quick-start-docker) in the README; come back here
to decide *how* to onboard your data.

---

## Why this exists

[Filament DB](https://github.com/hyiger/filament-db) and
[Spoolman](https://github.com/Donkie/Spoolman) each solve a different half of the filament
problem, and most of us end up wanting both:

- **Filament DB** is where material *profiles* live well — slicer integration, per-printer
  calibration, material-science properties, NFC tags, and the ability to pull canonical
  filament data from [OpenPrintTag](https://openprinttag.org).
- **Spoolman** is where the *print floor* lives — OctoPrint, Moonraker/Klipper, and Home
  Assistant all talk to it directly, and it decrements spool weight in real time during
  prints.

This bridge was built out of a real migration. The goal was to move filament management
into Filament DB — but first the existing spool data had to be **cleaned up to a real
standard** (OpenPrintTag) and carried over, *and* the Spoolman side had to keep working,
because OctoPrint and the Home Assistant integrations weren't going anywhere. That second
requirement is the important one: this isn't a one-time export. As long as prints keep
decrementing spools in Spoolman, the two systems need to **stay in sync** — which is why
the bridge does continuous, two-way sync with conflict resolution, not just an import.

So filament-bridge does two jobs:

1. **Onboard** your existing Spoolman inventory into Filament DB (optionally cleaning it
   against OpenPrintTag on the way).
2. **Keep the two in sync** afterward — weights, material properties, new spools — with
   conflicts queued for you instead of silently resolved.

---

## Pick your path

There are two ways to onboard. They differ only in **how much you clean up before
importing** — both end with the two systems linked and syncing.

### Path A — Just bridge them

> *"Set it up, point it at both systems, and create my filaments and spools in Filament DB
> from what's already in Spoolman."*

The Bulk Import Wizard matches your Spoolman filaments and spools, builds the Filament DB
variant hierarchy, and creates the records. You're up and syncing in minutes. Names and
data come over **as they are in Spoolman today** — warts and all.

**Choose this if** your Spoolman data is already clean enough, or you'd rather tidy names
later, or you just want sync working now.

### Path B — Clean up against OpenPrintTag first

> *"Do a little work first: match my current spools against OpenPrintTag — which stamps the
> OpenPrintTag ID onto each Spoolman filament and renames them to a clean standard — then
> import into Filament DB carrying that ID, so Filament DB can keep pulling canonical
> updates from OpenPrintTag later."*

You run the **OpenTag cleanup tool** *before* the import. For each Spoolman filament it
finds the best OpenPrintTag match, you review and confirm, and the bridge writes the
canonical fields plus the `openprinttag_slug` / `openprinttag_uuid` identity back to
Spoolman. Then you run the wizard — now the import carries those identifiers into Filament
DB, so Filament DB recognizes each filament's OpenPrintTag identity and can refresh it from
the source going forward.

**Choose this if** you want a clean, standardized catalog and the long-term benefit of
Filament DB staying current from OpenPrintTag. It's a little more up-front review for a
much tidier result.

| | Path A — Just bridge them | Path B — Clean first |
|---|---|---|
| Up-front effort | Minimal | Per-filament review pass |
| Names / data | As-is from Spoolman | Standardized to OpenPrintTag |
| OpenPrintTag identity in Filament DB | No | Yes (slug + UUID stamped) |
| Filament DB can pull future updates | No | Yes |
| Best for | "Get me synced now" | "Get me a clean catalog" |

> You can also do a hybrid: bridge first (Path A), then run the OpenTag cleanup later. The
> tool is re-runnable. Doing it **before** the first import is just cleaner because the
> standardized names and IDs land in Filament DB from the start instead of being changed
> after the fact.

---

## Before you start (both paths)

1. **Have both systems running** and reachable, on supported versions — Filament DB
   **≥ 1.33.0**, Spoolman **≥ 0.22.0**. Sync is hard-gated below these (see
   [Prerequisites](../README.md#prerequisites)).
2. **Deploy the bridge** — [Quick start](../README.md#quick-start-docker). It needs only
   `FILAMENTDB_URL` and `SPOOLMAN_URL`.
3. **Set an admin password** on first visit (auth is on by default).
4. **Back up all three systems.** The wizard and OpenTag apply both *write* to your live
   data. The pre-write dialog offers one-click Spoolman and Filament DB backups; see
   [Backups](../README.md#backups). Test against non-critical data first.

---

## Path A walkthrough — Just bridge them

1. **Pick a variant parent mode** (Settings). The wizard won't run Spoolman → Filament DB
   until you choose how flat Spoolman colors become Filament DB parent/variant lines —
   `promote_color` or `generic_container`. See
   [variant parent mode](variant-parent-mode.md).
2. **Run the Bulk Import Wizard** (Connectivity → Direction → Matches → Variances → Preview
   → Execute). Review the fuzzy matches, reconcile variant groups, and read the dry-run
   preview before you execute. Full step-by-step: [wizard.md](wizard.md).
3. **Execute.** Records are created in Filament DB and cross-linked back to Spoolman. A
   per-record report isolates any failures so one bad record never aborts the batch.
4. **Review the dry run**, then **enable auto-sync** (it's always OFF until you turn it on).
   Continue to [Ongoing sync](#ongoing-sync-both-paths).

---

## Path B walkthrough — Clean up against OpenPrintTag first

1. **Open the OpenTag Cleanup page.** The bridge pulls the OpenPrintTag dataset (cached 24 h)
   and scores every Spoolman filament against it.
2. **Review each filament.** You get the best match plus up to 5 alternates with a
   field-by-field comparison. Accept it, edit individual fields, mark fields "keep mine",
   switch candidates, or ignore the filament. Full semantics:
   [opentag-cleanup.md](opentag-cleanup.md).
3. **Apply.** The bridge writes the confirmed fields to Spoolman and stamps
   `openprinttag_slug` / `openprinttag_uuid` onto each filament — this is the standardized
   identity that makes the next step worthwhile.
4. **Now run the Bulk Import Wizard** (same as Path A, steps 1–4 above). Because your
   Spoolman filaments now carry the OpenPrintTag identity, the import brings clean names
   and those identifiers into Filament DB, so Filament DB can recognize and update each
   filament from OpenPrintTag later.
5. **Enable auto-sync** and continue below.

---

## Ongoing sync (both paths)

Once records are linked, the engine polls both systems on an interval and keeps the shared
surface in sync — **depending on your settings**. Two independent axes per data category
(Settings):

- **Direction** — `two_way`, or one-way either direction. Defaults: weight syncs
  Spoolman → Filament DB (so prints decrement both); material properties sync
  Filament DB → Spoolman; new spools sync two-way.
- **Conflict policy** — when the same field changes on *both* sides between cycles, what
  happens: `manual` (queue it for you — the default), or an automatic winner.

This is what closes the loop with the rest of your stack: OctoPrint / Moonraker / Klipper
keep decrementing spools in Spoolman, the bridge logs those decrements as **usage entries**
in Filament DB (preserving its audit trail — never raw overwrites), and any genuine
two-sided conflict waits for your decision on the Conflicts page. Nothing is auto-resolved
silently, and nothing is deleted upstream without your action.

Details: [sync-model.md](sync-model.md) · [conflicts.md](conflicts.md) ·
[spoolman-writes.md](spoolman-writes.md).

---

## Where to go next

- **[wizard.md](wizard.md)** — the Bulk Import Wizard in detail
- **[opentag-cleanup.md](opentag-cleanup.md)** — the OpenTag matcher and apply flow
- **[variant-parent-mode.md](variant-parent-mode.md)** — how flat Spoolman colors become
  Filament DB parent/variant lines
- **[configuration.md](configuration.md)** — every env var and runtime setting
- **[sync-model.md](sync-model.md)** — how a sync cycle actually works
