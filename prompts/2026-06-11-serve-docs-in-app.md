---
name: 2026-06-11-serve-docs-in-app
status: pending
created: 2026-06-11
model: sonnet
completed:
result:
---

# Task: Serve the docs/ markdown in-app at /docs/<slug>

User decision 2026-06-11: bridge documentation should be readable inside the app, not via
GitHub links. Today `frontend/src/pages/Settings.tsx` links to `/docs/variant-parent-mode`,
which the SPA fallback swallows (the router redirects unknown paths to the Dashboard) —
a dead link. Make `/docs/<slug>` a real, rendered docs viewer.

## Design

1. **Ship the markdown in the image.** In the `Dockerfile`, copy the repo `docs/` directory
   into the static tree, e.g. `COPY docs/ ./static/docs-md/`. The existing SPA fallback in
   `backend/app/main.py` already serves real files under `static/`, so
   `GET /docs-md/variant-parent-mode.md` returns the raw markdown with no backend changes.
   (Verify the fallback's `full_path.startswith("api")` guard doesn't interfere — it won't.)
2. **Dev mode:** in `frontend/vite.config.ts`, serve the repo docs during development so
   the viewer works under `npm run dev` — simplest is a tiny vite plugin or
   `server.fs`/middleware that maps `/docs-md/*.md` → `../docs/*.md` (or use
   `publicDir`-style static serving via a plugin). Keep it minimal; a ~15-line
   `configureServer` middleware reading the file from `../docs` is fine.
3. **Docs viewer route.** Add `frontend/src/pages/DocsViewer.tsx` and a router entry
   `docs/:slug` in `App.tsx` (inside the Layout so the sidebar stays). The page:
   - fetches `/docs-md/${slug}.md` (slug sanitized: `[a-z0-9-]+` only — reject anything
     else with the not-found state),
   - renders it with **`react-markdown` + `remark-gfm`** (new deps — approved; pin normal
     caret ranges, and double-check they don't drag in a vite/esbuild peer bump — the
     repo pins vitest ^2.x for vite-5 compatibility, do not upgrade vite/vitest),
   - styles with Tailwind typography-ish manual classes (NO @tailwindcss/typography
     dependency unless trivial — manual `prose`-like classes on the rendered elements via
     react-markdown `components` map are fine: headings, tables, code blocks, links),
   - rewrites relative markdown links: `[x](configuration.md)` → `/docs/configuration`
     (react-router `Link` or plain href), anchors preserved; external links open in a new
     tab; images (none today) can be left as-is,
   - dark-mode aware, with a small "Docs" header and a link back to `/docs` index.
   - `/docs` (no slug) renders `README.md` from the docs dir (the docs index).
4. **Sidebar:** add a "Docs" nav item in `Layout.tsx` pointing at `/docs` (place it above
   Settings, separated like Settings is).
5. **Fix the Settings link** (`/docs/variant-parent-mode`) — it now works; just confirm it
   navigates in-app (use the router, not target=_blank, OR keep new-tab if simpler — your
   call, note it in decisions.md).
6. **README/docs cross-links:** no change needed — repo-relative links keep working on
   GitHub, and the viewer's link rewriting handles them in-app.

## Tests

- Frontend: a DocsViewer test — renders fetched markdown (mock fetch), rewrites a
  relative `.md` link to `/docs/<slug>`, shows not-found state on 404/invalid slug.
- `npm test` + `tsc --noEmit` clean; `npm run build` succeeds.
- Backend suite unaffected but run it anyway.
- Sanity: `docker build` is NOT required to pass in this environment, but eyeball the
  Dockerfile COPY ordering (docs copy should sit with the static copy so layer caching
  stays sane).

## Before you start

- Read `backend/app/main.py` (SPA fallback), `frontend/src/App.tsx`, `Layout.tsx`,
  `vite.config.ts`, `Dockerfile`, and `frontend/package.json` (note the vitest/vite-5 pin).

## Working tree check

Run `git status --porcelain` first. If any of the files above are dirty beyond the
expected docs/prompts batch, stop and ask.

## When done

1. Update frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md` entry (serving approach, deps added, link-rewrite rule).
3. Propose ONE commit (`feat:` prefix, no Co-authored-by), on `dev`.
