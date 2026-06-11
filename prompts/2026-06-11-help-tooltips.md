---
name: 2026-06-11-help-tooltips
status: pending
created: 2026-06-11
model: sonnet
completed:
result:
---

# Task: Add "?" help tooltips with local context across the UI

Give users in-place explanations: a small `?` icon next to settings/columns/controls that
shows a short, plain-English tooltip on hover/focus (and tap, on touch). The inventory
below was compiled from a full UI read on 2026-06-11; the docs it summarizes are
`docs/configuration.md`, `docs/sync-model.md`, `docs/wizard.md`, `docs/conflicts.md`,
`docs/opentag-cleanup.md`.

## 1. Build a shared `HelpTip` component

`frontend/src/components/HelpTip.tsx`:

- Renders a small circled `?` (e.g. 14px, `text-gray-400`, `border`, rounded-full) inline
  after a label. Props: `text: string` (plain text, may be multi-sentence) and optional
  `learnMoreHref` (renders a "Learn more ↗" link inside the tip, opens in a new tab).
- Tooltip on hover AND keyboard focus (`tabIndex=0`, `aria-describedby`); click/tap
  toggles it (so touch works); Escape/blur closes. Max width ~18rem, dark-mode aware
  (`bg-gray-800 text-gray-100` light / `bg-gray-700` dark, border, shadow, text-xs),
  positioned above the icon with a simple flip-to-below when near the viewport top is NOT
  required — keep it simple (above, `z-50`).
- No new dependencies — plain React + Tailwind, matching existing styling idioms.
- Keep all tooltip copy in the component call sites (no central registry needed), but keep
  the copy SHORT — 1–3 sentences, no markdown.

Where a sub-text paragraph already explains a control well, do NOT duplicate it with a
tooltip; the inventory below already accounts for this.

## 2. Inventory — where to add tips and what they should say

Copy is provided; tighten freely but keep the meaning. `→ docs` means pass
`learnMoreHref` pointing at the in-app docs viewer: `/docs/<slug>` (e.g. `/docs/sync-model`).
This depends on `prompts/2026-06-11-serve-docs-in-app.md` having landed — run that first;
if it hasn't landed, fall back to the GitHub blob URL and note it.

### Settings.tsx

| Control | Tip |
|---|---|
| Weight sync · Direction | "Which side's weight changes get copied to the other. One-way ignores changes on the locked side; two-way syncs both and can conflict." → sync-model |
| Weight sync · On conflict | "Used only in two-way mode when both sides changed between syncs. Manual queues it for you; the others pick a winner automatically." → conflicts |
| Material properties · Direction | "Covers material/type, density, diameter, temperatures, cost, color, and finish tags." → sync-model |
| Material properties · On conflict | "Newest-wins isn't available here — Spoolman doesn't timestamp filament edits." |
| New spools · Direction | "When an unmapped spool appears in one system, the bridge creates it in the other. Direction limits which side gets auto-created." |
| Weight sync threshold (g) | "Changes smaller than this are ignored, so net↔gross rounding doesn't cause endless tiny updates. Default 2 g." |
| Weight precision (decimal places) | "Decimal places used when comparing and writing weights." |
| Variant line keywords | already has good sub-text — add tip only with the extra bit: "Used by the wizard when grouping colors into variant lines. Changes apply to the next wizard run." |
| Manufacturer mappings | existing sub-text is good — tip: "Only affects the OpenTag Cleanup matcher, not sync." → opentag-cleanup |
| Color word mappings | existing sub-text is good — skip tooltip |
| Variant parent mode (header) | "How the wizard builds Filament DB's parent/variant tree from flat Spoolman filaments. Choose once before the first import; existing mappings are never changed." → variant-parent-mode |
| Container marker | existing sub-text is good — skip |
| Auto-sync enabled | "Runs a sync cycle on the interval below. Stays off until you enable it; enabling asks you to back up first." |
| Sync interval | existing warning is good — skip |
| Sync-log retention | existing sub-text good — skip |
| Never import empties | tip: "Applies to wizard imports only — the ongoing engine doesn't create records for depleted spools either way." |
| API token enabled | "Lets scripts call the bridge API with Authorization: Bearer or X-API-Key instead of a login cookie." → security |
| Debug mode | existing text good — skip |

### Dashboard.tsx

| Control | Tip |
|---|---|
| "Sync now" | "Runs one live sync cycle immediately — same as a scheduled cycle." |
| "Dry run" | "Computes everything a cycle WOULD do — creates, updates, conflicts — without writing anything. Safe to run anytime." |
| Counts cards (In Sync / Pending / Conflict / Unlinked) | one tip on the grid or per card: In Sync "both sides match the last-synced state"; Pending "linked but not yet baselined by a sync cycle"; Conflict "has an open conflict — see the Conflicts page"; Unlinked "spool mapping lost its filament mapping; relink or unlink in Synced Records" |
| Next sync | "Approximate — actual time comes from the scheduler." |

### SyncedRecords.tsx

| Control | Tip |
|---|---|
| "SM weight" header | "Net filament weight from Spoolman (reel excluded), as of the last sync." |
| "FDB weight" header | "Gross weight from Filament DB (filament + empty reel), as of the last sync." |
| "Hide empty spools" | "Hides spools with 0 g remaining in Spoolman." |
| Expanded detail grid | one tip near the grid: "Last-known values per side from the bridge's snapshots — '—' means the field hasn't been baselined by a sync yet." |

### Conflicts.tsx

| Control | Tip |
|---|---|
| Page banner | banner text already explains semantics — skip |
| Type filter chips | per-type tips optional; ADD one to the **Master divergence** chip: "A Spoolman value would override a setting this variant inherits from its Filament DB parent. Resolving applies your chosen action upstream." → conflicts |
| Bulk resolve "Use spoolman/filamentdb" | "Records the choice only — no values are written upstream. Make the actual edit in the system you chose, and sync propagates it." |

### Wizard

| Control | Tip |
|---|---|
| Step 2 direction cards | "One-time import direction for THIS run. Ongoing sync direction lives in Settings." |
| Step 3 confidence % | "Fuzzy match score on vendor + name + color. 100% = exact or already cross-referenced." |
| Step 3 OPT badge — has `title` already | upgrade to HelpTip only if trivial; otherwise skip |
| Step 3 "Master / Parent" status pill | "A parent record owned by the bridge (or an existing FDB parent). Nothing to do here — it never syncs directly." |
| Variances "Empty-reel tare (g)" | "Weight of the empty spool. Used to convert Spoolman's net weight to Filament DB's gross weight; one tare applies to the whole group." |
| Variances master radio | "The master becomes (or maps to) the Filament DB parent. Variants inherit its print settings." |
| Variances "suggested standalone" chip | "This member's print properties differ from the master's, so it may not belong in the group. Move it out or reconcile the values below." |
| Variances attach-to-existing banner buttons | "Attach: new colors become variants of your existing Filament DB parent. Create new: a separate parent is created for this group." |
| Preview flag cards | per-card tips: Name collisions "names that already exist in Filament DB or repeat within this import — rename, fix grouping, or they fail per-record"; Empty active "depleted but unarchived Spoolman spools"; Default tare "no reel weight found anywhere — 200 g assumed; fix per-group in Variances"; Variant groups "parent/variant trees this import will create" |
| Execute "tare overrides applied" | "Tare values you set in Variances; submitted with this run only." |

### OpenTagCleanup.tsx

| Control | Tip |
|---|---|
| Confidence badge | "Match score vs the OpenTag entry: material, brand, color name, color hex, and finish all contribute. Below 30% = unmatched." → opentag-cleanup |
| "Reprocess records" / "Refresh dataset" — have `title` attrs | leave as-is or upgrade; low priority |
| "keep mine" | "Skips this field when applying — your current Spoolman value stays." |
| "ignore match" | "Excludes this filament from the apply entirely." |
| OPT stamped badge — has `title` | skip |
| "Hide already-tagged" | "Hides filaments that already carry an OpenPrintTag UUID." |

## 3. Conventions

- Don't remove existing helpful sub-text; tooltips complement it for the denser surfaces.
- Keyboard accessible; no layout shift when the tip opens.
- `npm test` + `tsc --noEmit` clean. Add a small render test for `HelpTip`
  (shows on focus, hides on Escape).

## Working tree check

Run `git status --porcelain` first. A large uncommitted docs batch (README, docs/*,
CLAUDE.md, prompts/*) is expected — leave it alone. If the frontend pages above are
dirty, stop and ask.

## When done

1. Update frontmatter; `git mv` to `prompts/done/`.
2. Brief `docs/decisions.md` entry (component approach, copy-at-call-site choice).
3. Propose ONE commit (`feat:` prefix, no Co-authored-by), on `dev`.
