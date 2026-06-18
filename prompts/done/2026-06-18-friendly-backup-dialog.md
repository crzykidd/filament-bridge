---
name: 2026-06-18-friendly-backup-dialog
status: done
created: 2026-06-18
model: sonnet            # focused frontend change
completed: 2026-06-18
result: >
  BackupSafetyDialog made unconditionally friendly (no checkbox, indigo Continue button).
  DebugConfirmDialog created for the two Danger-Zone debug clears with strict gate preserved.
  BackupButtons extracted as shared sub-component. All 84 tests green; tsc clean.
---

# Task: Make the backup dialog friendly; move debug confirms to their own modal

Tone down the "beta"/threatening backup gate for normal product actions — keep the optional
DB-backup buttons, drop the mandatory "I backed up" checkbox, soften the copy/styling. The two
**debug** clears keep their strict confirm, moved to a dedicated modal so the shared dialog can
be unconditionally friendly.

## Decisions already made with the user

- `BackupSafetyDialog` becomes **unconditionally friendly**: no acknowledgement checkbox,
  Proceed always enabled, softened copy (drop the amber "Beta feature" tag), neutral (not red)
  primary button. **Keep** the one-click "Back up Spoolman / Back up Filament DB" buttons as an
  optional step ("nice option to back up before proceeding").
- The **two Settings Danger-Zone debug clears** get their **own confirm modal** (separate
  component), preserving their current strict behavior — leave debug alone. The other debug
  confirms (`window.confirm` reset-bridge, the bespoke full-reset modal) stay untouched.

## Verified facts (from audit — file:line)

- Component: `frontend/src/components/BackupSafetyDialog.tsx` (props `:13-18`). The gate:
  `acknowledged` state `:35`; `canProceed = smState==='ok' || fdbState==='ok' || acknowledged`
  `:40`; checkbox UI `:244-254` (label "I've backed up my data (or accept the risk)" `:252`);
  Proceed `disabled={!canProceed}` `:269`. "Threatening" copy: title `:116`, amber "Beta
  feature" subtitle `:118-121`, red bold Proceed button `:266-273`. Backup buttons + states
  (KEEP): Spoolman `:42-58`/`:134-174`, Filament DB `:60-76`/`:187-227`, mongodump copy
  `:20-21`/`:229-240`.
- **Five call sites** (the surprise — only 3 are "real" product gates):
  1. Wizard Execute — `frontend/src/pages/Wizard/Step6Execute.tsx:212-217` (`Run initial sync`).
  2. OpenTag Apply — `frontend/src/pages/OpenTagCleanup.tsx:1902-1907` (`Apply OpenTag writes`).
  3. Enable auto-sync — `frontend/src/pages/Dashboard.tsx:143-148` AND
     `frontend/src/pages/Settings.tsx:602-607` (`Enable auto-sync`).
  4. **DEBUG** clear cross-refs — `Settings.tsx:608-613` (`Clear Filament DB references from
     Spoolman`), triggered in the Danger Zone at `:1300`.
  5. **DEBUG** clear OpenTag ids — `Settings.tsx:614-619` (`Clear Spoolman OpenPrintTag ids`),
     triggered at `:1324`.
- Backup API (unchanged): `client.ts:202-205` `backupSpoolman()` → `POST /backup/spoolman`,
  `backupFilamentDb()` → `POST /backup/filamentdb`. No backend changes in this task.
- Tests mock the dialog: `Step6Execute.test.tsx:31`, `Settings.test.tsx:37`,
  `Dashboard.test.tsx:34` — keep them green (update if props/imports change).

## What to do

1. **Friendly `BackupSafetyDialog`:** remove `acknowledged` state + the checkbox block + the
   acknowledge resets; `canProceed` → always true (Proceed always enabled). Reword the title +
   subtitle to drop "Beta feature" and the risk framing (e.g. "Back up first? (optional)" / "You
   can back up Spoolman and Filament DB before continuing."). Recolor Proceed from red→neutral/
   indigo, relabel to e.g. `Continue` / `{actionLabel}`. Keep the backup buttons + their
   loading/ok/error UI intact. Call sites 1–3 need no logic change.
2. **Debug confirm modal:** add a dedicated component for the two Danger-Zone clears that
   preserves today's strict gate — a clear warning, an acknowledgement checkbox, and a red
   confirm button. Keep the optional backup buttons for these (they're destructive clears) —
   to avoid duplicating that UI, consider extracting the backup-buttons block from
   `BackupSafetyDialog` into a small shared sub-component used by both. Repoint call sites #4
   and #5 (`Settings.tsx:608-619`) to the new modal. Behavior/strictness for debug must not
   regress.
3. Leave the `window.confirm` reset-bridge path and the full-reset inline modal
   (`Settings.tsx:620-656`) untouched.

## Before you start
- Read `BackupSafetyDialog.tsx` in full, the five call sites, `docs/` mentions of the backup
  safeguard (`docs/` — search "backup" / "safeguard"), and `CLAUDE.md` if it references it.

## Working tree check
`git status --porcelain`; build on current `dev`. List anything unexpected; ask.

## What to do — tests
- Friendly dialog renders with NO checkbox and an always-enabled Proceed; backup buttons still
  work (mock the API).
- The two debug clears still require acknowledgement before their (red) confirm fires.
- Existing mocked-dialog tests stay green.
- `npx tsc --noEmit` + `npm test`.

## Conventions to honor
- Doc updates ship in the SAME commit (`docs/` security/backup notes if any; `CHANGELOG.md`
  `[Unreleased]`; decision in `docs/decisions.md`). Conventional-commits `feat:` or `refactor:`.
  No `Co-authored-by:`. Branch `dev`, never `main`, never push.

## When done
1. Frontmatter (`status`/`completed`/`result`); `git mv` to `prompts/done/`.
2. Decision logged in `docs/decisions.md`.
3. Propose ONE commit (specific paths, never `git add -A`); present list + one-liner; STOP.
   Never push.
