---
name: 2026-06-09-theme-light-dark-system
status: completed
created: 2026-06-09
model: sonnet
completed: 2026-06-09
result: >
  Delivered full theme infrastructure: Tailwind darkMode:'class', ThemeContext
  (light/dark/system modes, localStorage fb_theme, OS-preference live listener),
  pre-paint inline script in index.html to prevent flash, color-scheme CSS property,
  Appearance section in Settings, SidebarThemeToggle in Layout. Dark styling across
  all primary pages (Dashboard, Conflicts, SyncedRecords, SyncLog, Settings,
  Login, Layout, BackupSafetyDialog, ColorDisplay, StatusBadge) and Wizard shared
  chrome + Steps 1/2/6. Incremental polish in Step3Matches, StepVariances,
  StepNPreview, OpenTagCleanup outer chrome only. Build passes clean.
---

# Task: Theme modes — light, dark, and match-system

Add a user-selectable color theme (light / dark / system) to the filament-bridge UI. The app is
currently entirely light-styled (no Tailwind `dark:` variants, `darkMode` not configured). This task
delivers the THEME INFRASTRUCTURE plus dark styling across the shared layout and primary surfaces.
Full per-page dark polish is acceptable to land incrementally — but the app must look correct in
dark mode on the main surfaces, not half-broken.

## Working tree note
Ignore pre-existing untracked dotfiles and the unrelated `docker-compose.dev.yml` change; never stage
them. Run `git status --porcelain` first. NOTE: auth + version-check prompts may have already landed
on `dev` — build on top; don't undo them (you'll be adding a theme picker near their Settings/header
additions).

## Infrastructure

- **Tailwind:** set `darkMode: 'class'` in `frontend/tailwind.config.js`.
- **Theme setting:** three modes — `light` | `dark` | `system`. Persist the user's choice in
  `localStorage` (`fb_theme`, default `system`). Apply by toggling the `dark` class on
  `document.documentElement`:
  - `light` → no `dark` class.
  - `dark` → `dark` class.
  - `system` → follow `window.matchMedia('(prefers-color-scheme: dark)')`, and LISTEN for changes so
    it live-updates when the OS theme flips.
  - Apply the initial theme BEFORE first paint (a tiny inline script in `index.html`, or set the
    class in `main.tsx` before render) to avoid a light flash.
- Also set the CSS `color-scheme` on the root per theme so native controls (scrollbars, dropdowns,
  date/color pickers) follow — the app previously fixed exactly this for dark dropdowns; keep it.
- A small theme context/hook (`useTheme`) exposing the current mode + setter is fine.

## Theme picker UI
- A segmented control (Light / Dark / System) in **Settings** (a new "Appearance" section). Optional
  bonus: a quick theme toggle in the sidebar/header. Saving is immediate (no Save button needed —
  it's a client-side preference; it does NOT need to round-trip to the backend, though you may also
  persist it server-side via BridgeConfig if trivial — localStorage is sufficient and preferred).

## Dark styling (the real work)
Add `dark:` variants so these render correctly in dark mode. Work through the SHARED chrome first,
then the primary pages:
- **Shared:** `components/Layout.tsx` (sidebar, header, nav links, active states), the page
  background, common components (`StatusBadge`, `DeepLinks`, `BackupSafetyDialog`, `ColorDisplay`,
  any shared card/table wrappers).
- **Primary pages:** `Dashboard`, `Settings`, `Conflicts`, `SyncedRecords`, `SyncLog`,
  `OpenTagCleanup`, and the `Wizard/*` steps.
- Use a consistent dark palette: e.g. page `bg-gray-50 dark:bg-gray-900`, cards
  `bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700`, primary text
  `text-gray-900 dark:text-gray-100`, secondary `text-gray-600 dark:text-gray-300/400`. Keep indigo
  accents but ensure contrast in dark. Don't invert semantic colors (red/amber/green badges stay
  meaningful — just adjust backgrounds/contrast).
- It's fine to introduce a couple of shared Tailwind component classes (via `@layer components` in
  the stylesheet) for cards/inputs to avoid repeating long `dark:` chains everywhere — but don't
  over-abstract.
- If you cannot fully dark-style every deep/rare view in one pass, prioritize the shared chrome +
  the primary pages above, and LIST any views left for follow-up in your report (don't silently
  leave broken-looking pages without flagging them).

## Conventions / tests / done
- Frontend: `cd frontend && npm run build` (must pass). There aren't meaningful unit tests for this;
  rely on the build + a careful self-review that dark classes are paired with their light defaults.
- Backend: only touch backend if you choose server-side theme persistence (optional). If you do,
  `cd backend && python3 -m pytest`.
- Update `CHANGELOG.md` `[Unreleased]`. Update `CLAUDE.md` only if you add a setting.
- Commit prefix `feat:`. No `Co-authored-by:`. Branch `dev`, never `main`, never push.
- When done: frontmatter → completed; `git mv` to `prompts/done/`; decisions in `docs/decisions.md`.
  DO NOT `git commit` — report back file list, proposed commit message, build result, and the list of
  any views not yet dark-polished.
