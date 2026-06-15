---
name: 2026-06-08-entrypoint-chown-drop
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-08
result: Implemented. Dockerfile: gosu installed, USER directive removed, docker-entrypoint.sh copied+exec'd, ENTRYPOINT set. Both compose files: user: line removed. README + docs/configuration.md: Permissions section updated (auto-chown, no manual step needed, PUID/PGID override). docs/decisions.md: supersedes the prior USER 1000:1000 entry with entrypoint chown-then-gosu explanation. docker CLI unavailable in sandbox; reviewed by eye.
---

# Task: Self-healing /data permissions — entrypoint chowns then drops to 1000:1000 (gosu)

The container now runs as `USER 1000:1000`, but a pre-existing `bridge-data` volume created by a
root container is root-owned, so the app gets `sqlite3.OperationalError: attempt to write a
readonly database` at startup. Switch to the standard robust pattern: start as root, an
entrypoint `chown`s `/data`, then drops privileges to 1000:1000 via `gosu` and execs the app.
This auto-handles existing AND new volumes with no manual chown.

## Dockerfile (runtime stage)

- Install `gosu` in the runtime image: `apt-get update && apt-get install -y --no-install-recommends gosu && rm -rf /var/lib/apt/lists/*` (debian slim base). Keep the
  `groupadd -g 1000 app && useradd -u 1000 -g 1000 ...` user creation and `mkdir -p /data`
  (so fresh volumes start owned right), but **remove the `USER 1000:1000` directive** — the
  container must start as root so the entrypoint can chown a root-owned mounted volume.
- Keep `ENV PYTHONDONTWRITEBYTECODE=1`.
- Add an entrypoint script `docker-entrypoint.sh` at the repo root, COPY it into the image
  (e.g. `/usr/local/bin/docker-entrypoint.sh`), make it executable, set
  `ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]`, and keep the existing
  `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]` (the entrypoint
  execs `"$@"`).

## docker-entrypoint.sh (new, repo root)

```sh
#!/bin/sh
set -e
# Ensure the data dir is writable by the runtime user, then drop privileges.
# Allow override via PUID/PGID (default 1000:1000).
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
mkdir -p "${DATA_DIR:-/data}"
chown -R "${PUID}:${PGID}" "${DATA_DIR:-/data}" 2>/dev/null || true
# If already running as non-root (e.g. compose set `user:`), just exec.
if [ "$(id -u)" = "0" ]; then
  exec gosu "${PUID}:${PGID}" "$@"
else
  exec "$@"
fi
```
(POSIX `sh` — the base image has `/bin/sh`. Tolerate a read-only/odd FS with `|| true` so the
container still starts; if chown failed and we're root, gosu still drops to the user.)

## Compose files

- **Remove `user: "1000:1000"`** from the `filament-bridge` service in BOTH `docker-compose.yml`
  and `docker-compose.dev.yml` — the container must start as root for the entrypoint to chown;
  the entrypoint drops to 1000:1000 itself. (The script's `id -u` check keeps it working even if
  someone re-adds `user:`.)

## Docs

- `README.md` + `docs/configuration.md` Permissions note: the container starts as root only to
  fix `/data` ownership, then runs the app as **1000:1000** (override with `PUID`/`PGID`). No
  manual chown is needed — existing root-owned volumes are corrected automatically on start.
  Remove/replace the previous "one-time chown required on upgrade" instruction.
- `docs/decisions.md`: replaced the `USER 1000:1000` approach with an entrypoint chown-then-gosu
  drop so `/data` is always writable (handles pre-existing root-owned volumes); app still runs
  as non-root 1000:1000, PUID/PGID overridable.

## Verification

- If the docker CLI + network are available: `docker build -t fb-test .`,
  `docker run --rm -v fbtest:/data fb-test id` should print `uid=1000`; and the app should
  start without the readonly-DB error against a root-owned volume (simulate:
  `docker run --rm -v fbtest:/data alpine chown -R 0:0 /data` first, then run fb-test and
  confirm it starts). If docker/network is unavailable in the sandbox, say so and review by eye.
- `docker compose -f docker-compose.yml config` and `... -f docker-compose.dev.yml config`
  parse and NO LONGER show `user:`.
- No backend code/tests affected.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. Update `docs/decisions.md` as above.
3. Non-interactive subagent run: stage ONLY the files this task touched (Dockerfile,
   docker-entrypoint.sh, both compose files, README.md, docs/configuration.md,
   docs/decisions.md, prompt move) and commit on `dev` with one `fix:` message. Never
   `git add -A`. Never push.
