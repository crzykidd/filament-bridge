# Standards implemented

This project implements the following [standards](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards)
from the crzynet `homelab-configs` repo. Each row pins the **version** that this
project has actually wired up.

| Standard | Version | Adopted | Notes |
|---|---|---|---|
| [code-checkin-and-pr](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/code-checkin-and-pr/README.md) | 1.1.0 | 2026-05-28 | **Partial.** Operational rules live in `CLAUDE.md` and the `dev` branch exists. Branch protection on `main` and the 5 required CI checks (backend lint, structured-config validation, migration check, compose validation, image build) are **pending first code** — `backend/`, `frontend/`, `Dockerfile`, `docker-compose.yml`, and `alembic/` don't exist yet. Wire CI + protection when they land. |
| [release-prep-and-cut](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/release-prep-and-cut/README.md) | 1.0.0 | 2026-05-28 | Slash commands installed at `.claude/commands/release-prep.md` and `release-cut.md`. Canonical version file = `backend/app/__init__.py` (`__version__`). **Pending first code:** the version file, `CHANGELOG.md`, a README version badge, and a README "What's New" section don't exist yet; the first release can't run until they do. |
| [handoff-prompt-workflow](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/handoff-prompt-workflow/README.md) | 1.5.0 | 2026-05-28 | `prompts/TEMPLATE.md` and `docs/decisions.md` created. Soft pointer in `CLAUDE.md`. v1.5.0 adds step 8: the agent hands the user the launch command (`claude --model <model> "Read prompts/<file>.md and execute it as your task."`) whenever it creates a prompt. `TEMPLATE.md` unchanged from 1.4.0. |
