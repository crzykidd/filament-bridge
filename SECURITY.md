# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities **privately** — do not open a public GitHub issue, and don't
disclose the details publicly until a fix is available.

Use GitHub's private vulnerability reporting: go to the repository's **Security** tab →
**Report a vulnerability** (this opens a private advisory visible only to you and the maintainers).
See [Privately reporting a security vulnerability](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
for the steps.

Please include, where you can:

- what the issue is and the impact you think it has,
- the affected version (see the footer of the app, or `backend/app/__init__.py`),
- steps to reproduce, and
- your deployment shape (LAN-only vs internet-exposed, behind a reverse proxy / tunnel, mobile
  scan flow enabled, etc.) — it materially affects severity for this app.

This is a small, single-maintainer project, so please allow reasonable time for a response and a
fix before any public disclosure.

## Supported versions

Fixes are applied to the latest release only. Run a current version before reporting — the version
is shown in the app footer and lives (bare) in `backend/app/__init__.py`.

## Scope & deployment model

filament-bridge is designed for **self-hosted** use as a Docker sidecar. Its threat model assumes:

- The bridge sits on a trusted LAN, or behind a TLS-terminating reverse proxy / tunnel when exposed
  to the internet. It should **not** be published directly to the internet on its raw port. See
  [docs/security.md](docs/security.md) for the reverse-proxy and TLS guidance.
- It is a **single-admin** app (one password, optional API token; no multi-user/roles).
- The two upstream systems (Filament DB, Spoolman) are unauthenticated by design; the bridge holds
  the credentials that matter.

The [security model doc](docs/security.md) describes the auth model, the configurable mobile scan
flow (including the `mobile_session_days=0` public mode and what it exposes), backup handling, and
what is intentionally left to the reverse proxy. Some tradeoffs are **accepted risks** for the
self-hosted single-admin model and are recorded in [docs/decisions.md](docs/decisions.md) — please
skim those before reporting, as a known accepted-risk item may already cover your finding.

Things that **are** in scope and worth reporting: authentication bypass, session forgery, secrets
leaking outside the box (e.g. via exports/logs), injection, SSRF/open-redirect, or any
unauthenticated write/enumeration path that shouldn't be public in the default configuration.
