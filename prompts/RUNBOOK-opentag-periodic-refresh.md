---
name: RUNBOOK-opentag-periodic-refresh
status: permanent        # RUNBOOK — recurring procedure, NOT moved to done/ when run
created: 2026-06-11
updated: 2026-06-11      # finalized after matcher v2 shipped
model: any
---

# RUNBOOK: Periodically refresh OpenTag mappings as new filaments/colors are added

> **This is a permanent runbook, not a one-shot task. Do NOT move it to `prompts/done/`.**
> Run it from time to time to pull the latest OpenPrintTag data and re-match. The OpenPrintTag
> dataset grows fast (1000+ spools added in a single week as of 2026-06-11), so new
> brands/colors/finishes/modifiers appear regularly and existing matches drift.

## Why this matters
- **Dataset grows** → new materials to match against (better matches for already-tagged
  filaments, new candidates for unmatched ones).
- **Lexicon must re-mine** → matcher v2 mines modifier/color lexicons FROM the dataset. New
  descriptors (e.g. a new finish or marketing modifier) are only recognized if the lexicon
  re-mines on refresh. Verify the refresh path bumps/recomputes the lexicon (the matcher-v2
  cache uses `lexicon_version` + recompute-on-fetch — confirm it fires).

## Procedure

1. **Refresh the dataset.** Click **Refresh dataset** on the OpenTag Cleanup page
   (or `POST /api/openprinttag/refresh`). The dataset banner updates with a new
   material count and timestamp. The lexicon is automatically re-mined from the new
   materials and saved alongside them in `opentag_cache.json` — no manual step needed.
2. **(Optional) Re-mine review.** Run `python scripts/dump_lexicon.py` to inspect the
   newly mined modifier/color vocabularies. If an important descriptor was missed (e.g.
   a new finish word used by a large brand), add it to `MODIFIER_SEED` or `BASE_COLORS`
   in `backend/app/core/opentag_lexicon.py`, bump `LEXICON_VERSION`, and the next
   refresh or cache warm-load will re-mine automatically.
3. **Reprocess matches.** The page reloads matches automatically after a refresh. If you
   want to reprocess without downloading again (e.g. after adding a vendor alias), click
   **Reprocess records**.
4. **Work two buckets:**
   - **Updates available** — the amber banner ("N filaments have updated OpenPrintTag
     values") lists already-tagged filaments whose dataset values drifted. Click
     **Review updates**, select the ones you want, and **Apply selected**. Filaments
     marked "Ignore future updates" do not appear here.
   - **Unmatched** — confidence &lt; 30% filaments listed at the bottom of the main
     review page. For ones now covered by a new dataset entry, use the per-filament
     candidate dropdown or click **Search OpenTag manually…** to find the right entry.
5. **Apply** writes `openprinttag_slug`/`openprinttag_uuid` extras and reviewed data
   fields to Spoolman; the identity keys also flow to the linked FDB `settings{}` bag.
   The ongoing sync engine keeps FDB identity current after that.
6. **This runbook stays in `prompts/`** — nothing to move to `done/`.

## Cadence
Manual, "from time to time" (e.g. monthly, or after a known large OpenPrintTag drop).
Consider whether to wire this to the `/schedule` (cron routine) or `/loop` mechanism later —
out of scope until the manual runbook is proven.

## Cross-refs
- `docs/opentag-cleanup.md`, `docs/opentag-matching.md` (matcher v2), `docs/spoolman-writes.md`.
- The "ignore future updates" flag (`openprinttag_ignore` Spoolman extra) suppresses a
  filament from the updates bucket — respect it.
