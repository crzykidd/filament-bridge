#!/usr/bin/env python3
"""Regenerate the topic-grouped index at the top of docs/decisions.md.

Idempotent — running it twice produces no diff.

The CATEGORIES list below is the source of truth for bucketing.  When a new
decision is added to docs/decisions.md, append its heading text to the
matching area in CATEGORIES (or create a new area) and re-run this script.

Usage (from repo root):
    python scripts/gen-decisions-index.py [--dry-run] [--docs-path PATH]
"""

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DECISIONS_PATH = REPO_ROOT / "docs" / "decisions.md"

# HTML-comment fences delimit the index block (idempotency key).
INDEX_START = "<!-- decisions-topic-index-start -->"
INDEX_END = "<!-- decisions-topic-index-end -->"

MAINTENANCE_NOTE = (
    "_New entries: add a line to the matching area below, "
    "or re-run `scripts/gen-decisions-index.py` after updating CATEGORIES._"
)

# ---------------------------------------------------------------------------
# CATEGORIES
#
# Ordered list of (area_name, [heading_text, ...]).  Each heading_text must
# match a `## ` entry in docs/decisions.md exactly (minus the leading `## `).
# Within each area the order is newest-first (matching file order), but the
# script does not enforce it.
# ---------------------------------------------------------------------------
CATEGORIES = [
    ("Sync engine & anti-ping-pong", [
        # Core engine mechanics, polling loop, snapshot management, scheduler
        "2026-07-19 — Purge stale filament mappings when Spoolman reuses an id, GitHub #70",
        "2026-06-11 — Small-fix batch (compose image, interval, pagination, dry-run, Settings copy)",
        "2026-06-11 — Honor configured cross-reference field names in ensure_extra_fields + engine orphan guard",
        "2026-06-11 — Durable `changes.log` file (`CHANGES_LOG_ENABLED` / `CHANGES_LOG_PATH`)",
        "2026-06-11 — Debug startup state dump (`DEBUG_STARTUP_DUMP`)",
        "2026-06-11 — Startup state dump retries the upstream fetch (~2 min) instead of one-shot",
        "2026-06-11 — FR-11 fix: FDB `_field_values` now persisted in spool snapshots",
        "2026-06-10 — Engine: stale spool mappings purge instead of queuing deletion conflicts",
        "2026-06-08 — Sync interval + log retention are runtime-configurable; no in-app log-file rotation",
        "2026-06-06 — Per-category sync direction + conflict policy (two-axis model)",
        "2026-05-30 — Phase 5 sync fixes (PATCH, weight precision, material default, wizard gating)",
        "2026-05-29 — Async-job / sync-DB bridging approach (Option A — inline)",
        "2026-05-28 — Sync engine defaults for the three design open questions",
        "2026-05-28 — Synchronous SQLAlchemy (not async) for the persistence layer",
        "2026-05-28 — Spoolman extra fields: create on startup, JSON-decode values",
    ]),

    ("Weight model", [
        # Net/gross translation, usage entries, tare weight, anti-double-count
        "2026-06-24 — Lowering a spool weight always goes through an FDB usage entry (issue #28)",
        "2026-06-10 — Weight model: net = totalWeight − tare (no usageHistory subtraction); refresh both snapshots after a weight push",
    ]),

    ("Wizard & variant model", [
        # Bulk Import Wizard, variant hierarchy, naming, reconcile, planner
        "2026-06-28 — Reconcile orphaned spools instead of silently skipping them, GitHub #48",
        "2026-06-21 — `never_import_empties` is honored by the ongoing engine (not just the wizard)",
        "2026-06-18 — Parent/variant + OpenPrintTag rework: PARKED, blocked on upstream",
        "2026-06-13 — Reconcile: master/container parents are intentional; shown as variant annotation, never as missing",
        "2026-06-13 — Reconcile page: read-only, on-demand, no fuzzy suggestions",
        "2026-06-13 — find-or-attach on 409 in `_execute_spoolman_to_fdb` (idempotent conflict Add)",
        "2026-06-13 — FilamentMapping.identity column + filament-only rows in Synced Records",
        "2026-06-11 — Filament-level dashboard counts + wizard execute per-type breakdown",
        "2026-06-11 — Archived Spoolman spools import as retired FDB spools (not silently dropped)",
        "2026-06-11 — Fix wizard Pass-2.6 finish-tag wire format (CSV not JSON array)",
        "2026-06-10 — Wizard planner validates mappings against live FDB; stale → recreate + replace",
        "2026-06-10 — Wizard import: created FDB filament naming rule (variant + standalone)",
        "2026-06-10 — Wizard execute response: added `label` field to `WizardExecuteRecord`",
        "2026-06-09 — Configurable container marker, Master/Parent badge, editable collision rename",
        "2026-06-08 — Generic container parent mode for Bulk Import Wizard",
        '2026-06-08 — Container naming "Master" suffix + resilient 409 execute',
        "2026-06-07 — Wizard pre-matches records by filamentdb_id cross-reference before fuzzy matching",
        "2026-06-07 — Renamed to Bulk Import Wizard; ongoing SoT removed from wizard step; never_import_empties global setting",
        "2026-06-06 — Name-collision detection is vendor-aware",
        "2026-06-06 — FDB create_spool returns the filament doc; extract spool _id by label match",
        "2026-06-06 — Stale cross-ref no longer skips spool creation; spoolWeight from resolved tare",
        "2026-06-06 — Import now sets FDB netFilamentWeight from Spoolman filament weight",
        '2026-06-06 — Dry-run preview lists in-sync pairs as "matched — no updates"',
        "2026-06-06 — New-spool direction enforced; wizard writes new keys; old source-of-truth removed",
        "2026-06-05 — Variances detail enrichment, per-field reconciliation, execute write-back, pre-flight summary",
        "2026-06-05 — Variances type/diameter/temps display",
        "2026-06-05 — Reconcile canonical-key contract + editable master temps",
        '2026-06-04 — variant_line_keywords user setting + Standalone "Move to existing group"',
        "2026-06-04 — Wizard per-member actions + finish-line auto-split (Part A/B)",
        "2026-06-04 — Wizard variant-resolution redesign: D1 grouping key, D2 suggest-exclude, D3 FDB-parent attach, D4 empty-spool toggle",
        "2026-06-03 — Wizard: merged Variances step, downstream filtering, master-tare rule",
        "2026-06-01 — Match-review v2: one unified table, Group-By Status default",
        "2026-05-31 — Match-review redesign: grouped tables, checkboxes, rescan",
        "2026-05-31 — Wizard preview (FR-4 foundation): reconcile-flag keys + read-only UI step",
        "2026-05-31 — Spoolman→FDB variant grouping: SM-keyed master-promote",
        "2026-05-31 — Unified dry-run: shared planner, auto-decisions, orphan bucket",
        "2026-05-29 — Phase 3b wizard execute (FR-7): create order, idempotency, snapshot seed, fatal vs per-record",
        "2026-05-29 — Phase 3 API: error envelope, conflict-resolve semantics, wizard state, backup format",
        "2026-05-29 — Spoolman extra-field conflict-key definition (Phase 2)",
        "2026-05-28 — Filament DB variant inheritance: read detail, strip computed fields",
    ]),

    ("Conflicts & resolution", [
        # Conflict detection, types, policies, resolution UI, new-record handling
        '2026-06-28 — `new_filament`/`new_spool` conflicts update in place (stable id), GitHub #44',
        "2026-06-23 — Cross-system conflict resolution converges (writes both sides on resolve) (issue #21)",
        "2026-06-11 — New-record handling: two-tier policy model (new_filament_policy / new_spool_policy)",
        "2026-06-10 — Phase B: master_divergence resolve→apply workflow",
        "2026-06-10 — Phase A: native shared-filament scalar sync + conflict_type column",
        "2026-06-08 — Conflicts page rework + `ColorDisplay` + multicolor in `_conflict_identity` (`eb9af66`)",
        "2026-06-07 — new_spool conflicts: dedup + auto-resolve on map",
        "2026-06-06 — Conflict cards carry snapshot-derived identity",
        "2026-06-05 — Tare excluded from variant-prop conflicts; conflict badges name specific fields",
        "2026-06-05 — Conflicts page: client-side type filter",
        "2026-06-05 — Upstream deletion detection → conflict queue",
    ]),

    ("OpenTag / OpenPrintTag", [
        # OpenPrintTag matching, cleanup tool, dataset, scoring, apply
        "2026-06-24 — OpenPrintTag drying time is minutes end-to-end (issue #27)",
        "2026-06-21 — OpenPrintTag material settings sync as TYPED Spoolman extras → FDB first-class fields",
        "2026-06-19 — \"Missing values\" report audits OpenPrintTag, not the user's spools",
        "2026-06-19 — OpenPrintTag dataset: ingest the full supported schema (material + packages + containers)",
        "2026-06-18 — OpenTag dataset: gate the heavy tarball download behind a commit-SHA check",
        "2026-06-18 — OpenTag matching: offload CPU off the event loop + cache the last result",
        "2026-06-18 — OpenTag inline unmatch/re-match: scoped FDB settings{} *removal* exception",
        "2026-06-18 — OpenTag completeness report: assess the raw OPT record, not the lossy field path",
        "2026-06-18 — OpenTag Cleanup: toolbar view-switch in component state; Reprocess moves to banner",
        "2026-06-13 — Debug: added POST /api/debug/clear-spoolman-opentag-ids",
        "2026-06-13 — Remove `opentag_color_keywords` user-override feature",
        "2026-06-13 — OpenTag apply: re-point this filament to exact-named canonical vendor",
        "2026-06-11 — OpenTag matcher v2.1: soften hard gates + capture fill-composite descriptors",
        "2026-06-11 — OpenTag matcher v2: structured token decomposition + mined lexicons",
        '2026-06-11 — OpenTag "ignore future updates" flag stored as Spoolman extra field',
        "2026-06-11 — OpenTag dataset: direct GitHub tarball fetch (no FDB proxy)",
        "2026-06-08 — OpenTag matching fixes + unmatched-UI enrichment",
        "2026-06-08 — Single-hex OpenTag entries use color_hex; multi_color_hexes requires ≥2",
        "2026-06-08 — OpenTag no-match reason taxonomy + group collapse UX",
        "2026-06-07 — Wizard OpenPrintTag flag + filter (`db8a4c6`, `4b5db3f`)",
        "2026-06-07 — OPT stamped badge on OpenTag Cleanup cards (`7eb5e98`)",
        "2026-06-07 — OpenTag cleanup lets the user pick from best + top-5 alternates; each candidate carries its own field comparison",
        "2026-06-07 — OpenTag cleanup: reviewable Manufacturer field reassigns Spoolman vendor via find-or-create",
        "2026-06-07 — Settings `opentag_vendor_aliases` maps Spoolman vendor names to OpenTag brand names",
        "2026-06-07 — OpenTag review: exact-UUID match, existing identity display, reviewable name",
        "2026-06-07 — OpenTag secondary_colors recovered from raw tarball; multicolor mismatch flag",
        "2026-06-07 — OpenTag apply no longer writes multi_color_direction when secondaryColors is empty",
        "2026-06-07 — OpenTag apply self-creates required extra fields; ensure_extra_fields is per-section resilient",
        "2026-06-07 — filamentdb_material_tags stored as CSV string in Spoolman text extra field",
        "2026-06-06 — OpenTag matcher: arrangement-from-tags, polymer-family gate, finish-aware scoring",
        "2026-06-06 — OpenTag matching hard-filters by color profile; apply sets multi_color_direction + handles empty primary",
        "2026-06-06 — OpenTag matcher: color NAME is the key within-brand/material discriminator; hex demoted",
        "2026-06-06 — OpenTag cleanup: instant dataset banner + staged fetch/match progress",
        "2026-06-06 — OpenTag matching pre-filters candidates by normalized brand for performance; progress logged",
        "2026-06-06 — FDB /api/openprinttag returns OPTDatabase wrapper; bridge extracts .materials; cache self-heals malformed data",
        "2026-06-06 — OpenTag cleanup API renamed to /openprinttag/*; 120 s fetch timeout; structured fetch errors",
        "2026-06-06 — OpenTag cleanup tool + scoped FDB settings-bag exception",
        "2026-06-06 — OpenPrintTag finish-tag model adopted; `filamentdb_material_tags` Spoolman extra field",
    ]),

    ("Backups", [
        # Export/import, nightly scheduled backup, safety dialogs
        "2026-07-02 — Backup boundary excludes auth secrets and internal state, GitHub #57",
        "2026-06-23 — Scheduled nightly backups: bridge-state + FDB snapshot only, on by default (issue #5)",
        "2026-06-18 — BackupSafetyDialog made unconditionally friendly; debug clears moved to DebugConfirmDialog",
        "2026-06-11 — Backup export/import fidelity: `is_synthetic_parent`, `conflict_type`, and auth secrets",
        "2026-06-08 — Filament DB backup API correction",
        "2026-06-07 — Pre-write backup safeguard dialog gates destructive actions",
    ]),

    ("Mobile & labels", [
        # Mobile scan flow, QR redirect, LabelForge printing, session auth
        "2026-06-24 — Configurable mobile-scan auth: `mobile_session_days` (0 = public, N = login TTL)",
        "2026-06-23 — Mobile updates & labels (phase 3 — LabelForge label printing)",
        "2026-06-23 — Mobile updates & labels (phase 2 frontend mobile flow)",
        "2026-06-23 — Mobile updates & labels (phase 1 backend foundation)",
    ]),

    ("Security & auth", [
        # Auth gates, session cookies, API tokens, security headers
        "2026-07-02 — Per-IP in-memory login rate-limiting, GitHub #59",
        "2026-07-02 — Secrets stored plaintext in SQLite is an accepted risk (M3 won't-fix)",
        "2026-07-02 — Proxy-aware Secure cookie flag + response security headers, GitHub #58",
        "2026-06-09 — Single-account auth + API token + first-login required-settings gate",
    ]),

    ("Locations & lifecycle", [
        # Location sync (name-based), archive/retire mirroring, FDB locationId
        "2026-06-24 — Sync spool location in the continuous engine, compared by name (`location_sync`, GitHub #29)",
        "2026-06-17 — Archive/retire to sync bidirectionally for already-synced spools (FR-21 symmetric, design agreed)",
        "2026-05-31 — FDB location semantics: locationId (ObjectId reference), pre-creation required",
    ]),

    ("Multicolor & filament data", [
        # Multicolor mapping, color tokens, material grade, cost sync
        "2026-06-17 — Synced Records FDB color: capture a display hex for every mapped filament (GitHub #2)",
        "2026-06-08 — multicolor writes always include multi_color_direction (Spoolman 422 fix)",
        "2026-06-07 — Spoolman multicolor: `multi_color_hexes` only; `color_hex` never set for multicolor",
        "2026-06-07 — Color-name tokens split on non-alphanumeric; multicolor descriptor noise dropped",
        "2026-06-07 — PLA+/grade modeling: base polymer + grade in name; no material guard (`memory/pla-plus-modeling-decision.md`)",
        "2026-06-06 — Filament cost sync: spool-price-first, filament fallback; matprop SoT; snapshot merge",
        "2026-05-31 — Structured multicolor sync supersedes the colorName projection",
        "2026-05-30 — Multicolor filament mapping (Spoolman ↔ Filament DB)",
    ]),

    ("UI, CI & infrastructure", [
        # Frontend components, Docker, CI, deep-links, debug tools, misc
        "2026-06-22 — Changelog archiving is summarize-on-archive (release-prep-and-cut v1.1.0)",
        "2026-06-21 — CI is push-only; CodeQL is PR-gated (no dual push+PR triggers)",
        "2026-06-19 — CodeQL log-injection FPs are int path params, not `scrub`; no model pack",
        "2026-06-19 — Defer the per-minor CHANGELOG archive (deviation from release-prep-and-cut)",
        "2026-06-17 — Dashboard counts: spools vs filaments are independent; break out master filaments (GitHub #3)",
        "2026-06-11 — HelpTip component for in-place UI help",
        "2026-06-11 — In-app docs viewer at /docs/:slug",
        "2026-06-11 — MappingRow carries `conflict_id`; Synced Records deep-links to Conflicts",
        "2026-06-10 — Debug: added POST /api/debug/full-reset",
        "2026-06-09 — Light/dark/system theme infrastructure",
        "2026-06-09 — Version display, GitHub update check, dev channel marker",
        "2026-06-08 — gated Debug mode with reset tools for clean re-testing",
        "2026-06-08 — Browser-local timestamp rendering (`d22cad8`)",
        "2026-06-08 — Sync-log windows view + `DELETE /sync-log` (`7b0361e`)",
        "2026-06-08 — Synced Records enrichment: multicolor, weight, empty, conflict deep-link (`a870950`)",
        "2026-06-08 — Entrypoint chown-then-gosu drop replaces static USER directive",
        "2026-06-08 — Container runs as non-root 1000:1000; /data chowned in image (superseded)",
        "2026-06-08 — docker-compose.yml ships bridge-only; full dev stack moved to docker-compose.dev.yml",
        "2026-06-03 — CI workflows, registry, and main branch protection",
        "2026-06-01 — De-adopted the vexp-context-engine standard (sunset homelab-wide)",
        "2026-05-30 — Make docker-compose deployable + SPA route fallback",
        "2026-05-30 — Dashboard dry-run: SyncPreviewEntry shape and skip coverage",
        "2026-05-29 — Phase 4 Web UI: SPA scaffold, static mount, deep-link bases, hooks",
        "2026-05-28 — Canonical build-phase numbering (closes the skipped Phase 2)",
        "2026-05-28 — Deep-link routes (corrects PRD NFR-7 / CLAUDE.md)",
        "2026-05-28 — Docker base images: node:22-alpine (build) + python:3.12-slim-bookworm (runtime)",
        "2026-05-28 — Canonical version file is `backend/app/__init__.py`",
    ]),
]

# ---------------------------------------------------------------------------
# GFM slug computation
# ---------------------------------------------------------------------------

def gfm_slug(text: str) -> str:
    """Compute the GitHub-Flavored Markdown heading anchor slug.

    Rules (matching GitHub's implementation):
      1. Strip inline-code backtick wrappers (keep inner text).
      2. Lowercase the entire string.
      3. Replace every space with a hyphen.
      4. Remove every character that is not a word char (a-z, 0-9, _)
         or a hyphen — this includes em dashes, punctuation, etc.
    Duplicate-slug suffix (-1, -2, …) is handled by the caller.
    """
    # Strip backtick wrappers but keep content
    text = re.sub(r'`([^`]*)`', r'\1', text)
    text = text.lower()
    text = text.replace(' ', '-')
    text = re.sub(r'[^\w-]', '', text)
    return text


def unique_slugs(headings: list[str]) -> list[str]:
    """Return a list of unique GFM slugs, appending -1/-2/… on collision."""
    seen: dict[str, int] = {}
    result = []
    for h in headings:
        base = gfm_slug(h)
        count = seen.get(base, 0)
        seen[base] = count + 1
        result.append(base if count == 0 else f"{base}-{count}")
    return result


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_ISSUE_TRAILING = re.compile(
    r'(?:,\s*GitHub\s*#(\d+))'          # ", GitHub #N" at end
    r'|(?:\s+\(issue\s+#(\d+)\))$'      # " (issue #N)" at end
    r'|(?:\s+\(GitHub\s+#(\d+)\))$',    # " (GitHub #N)" at end
)


def split_issue(title: str) -> tuple[str, str | None]:
    """Return (clean_title, issue_num_str_or_None).

    The first regex alternative matches ', GitHub #N' without an end-anchor so
    it handles issue refs embedded inside a parenthetical
    ('...(location_sync, GitHub #29)').  When a bare ')' trails the match we
    restore it so the display text stays balanced.
    """
    m = _ISSUE_TRAILING.search(title)
    if not m:
        return title, None
    num = m.group(1) or m.group(2) or m.group(3)
    clean = title[: m.start()]
    # If a lone ')' was left unconsumed and it closes an unmatched '(',
    # put it back (covers the embedded-in-parens case above).
    remaining = title[m.end():]
    if remaining.strip() == ")" and clean.count("(") > clean.count(")"):
        clean += ")"
    return clean, num


def extract_headings(content: str) -> list[str]:
    """Return the text of every `## ` heading (without the `## ` prefix)."""
    return [
        line[3:]
        for line in content.splitlines()
        if line.startswith("## ")
    ]


# ---------------------------------------------------------------------------
# Index block generation
# ---------------------------------------------------------------------------

def build_index_block(headings: list[str], slugs: list[str]) -> str:
    """Produce the full index block (including fence markers)."""
    slug_of: dict[str, str] = dict(zip(headings, slugs))

    # Flatten all categorised headings into a set for coverage checking
    categorised: set[str] = set()
    for _, entries in CATEGORIES:
        for h in entries:
            categorised.add(h)

    lines: list[str] = [INDEX_START, "", MAINTENANCE_NOTE, ""]

    unmatched_cat: list[str] = []  # in CATEGORIES but not in file
    duplicate_cat: list[str] = []  # appears more than once in CATEGORIES
    covered: set[str] = set()      # file headings assigned to a category

    for area_name, entries in CATEGORIES:
        lines.append(f"### {area_name}")
        lines.append("")
        for entry_text in entries:
            if entry_text not in slug_of:
                unmatched_cat.append(entry_text)
                continue
            if entry_text in covered:
                duplicate_cat.append(entry_text)
                continue  # skip; already listed in an earlier area
            slug = slug_of[entry_text]
            covered.add(entry_text)
            clean, issue_num = split_issue(entry_text)
            issue_suffix = f" — #{issue_num}" if issue_num else ""
            lines.append(f"- [{clean}](#{slug}){issue_suffix}")
        lines.append("")

    lines.append(INDEX_END)

    # Report problems to stderr (non-fatal so --dry-run still prints)
    if unmatched_cat:
        print(
            f"ERROR: {len(unmatched_cat)} CATEGORIES entries not found in file:",
            file=sys.stderr,
        )
        for t in unmatched_cat:
            print(f"  {t!r}", file=sys.stderr)

    if duplicate_cat:
        print(
            f"ERROR: {len(duplicate_cat)} CATEGORIES entries listed more than once:",
            file=sys.stderr,
        )
        for t in duplicate_cat:
            print(f"  {t!r}", file=sys.stderr)

    uncovered = [h for h in headings if h not in covered]
    if uncovered:
        print(
            f"WARNING: {len(uncovered)} file headings not in any category:",
            file=sys.stderr,
        )
        for h in uncovered:
            print(f"  {h!r}", file=sys.stderr)

    matched = len(covered)
    print(
        f"Index: {matched}/{len(headings)} headings matched "
        f"({len(CATEGORIES)} areas)",
        file=sys.stderr,
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# File update (idempotent)
# ---------------------------------------------------------------------------

def update_decisions(path: Path, dry_run: bool = False) -> None:
    content = path.read_text(encoding="utf-8")
    headings = extract_headings(content)
    slugs = unique_slugs(headings)

    index_block = build_index_block(headings, slugs)

    # Locate the title line (`# Decision record`) and the first `## ` heading.
    title_line = "# Decision record"
    title_pos = content.find(title_line)
    if title_pos == -1:
        sys.exit("ERROR: '# Decision record' not found in file.")

    first_h2 = content.find("\n## ", title_pos)
    if first_h2 == -1:
        sys.exit("ERROR: No `## ` heading found after title.")

    # Everything between the title newline and the first ## is the current
    # index area (may already contain a previous index block or be empty).
    after_title = content.find("\n", title_pos) + 1  # start of content after title line

    # If an existing index block is present, replace only inside the fences.
    start_fence = content.find(INDEX_START, after_title)
    end_fence = content.find(INDEX_END, after_title)

    if start_fence != -1 and end_fence != -1 and start_fence < end_fence:
        # Replace the existing block (inclusive of fence lines)
        end_of_fence = content.find("\n", end_fence) + 1
        new_content = (
            content[:start_fence]
            + index_block
            + "\n"
            + content[end_of_fence:]
        )
    else:
        # No existing block — insert right after the title line
        after_title_end = content.find("\n", title_pos) + 1
        new_content = (
            content[:after_title_end]
            + "\n"
            + index_block
            + "\n\n"
            + content[after_title_end:]
        )

    if dry_run:
        print(new_content)
        return

    if new_content == content:
        print("No changes (already up to date).", file=sys.stderr)
        return

    path.write_text(new_content, encoding="utf-8")
    print(f"Updated {path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the updated file to stdout instead of writing it.",
    )
    parser.add_argument(
        "--docs-path",
        type=Path,
        default=DEFAULT_DECISIONS_PATH,
        help="Path to docs/decisions.md (default: auto-detected from repo root).",
    )
    args = parser.parse_args()
    update_decisions(args.docs_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
