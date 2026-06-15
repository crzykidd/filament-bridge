---
name: 2026-06-08-opentag-stamped-badge
status: completed        # pending | completed | failed
created: 2026-06-08
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-07
result: Added grey/orange OPT badge to FilamentCard header; tsc + build pass.
---

# Task: OpenTag cleanup — "already stamped" badge on the match header (grey / orange)

On each OpenTag Cleanup match card's main line, show a small badge indicating whether the
Spoolman filament already carries an OpenPrintTag id:

- **No badge** — the filament has no existing `openprinttag_uuid`.
- **Grey badge** — it has an `openprinttag_uuid` AND its data matches the OpenTag entry
  (in sync).
- **Orange badge** — it has an `openprinttag_uuid` but the data differs from OpenTag
  (drifted — re-applying would update it).

Frontend-only (`frontend/src/pages/OpenTagCleanup.tsx`) — the needed data is already in each
match/candidate's `fields`.

## Logic (per filament, using the currently-selected candidate)

The card already has `match.candidates` (or the top-level fields) where each field row has
`field`, `spoolman_value`, `opentag_value`. Define:
- `existingUuid` = the `spoolman_value` of the `extra.openprinttag_uuid` field row (the
  filament's CURRENT Spoolman value; non-empty ⇒ already stamped). Candidate-independent.
- `dataDiffers` = over the selected candidate's field rows, EXCLUDING the identity rows
  (`extra.openprinttag_slug`, `extra.openprinttag_uuid`), is there any row whose
  `spoolman_value` differs from `opentag_value` when **normalized** (lowercase + trim, and
  treat null/`""`/`—` as equal-to-empty, so hex-case or empty-vs-null don't false-trigger)?

Badge:
- no `existingUuid` → render nothing.
- `existingUuid` and not `dataDiffers` → grey badge.
- `existingUuid` and `dataDiffers` → orange badge.

## UI

- Place a small badge on the card header line (near the SM #id / confidence / dropdown).
- We don't have the OpenPrintTag logo asset — use a small tag/NFC-style icon or a compact
  pill labeled e.g. "OPT" / "tagged". Grey variant uses neutral gray (e.g. `bg-gray-100
  text-gray-500 border-gray-200`); orange variant uses amber (`bg-amber-100 text-amber-700
  border-amber-300`). Add a `title` tooltip: grey → "Already tagged in OpenPrintTag — in
  sync"; orange → "Tagged in OpenPrintTag — Spoolman data differs from OpenTag".
- Recompute when the selected candidate changes (so switching candidates re-evaluates
  `dataDiffers`). `existingUuid` stays the same.
- Match the existing Tailwind styling; keep it unobtrusive on the header row.

## Verification

- `cd frontend && npx tsc --noEmit && npm run build` — must pass.
- Reason through: a never-tagged filament shows no badge; a tagged filament whose
  material/density/color/temps/tags/name all match OpenTag shows grey; a tagged filament with
  any differing data field shows orange; selecting a different candidate updates the
  grey/orange state; hex-case-only or null-vs-empty differences do NOT turn it orange.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. No `docs/decisions.md` entry needed (trivial UI add) unless non-obvious.
3. Non-interactive subagent run: when tsc/build pass, stage ONLY the files this task touched
   (incl. prompt move) and commit on `dev` with one `feat:` message. Never `git add -A`.
   Never push.
