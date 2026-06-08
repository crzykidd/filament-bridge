---
name: 2026-06-08-docker-nonroot-user
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-08
result: Dockerfile updated with non-root user 1000:1000, /data and /app chowned, PYTHONDONTWRITEBYTECODE set. Both compose files updated with user: "1000:1000". README.md and docs/configuration.md document named/bind/upgrade paths. docs/decisions.md entry added.
---

# Task: Run the container as non-root user 1000:1000 with writable /data

The image runs as root and never creates/owns `DATA_DIR=/data`. Run as uid:gid **1000:1000**
and make the data directory writable by that user.

## 1. Dockerfile (runtime stage)

In the Stage-2 runtime image, after copying the app code + static assets and before `CMD`:
- Create a non-root user/group with uid 1000 / gid 1000 (e.g.
  `groupadd -g 1000 app && useradd -u 1000 -g 1000 -m -s /usr/sbin/nologin app`).
- `mkdir -p /data` and `chown -R 1000:1000 /data` so the bridge can write the SQLite DB,
  `opentag_cache.json`, and `backups/`. Also `chown -R 1000:1000 /app` so Python can write
  bytecode/anything under the workdir (or set `ENV PYTHONDONTWRITEBYTECODE=1` to avoid the
  need — do both for cleanliness).
- Add `USER 1000:1000` before `CMD`.
- Pip install stays as root (installs to /usr/local, world-readable) — keep it BEFORE the
  `USER` line.

Note: a named `bridge-data` volume mounted at `/data` inherits the image's `/data` ownership
(1000:1000) on first creation, so it'll be writable. (Bind mounts need the host dir owned by
1000:1000 — documented below.)

## 2. Compose files

Add `user: "1000:1000"` to the `filament-bridge` service in BOTH `docker-compose.yml`
(standard) and `docker-compose.dev.yml` (so it's explicit/overridable; the Dockerfile already
sets it, but make it visible).

## 3. Docs

- `README.md` (Backups/Quick-start area or a short "Permissions" note) + `docs/configuration.md`:
  note the container runs as **1000:1000**. For a **named volume**, nothing to do. For a
  **bind mount** of `/data`, the host directory must be owned by 1000:1000
  (`chown -R 1000:1000 ./data`). Existing deployments that previously ran as root have a
  root-owned `/data` volume — they must `chown` it to 1000:1000 once (or recreate the volume)
  when upgrading.
- `docs/decisions.md`: container runs as non-root 1000:1000; `/data` is chowned in the image so
  named volumes are writable; bind mounts / pre-existing root-owned volumes need a one-time
  chown.

## Verification

- `docker build -t filament-bridge-test .` succeeds (run it if the docker CLI is available;
  otherwise review the Dockerfile carefully). If you can build+run, confirm the process is uid
  1000 (`docker run --rm filament-bridge-test id` → uid=1000) and that it can write to /data
  with a named volume.
- `docker compose -f docker-compose.yml config` and `... -f docker-compose.dev.yml config`
  still parse, now showing `user: "1000:1000"`.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md` as above.
3. Non-interactive subagent run: stage ONLY the files this task touched (Dockerfile, both
   compose files, README.md, docs/configuration.md, docs/decisions.md, prompt move) and commit
   on `dev` with one `chore:` message. Use a pathspec-scoped commit (a parallel agent edits
   backend/*.py concurrently; never `git add -A`). Retry once on index lock. Never push.
