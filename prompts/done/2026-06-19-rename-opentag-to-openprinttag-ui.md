---
name: 2026-06-19-rename-opentag-to-openprinttag-ui
status: done
created: 2026-06-19
model: sonnet            # string sweep
completed: 2026-06-19
result: All user-facing "OpenTag" strings renamed to "OpenPrintTag" in Layout.tsx nav label, OpenTagCleanup.tsx (H1, subtitle, button titles, banner, table headers, unmatch option, help text, search label, newValue text), docs/opentag-cleanup.md H1, docs/README.md link labels. CHANGELOG [Unreleased] entry added. TypeScript check and tests green. No filename/route/identifier changes.
---

# Task: Rename the UI "OpenTag" → "OpenPrintTag"

The project name is **OpenPrintTag**; the API is already `/openprinttag/*`, but the UI still
says "OpenTag". Sweep the **user-facing strings** only. Do NOT rename component files, routes,
config keys, extra-field names, TS identifiers/types, the API, or the docs filename/slug.

## What to change (verified inventory — file:line)

- **Nav/sidebar:** `frontend/src/components/Layout.tsx:224` — `label: 'OpenTag Cleanup'` →
  `'OpenPrintTag Cleanup'`. **Keep** `to: '/opentag-cleanup'`.
- **`frontend/src/pages/OpenTagCleanup.tsx`** user-facing strings: H1 `:1915`, subtitle `:1918`,
  button titles `:1933` / `:1946` / `:1988`, banner `:1969`, td title `:352`, unmatch option
  `:381`, help text `:404`, manual-search link `:451` + label `:456`, table header `:530`,
  `newValue` user text `:601`, table header `:941`, button `:1145`, body `:1153`, and
  `actionLabel="Apply OpenTag writes"` `:1910`. Replace "OpenTag" → "OpenPrintTag" in each.
  (File-header comments are optional/non-user-facing.)
- **Docs:** `docs/opentag-cleanup.md:1` H1 title → "OpenPrintTag Cleanup tool". `docs/README.md:14`
  link label. (Optional: the `docs/opentag-matching.md` label at `README.md:15`.)

## Do NOT change
- Component filename `OpenTagCleanup.tsx`, route `/opentag-cleanup` (`App.tsx`, `Layout.tsx`),
  the docs **filename/slug** `opentag-cleanup.md` (it's the docs route + referenced from many
  docs + the in-app `learnMoreHref="/docs/opentag-cleanup"`), all API routes (`/openprinttag/*`),
  client wrappers, TS types/identifiers (`OpenTagCandidate`, `getOpenTagMatches`, …), config
  keys, and extra-field names (`openprinttag_*`).

## Before you start / working tree
Read the cited files; `git status --porcelain` (build on current `dev`).

## Tests
`cd frontend && npx tsc --noEmit && npm test` green (update any test asserting the old label,
e.g. a nav/title test if present). Add a `CHANGELOG.md` `[Unreleased]` line.

## When done
Update frontmatter, `git mv` to `prompts/done/`, propose ONE `refactor:`/`docs:` commit (specific
paths), present list + one-liner, STOP. Branch `dev`, never `main`, never push.
