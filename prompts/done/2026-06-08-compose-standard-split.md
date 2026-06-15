---
name: 2026-06-08-compose-standard-split
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-08
result: docker-compose.yml rewritten to bridge-only (published image, placeholder external URLs); docker-compose.dev.yml updated to full local stack with named volumes and comment header; README quick-start updated; CLAUDE.md project-structure updated; docs/decisions.md entry added.
---

# Task: Standard docker-compose ships only the bridge; full stack moves to docker-compose.dev.yml

The repo's `docker-compose.yml` bundles `filament-db`, `mongo`, and `spoolman` alongside the
bridge. Those are SEPARATE projects the user runs themselves — the standard compose must not
ship them. Split:

## 1. `docker-compose.dev.yml` (new) — the full local stack

Move the CURRENT full content of `docker-compose.yml` (bridge `build: .` + `filament-db` +
`mongo` + `spoolman` + all three volumes, internal URLs `http://filament-db:3000` /
`http://spoolman:7912`, depends_on) into a new `docker-compose.dev.yml`. Add a top comment:
"Development/testing stack — runs the bridge plus its own Spoolman + Filament DB + MongoDB.
For a normal deployment use docker-compose.yml and point it at your existing Spoolman/Filament DB."

## 2. `docker-compose.yml` (rewrite) — standard, bridge only

Replace `docker-compose.yml` with just the bridge, using the published image and pointing at
the user's EXTERNAL services via placeholder URLs:

```yaml
# filament-bridge — standard deployment.
# Spoolman and Filament DB are separate projects you run yourself; point the bridge at them
# with the URLs below. For a full local stack (bridge + Spoolman + Filament DB + Mongo) for
# development/testing, use docker-compose.dev.yml instead.
services:
  filament-bridge:
    image: ghcr.io/hyiger/filament-bridge:latest
    ports:
      - "8090:8090"
    volumes:
      - bridge-data:/data        # REQUIRED — persists the SQLite state database
    environment:
      FILAMENTDB_URL: http://your-filament-db-host:3000   # your existing Filament DB
      SPOOLMAN_URL: http://your-spoolman-host:7912         # your existing Spoolman
      # DISCORD_WEBHOOK_URL: https://discord.com/api/webhooks/...
    restart: unless-stopped

volumes:
  bridge-data:
```

(No `filament-db`/`mongo`/`spoolman` services, no `depends_on`, only the `bridge-data` volume.)

## 3. Update doc references

- `README.md`: any pointer that says the repo ships a full runnable stack at
  `docker-compose.yml` should point to `docker-compose.dev.yml`; note that `docker-compose.yml`
  is the standard bridge-only deploy pointing at your own Spoolman/Filament DB. (The README
  quick-start's inline compose already shows the bridge-only shape — keep it consistent with
  the new `docker-compose.yml`, incl. the `bridge-data:/data` volume.)
- `CLAUDE.md`: the project-structure line `docker-compose.yml — example deployment with both
  upstream services` should be corrected: `docker-compose.yml` = standard bridge-only;
  `docker-compose.dev.yml` = full local stack for development.

## Verification

- `docker compose -f docker-compose.yml config` and
  `docker compose -f docker-compose.dev.yml config` both parse without error (run them if the
  docker CLI is available; otherwise YAML-lint mentally). No code/tests affected.
- `git diff --stat` shows the two compose files + README.md + CLAUDE.md (+ prompt move).

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: standard `docker-compose.yml` ships only the bridge (Spoolman/FDB are
   external); full local stack lives in `docker-compose.dev.yml`.
3. Non-interactive subagent run: stage ONLY the files this task touched (incl. prompt move +
   docs) and commit on `dev` with one `chore:` message. Never `git add -A`. Never push.
