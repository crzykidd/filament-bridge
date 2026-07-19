# Decision record

<!-- decisions-topic-index-start -->

_New entries: add a line to the matching area below, or re-run `scripts/gen-decisions-index.py` after updating CATEGORIES._

### Sync engine & anti-ping-pong

- [2026-07-19 — Purge stale filament mappings when Spoolman reuses an id](#2026-07-19--purge-stale-filament-mappings-when-spoolman-reuses-an-id-github-70) — #70
- [2026-06-11 — Small-fix batch (compose image, interval, pagination, dry-run, Settings copy)](#2026-06-11--small-fix-batch-compose-image-interval-pagination-dry-run-settings-copy)
- [2026-06-11 — Honor configured cross-reference field names in ensure_extra_fields + engine orphan guard](#2026-06-11--honor-configured-cross-reference-field-names-in-ensure_extra_fields--engine-orphan-guard)
- [2026-06-11 — Durable `changes.log` file (`CHANGES_LOG_ENABLED` / `CHANGES_LOG_PATH`)](#2026-06-11--durable-changeslog-file-changes_log_enabled--changes_log_path)
- [2026-06-11 — Debug startup state dump (`DEBUG_STARTUP_DUMP`)](#2026-06-11--debug-startup-state-dump-debug_startup_dump)
- [2026-06-11 — Startup state dump retries the upstream fetch (~2 min) instead of one-shot](#2026-06-11--startup-state-dump-retries-the-upstream-fetch-2-min-instead-of-one-shot)
- [2026-06-11 — FR-11 fix: FDB `_field_values` now persisted in spool snapshots](#2026-06-11--fr-11-fix-fdb-_field_values-now-persisted-in-spool-snapshots)
- [2026-06-10 — Engine: stale spool mappings purge instead of queuing deletion conflicts](#2026-06-10--engine-stale-spool-mappings-purge-instead-of-queuing-deletion-conflicts)
- [2026-06-08 — Sync interval + log retention are runtime-configurable; no in-app log-file rotation](#2026-06-08--sync-interval--log-retention-are-runtime-configurable-no-in-app-log-file-rotation)
- [2026-06-06 — Per-category sync direction + conflict policy (two-axis model)](#2026-06-06--per-category-sync-direction--conflict-policy-two-axis-model)
- [2026-05-30 — Phase 5 sync fixes (PATCH, weight precision, material default, wizard gating)](#2026-05-30--phase-5-sync-fixes-patch-weight-precision-material-default-wizard-gating)
- [2026-05-29 — Async-job / sync-DB bridging approach (Option A — inline)](#2026-05-29--async-job--sync-db-bridging-approach-option-a--inline)
- [2026-05-28 — Sync engine defaults for the three design open questions](#2026-05-28--sync-engine-defaults-for-the-three-design-open-questions)
- [2026-05-28 — Synchronous SQLAlchemy (not async) for the persistence layer](#2026-05-28--synchronous-sqlalchemy-not-async-for-the-persistence-layer)
- [2026-05-28 — Spoolman extra fields: create on startup, JSON-decode values](#2026-05-28--spoolman-extra-fields-create-on-startup-json-decode-values)

### Weight model

- [2026-06-24 — Lowering a spool weight always goes through an FDB usage entry](#2026-06-24--lowering-a-spool-weight-always-goes-through-an-fdb-usage-entry-issue-28) — #28
- [2026-06-10 — Weight model: net = totalWeight − tare (no usageHistory subtraction); refresh both snapshots after a weight push](#2026-06-10--weight-model-net--totalweight--tare-no-usagehistory-subtraction-refresh-both-snapshots-after-a-weight-push)

### Wizard & variant model

- [2026-06-28 — Reconcile orphaned spools instead of silently skipping them](#2026-06-28--reconcile-orphaned-spools-instead-of-silently-skipping-them-github-48) — #48
- [2026-06-21 — `never_import_empties` is honored by the ongoing engine (not just the wizard)](#2026-06-21--never_import_empties-is-honored-by-the-ongoing-engine-not-just-the-wizard)
- [2026-06-18 — Parent/variant + OpenPrintTag rework: PARKED, blocked on upstream](#2026-06-18--parentvariant--openprinttag-rework-parked-blocked-on-upstream)
- [2026-06-13 — Reconcile: master/container parents are intentional; shown as variant annotation, never as missing](#2026-06-13--reconcile-mastercontainer-parents-are-intentional-shown-as-variant-annotation-never-as-missing)
- [2026-06-13 — Reconcile page: read-only, on-demand, no fuzzy suggestions](#2026-06-13--reconcile-page-read-only-on-demand-no-fuzzy-suggestions)
- [2026-06-13 — find-or-attach on 409 in `_execute_spoolman_to_fdb` (idempotent conflict Add)](#2026-06-13--find-or-attach-on-409-in-_execute_spoolman_to_fdb-idempotent-conflict-add)
- [2026-06-13 — FilamentMapping.identity column + filament-only rows in Synced Records](#2026-06-13--filamentmappingidentity-column--filament-only-rows-in-synced-records)
- [2026-06-11 — Filament-level dashboard counts + wizard execute per-type breakdown](#2026-06-11--filament-level-dashboard-counts--wizard-execute-per-type-breakdown)
- [2026-06-11 — Archived Spoolman spools import as retired FDB spools (not silently dropped)](#2026-06-11--archived-spoolman-spools-import-as-retired-fdb-spools-not-silently-dropped)
- [2026-06-11 — Fix wizard Pass-2.6 finish-tag wire format (CSV not JSON array)](#2026-06-11--fix-wizard-pass-26-finish-tag-wire-format-csv-not-json-array)
- [2026-06-10 — Wizard planner validates mappings against live FDB; stale → recreate + replace](#2026-06-10--wizard-planner-validates-mappings-against-live-fdb-stale--recreate--replace)
- [2026-06-10 — Wizard import: created FDB filament naming rule (variant + standalone)](#2026-06-10--wizard-import-created-fdb-filament-naming-rule-variant--standalone)
- [2026-06-10 — Wizard execute response: added `label` field to `WizardExecuteRecord`](#2026-06-10--wizard-execute-response-added-label-field-to-wizardexecuterecord)
- [2026-06-09 — Configurable container marker, Master/Parent badge, editable collision rename](#2026-06-09--configurable-container-marker-masterparent-badge-editable-collision-rename)
- [2026-06-08 — Generic container parent mode for Bulk Import Wizard](#2026-06-08--generic-container-parent-mode-for-bulk-import-wizard)
- [2026-06-08 — Container naming "Master" suffix + resilient 409 execute](#2026-06-08--container-naming-master-suffix--resilient-409-execute)
- [2026-06-07 — Wizard pre-matches records by filamentdb_id cross-reference before fuzzy matching](#2026-06-07--wizard-pre-matches-records-by-filamentdb_id-cross-reference-before-fuzzy-matching)
- [2026-06-07 — Renamed to Bulk Import Wizard; ongoing SoT removed from wizard step; never_import_empties global setting](#2026-06-07--renamed-to-bulk-import-wizard-ongoing-sot-removed-from-wizard-step-never_import_empties-global-setting)
- [2026-06-06 — Name-collision detection is vendor-aware](#2026-06-06--name-collision-detection-is-vendor-aware)
- [2026-06-06 — FDB create_spool returns the filament doc; extract spool _id by label match](#2026-06-06--fdb-create_spool-returns-the-filament-doc-extract-spool-_id-by-label-match)
- [2026-06-06 — Stale cross-ref no longer skips spool creation; spoolWeight from resolved tare](#2026-06-06--stale-cross-ref-no-longer-skips-spool-creation-spoolweight-from-resolved-tare)
- [2026-06-06 — Import now sets FDB netFilamentWeight from Spoolman filament weight](#2026-06-06--import-now-sets-fdb-netfilamentweight-from-spoolman-filament-weight)
- [2026-06-06 — Dry-run preview lists in-sync pairs as "matched — no updates"](#2026-06-06--dry-run-preview-lists-in-sync-pairs-as-matched--no-updates)
- [2026-06-06 — New-spool direction enforced; wizard writes new keys; old source-of-truth removed](#2026-06-06--new-spool-direction-enforced-wizard-writes-new-keys-old-source-of-truth-removed)
- [2026-06-05 — Variances detail enrichment, per-field reconciliation, execute write-back, pre-flight summary](#2026-06-05--variances-detail-enrichment-per-field-reconciliation-execute-write-back-pre-flight-summary)
- [2026-06-05 — Variances type/diameter/temps display](#2026-06-05--variances-typediametertemps-display)
- [2026-06-05 — Reconcile canonical-key contract + editable master temps](#2026-06-05--reconcile-canonical-key-contract--editable-master-temps)
- [2026-06-04 — variant_line_keywords user setting + Standalone "Move to existing group"](#2026-06-04--variant_line_keywords-user-setting--standalone-move-to-existing-group)
- [2026-06-04 — Wizard per-member actions + finish-line auto-split (Part A/B)](#2026-06-04--wizard-per-member-actions--finish-line-auto-split-part-ab)
- [2026-06-04 — Wizard variant-resolution redesign: D1 grouping key, D2 suggest-exclude, D3 FDB-parent attach, D4 empty-spool toggle](#2026-06-04--wizard-variant-resolution-redesign-d1-grouping-key-d2-suggest-exclude-d3-fdb-parent-attach-d4-empty-spool-toggle)
- [2026-06-03 — Wizard: merged Variances step, downstream filtering, master-tare rule](#2026-06-03--wizard-merged-variances-step-downstream-filtering-master-tare-rule)
- [2026-06-01 — Match-review v2: one unified table, Group-By Status default](#2026-06-01--match-review-v2-one-unified-table-group-by-status-default)
- [2026-05-31 — Match-review redesign: grouped tables, checkboxes, rescan](#2026-05-31--match-review-redesign-grouped-tables-checkboxes-rescan)
- [2026-05-31 — Wizard preview (FR-4 foundation): reconcile-flag keys + read-only UI step](#2026-05-31--wizard-preview-fr-4-foundation-reconcile-flag-keys--read-only-ui-step)
- [2026-05-31 — Spoolman→FDB variant grouping: SM-keyed master-promote](#2026-05-31--spoolmanfdb-variant-grouping-sm-keyed-master-promote)
- [2026-05-31 — Unified dry-run: shared planner, auto-decisions, orphan bucket](#2026-05-31--unified-dry-run-shared-planner-auto-decisions-orphan-bucket)
- [2026-05-29 — Phase 3b wizard execute (FR-7): create order, idempotency, snapshot seed, fatal vs per-record](#2026-05-29--phase-3b-wizard-execute-fr-7-create-order-idempotency-snapshot-seed-fatal-vs-per-record)
- [2026-05-29 — Phase 3 API: error envelope, conflict-resolve semantics, wizard state, backup format](#2026-05-29--phase-3-api-error-envelope-conflict-resolve-semantics-wizard-state-backup-format)
- [2026-05-29 — Spoolman extra-field conflict-key definition (Phase 2)](#2026-05-29--spoolman-extra-field-conflict-key-definition-phase-2)
- [2026-05-28 — Filament DB variant inheritance: read detail, strip computed fields](#2026-05-28--filament-db-variant-inheritance-read-detail-strip-computed-fields)

### Conflicts & resolution

- [2026-06-28 — `new_filament`/`new_spool` conflicts update in place (stable id)](#2026-06-28--new_filamentnew_spool-conflicts-update-in-place-stable-id-github-44) — #44
- [2026-06-23 — Cross-system conflict resolution converges (writes both sides on resolve)](#2026-06-23--cross-system-conflict-resolution-converges-writes-both-sides-on-resolve-issue-21) — #21
- [2026-06-11 — New-record handling: two-tier policy model (new_filament_policy / new_spool_policy)](#2026-06-11--new-record-handling-two-tier-policy-model-new_filament_policy--new_spool_policy)
- [2026-06-10 — Phase B: master_divergence resolve→apply workflow](#2026-06-10--phase-b-master_divergence-resolveapply-workflow)
- [2026-06-10 — Phase A: native shared-filament scalar sync + conflict_type column](#2026-06-10--phase-a-native-shared-filament-scalar-sync--conflict_type-column)
- [2026-06-08 — Conflicts page rework + `ColorDisplay` + multicolor in `_conflict_identity` (`eb9af66`)](#2026-06-08--conflicts-page-rework--colordisplay--multicolor-in-_conflict_identity-eb9af66)
- [2026-06-07 — new_spool conflicts: dedup + auto-resolve on map](#2026-06-07--new_spool-conflicts-dedup--auto-resolve-on-map)
- [2026-06-06 — Conflict cards carry snapshot-derived identity](#2026-06-06--conflict-cards-carry-snapshot-derived-identity)
- [2026-06-05 — Tare excluded from variant-prop conflicts; conflict badges name specific fields](#2026-06-05--tare-excluded-from-variant-prop-conflicts-conflict-badges-name-specific-fields)
- [2026-06-05 — Conflicts page: client-side type filter](#2026-06-05--conflicts-page-client-side-type-filter)
- [2026-06-05 — Upstream deletion detection → conflict queue](#2026-06-05--upstream-deletion-detection--conflict-queue)

### OpenTag / OpenPrintTag

- [2026-06-24 — OpenPrintTag drying time is minutes end-to-end](#2026-06-24--openprinttag-drying-time-is-minutes-end-to-end-issue-27) — #27
- [2026-06-21 — OpenPrintTag material settings sync as TYPED Spoolman extras → FDB first-class fields](#2026-06-21--openprinttag-material-settings-sync-as-typed-spoolman-extras--fdb-first-class-fields)
- [2026-06-19 — "Missing values" report audits OpenPrintTag, not the user's spools](#2026-06-19--missing-values-report-audits-openprinttag-not-the-users-spools)
- [2026-06-19 — OpenPrintTag dataset: ingest the full supported schema (material + packages + containers)](#2026-06-19--openprinttag-dataset-ingest-the-full-supported-schema-material--packages--containers)
- [2026-06-18 — OpenTag dataset: gate the heavy tarball download behind a commit-SHA check](#2026-06-18--opentag-dataset-gate-the-heavy-tarball-download-behind-a-commit-sha-check)
- [2026-06-18 — OpenTag matching: offload CPU off the event loop + cache the last result](#2026-06-18--opentag-matching-offload-cpu-off-the-event-loop--cache-the-last-result)
- [2026-06-18 — OpenTag inline unmatch/re-match: scoped FDB settings{} *removal* exception](#2026-06-18--opentag-inline-unmatchre-match-scoped-fdb-settings-removal-exception)
- [2026-06-18 — OpenTag completeness report: assess the raw OPT record, not the lossy field path](#2026-06-18--opentag-completeness-report-assess-the-raw-opt-record-not-the-lossy-field-path)
- [2026-06-18 — OpenTag Cleanup: toolbar view-switch in component state; Reprocess moves to banner](#2026-06-18--opentag-cleanup-toolbar-view-switch-in-component-state-reprocess-moves-to-banner)
- [2026-06-13 — Debug: added POST /api/debug/clear-spoolman-opentag-ids](#2026-06-13--debug-added-post-apidebugclear-spoolman-opentag-ids)
- [2026-06-13 — Remove `opentag_color_keywords` user-override feature](#2026-06-13--remove-opentag_color_keywords-user-override-feature)
- [2026-06-13 — OpenTag apply: re-point this filament to exact-named canonical vendor](#2026-06-13--opentag-apply-re-point-this-filament-to-exact-named-canonical-vendor)
- [2026-06-11 — OpenTag matcher v2.1: soften hard gates + capture fill-composite descriptors](#2026-06-11--opentag-matcher-v21-soften-hard-gates--capture-fill-composite-descriptors)
- [2026-06-11 — OpenTag matcher v2: structured token decomposition + mined lexicons](#2026-06-11--opentag-matcher-v2-structured-token-decomposition--mined-lexicons)
- [2026-06-11 — OpenTag "ignore future updates" flag stored as Spoolman extra field](#2026-06-11--opentag-ignore-future-updates-flag-stored-as-spoolman-extra-field)
- [2026-06-11 — OpenTag dataset: direct GitHub tarball fetch (no FDB proxy)](#2026-06-11--opentag-dataset-direct-github-tarball-fetch-no-fdb-proxy)
- [2026-06-08 — OpenTag matching fixes + unmatched-UI enrichment](#2026-06-08--opentag-matching-fixes--unmatched-ui-enrichment)
- [2026-06-08 — Single-hex OpenTag entries use color_hex; multi_color_hexes requires ≥2](#2026-06-08--single-hex-opentag-entries-use-color_hex-multi_color_hexes-requires-2)
- [2026-06-08 — OpenTag no-match reason taxonomy + group collapse UX](#2026-06-08--opentag-no-match-reason-taxonomy--group-collapse-ux)
- [2026-06-07 — Wizard OpenPrintTag flag + filter (`db8a4c6`, `4b5db3f`)](#2026-06-07--wizard-openprinttag-flag--filter-db8a4c6-4b5db3f)
- [2026-06-07 — OPT stamped badge on OpenTag Cleanup cards (`7eb5e98`)](#2026-06-07--opt-stamped-badge-on-opentag-cleanup-cards-7eb5e98)
- [2026-06-07 — OpenTag cleanup lets the user pick from best + top-5 alternates; each candidate carries its own field comparison](#2026-06-07--opentag-cleanup-lets-the-user-pick-from-best--top-5-alternates-each-candidate-carries-its-own-field-comparison)
- [2026-06-07 — OpenTag cleanup: reviewable Manufacturer field reassigns Spoolman vendor via find-or-create](#2026-06-07--opentag-cleanup-reviewable-manufacturer-field-reassigns-spoolman-vendor-via-find-or-create)
- [2026-06-07 — Settings `opentag_vendor_aliases` maps Spoolman vendor names to OpenTag brand names](#2026-06-07--settings-opentag_vendor_aliases-maps-spoolman-vendor-names-to-opentag-brand-names)
- [2026-06-07 — OpenTag review: exact-UUID match, existing identity display, reviewable name](#2026-06-07--opentag-review-exact-uuid-match-existing-identity-display-reviewable-name)
- [2026-06-07 — OpenTag secondary_colors recovered from raw tarball; multicolor mismatch flag](#2026-06-07--opentag-secondary_colors-recovered-from-raw-tarball-multicolor-mismatch-flag)
- [2026-06-07 — OpenTag apply no longer writes multi_color_direction when secondaryColors is empty](#2026-06-07--opentag-apply-no-longer-writes-multi_color_direction-when-secondarycolors-is-empty)
- [2026-06-07 — OpenTag apply self-creates required extra fields; ensure_extra_fields is per-section resilient](#2026-06-07--opentag-apply-self-creates-required-extra-fields-ensure_extra_fields-is-per-section-resilient)
- [2026-06-07 — filamentdb_material_tags stored as CSV string in Spoolman text extra field](#2026-06-07--filamentdb_material_tags-stored-as-csv-string-in-spoolman-text-extra-field)
- [2026-06-06 — OpenTag matcher: arrangement-from-tags, polymer-family gate, finish-aware scoring](#2026-06-06--opentag-matcher-arrangement-from-tags-polymer-family-gate-finish-aware-scoring)
- [2026-06-06 — OpenTag matching hard-filters by color profile; apply sets multi_color_direction + handles empty primary](#2026-06-06--opentag-matching-hard-filters-by-color-profile-apply-sets-multi_color_direction--handles-empty-primary)
- [2026-06-06 — OpenTag matcher: color NAME is the key within-brand/material discriminator; hex demoted](#2026-06-06--opentag-matcher-color-name-is-the-key-within-brandmaterial-discriminator-hex-demoted)
- [2026-06-06 — OpenTag cleanup: instant dataset banner + staged fetch/match progress](#2026-06-06--opentag-cleanup-instant-dataset-banner--staged-fetchmatch-progress)
- [2026-06-06 — OpenTag matching pre-filters candidates by normalized brand for performance; progress logged](#2026-06-06--opentag-matching-pre-filters-candidates-by-normalized-brand-for-performance-progress-logged)
- [2026-06-06 — FDB /api/openprinttag returns OPTDatabase wrapper; bridge extracts .materials; cache self-heals malformed data](#2026-06-06--fdb-apiopenprinttag-returns-optdatabase-wrapper-bridge-extracts-materials-cache-self-heals-malformed-data)
- [2026-06-06 — OpenTag cleanup API renamed to /openprinttag/*; 120 s fetch timeout; structured fetch errors](#2026-06-06--opentag-cleanup-api-renamed-to-openprinttag-120-s-fetch-timeout-structured-fetch-errors)
- [2026-06-06 — OpenTag cleanup tool + scoped FDB settings-bag exception](#2026-06-06--opentag-cleanup-tool--scoped-fdb-settings-bag-exception)
- [2026-06-06 — OpenPrintTag finish-tag model adopted; `filamentdb_material_tags` Spoolman extra field](#2026-06-06--openprinttag-finish-tag-model-adopted-filamentdb_material_tags-spoolman-extra-field)

### Backups

- [2026-07-02 — Backup boundary excludes auth secrets and internal state](#2026-07-02--backup-boundary-excludes-auth-secrets-and-internal-state-github-57) — #57
- [2026-06-23 — Scheduled nightly backups: bridge-state + FDB snapshot only, on by default](#2026-06-23--scheduled-nightly-backups-bridge-state--fdb-snapshot-only-on-by-default-issue-5) — #5
- [2026-06-18 — BackupSafetyDialog made unconditionally friendly; debug clears moved to DebugConfirmDialog](#2026-06-18--backupsafetydialog-made-unconditionally-friendly-debug-clears-moved-to-debugconfirmdialog)
- [2026-06-11 — Backup export/import fidelity: `is_synthetic_parent`, `conflict_type`, and auth secrets](#2026-06-11--backup-exportimport-fidelity-is_synthetic_parent-conflict_type-and-auth-secrets)
- [2026-06-08 — Filament DB backup API correction](#2026-06-08--filament-db-backup-api-correction)
- [2026-06-07 — Pre-write backup safeguard dialog gates destructive actions](#2026-06-07--pre-write-backup-safeguard-dialog-gates-destructive-actions)

### Mobile & labels

- [2026-06-24 — Configurable mobile-scan auth: `mobile_session_days` (0 = public, N = login TTL)](#2026-06-24--configurable-mobile-scan-auth-mobile_session_days-0--public-n--login-ttl)
- [2026-06-23 — Mobile updates & labels (phase 3 — LabelForge label printing)](#2026-06-23--mobile-updates--labels-phase-3--labelforge-label-printing)
- [2026-06-23 — Mobile updates & labels (phase 2 frontend mobile flow)](#2026-06-23--mobile-updates--labels-phase-2-frontend-mobile-flow)
- [2026-06-23 — Mobile updates & labels (phase 1 backend foundation)](#2026-06-23--mobile-updates--labels-phase-1-backend-foundation)

### Security & auth

- [2026-07-02 — Per-IP in-memory login rate-limiting](#2026-07-02--per-ip-in-memory-login-rate-limiting-github-59) — #59
- [2026-07-02 — Secrets stored plaintext in SQLite is an accepted risk (M3 won't-fix)](#2026-07-02--secrets-stored-plaintext-in-sqlite-is-an-accepted-risk-m3-wont-fix)
- [2026-07-02 — Proxy-aware Secure cookie flag + response security headers](#2026-07-02--proxy-aware-secure-cookie-flag--response-security-headers-github-58) — #58
- [2026-06-09 — Single-account auth + API token + first-login required-settings gate](#2026-06-09--single-account-auth--api-token--first-login-required-settings-gate)

### Locations & lifecycle

- [2026-06-24 — Sync spool location in the continuous engine, compared by name (`location_sync`)](#2026-06-24--sync-spool-location-in-the-continuous-engine-compared-by-name-location_sync-github-29) — #29
- [2026-06-17 — Archive/retire to sync bidirectionally for already-synced spools (FR-21 symmetric, design agreed)](#2026-06-17--archiveretire-to-sync-bidirectionally-for-already-synced-spools-fr-21-symmetric-design-agreed)
- [2026-05-31 — FDB location semantics: locationId (ObjectId reference), pre-creation required](#2026-05-31--fdb-location-semantics-locationid-objectid-reference-pre-creation-required)

### Multicolor & filament data

- [2026-06-17 — Synced Records FDB color: capture a display hex for every mapped filament](#2026-06-17--synced-records-fdb-color-capture-a-display-hex-for-every-mapped-filament-github-2) — #2
- [2026-06-08 — multicolor writes always include multi_color_direction (Spoolman 422 fix)](#2026-06-08--multicolor-writes-always-include-multi_color_direction-spoolman-422-fix)
- [2026-06-07 — Spoolman multicolor: `multi_color_hexes` only; `color_hex` never set for multicolor](#2026-06-07--spoolman-multicolor-multi_color_hexes-only-color_hex-never-set-for-multicolor)
- [2026-06-07 — Color-name tokens split on non-alphanumeric; multicolor descriptor noise dropped](#2026-06-07--color-name-tokens-split-on-non-alphanumeric-multicolor-descriptor-noise-dropped)
- [2026-06-07 — PLA+/grade modeling: base polymer + grade in name; no material guard (`memory/pla-plus-modeling-decision.md`)](#2026-06-07--plagrade-modeling-base-polymer--grade-in-name-no-material-guard-memorypla-plus-modeling-decisionmd)
- [2026-06-06 — Filament cost sync: spool-price-first, filament fallback; matprop SoT; snapshot merge](#2026-06-06--filament-cost-sync-spool-price-first-filament-fallback-matprop-sot-snapshot-merge)
- [2026-05-31 — Structured multicolor sync supersedes the colorName projection](#2026-05-31--structured-multicolor-sync-supersedes-the-colorname-projection)
- [2026-05-30 — Multicolor filament mapping (Spoolman ↔ Filament DB)](#2026-05-30--multicolor-filament-mapping-spoolman--filament-db)

### UI, CI & infrastructure

- [2026-06-22 — Changelog archiving is summarize-on-archive (release-prep-and-cut v1.1.0)](#2026-06-22--changelog-archiving-is-summarize-on-archive-release-prep-and-cut-v110)
- [2026-06-21 — CI is push-only; CodeQL is PR-gated (no dual push+PR triggers)](#2026-06-21--ci-is-push-only-codeql-is-pr-gated-no-dual-pushpr-triggers)
- [2026-06-19 — CodeQL log-injection FPs are int path params, not `scrub`; no model pack](#2026-06-19--codeql-log-injection-fps-are-int-path-params-not-scrub-no-model-pack)
- [2026-06-19 — Defer the per-minor CHANGELOG archive (deviation from release-prep-and-cut)](#2026-06-19--defer-the-per-minor-changelog-archive-deviation-from-release-prep-and-cut)
- [2026-06-17 — Dashboard counts: spools vs filaments are independent; break out master filaments](#2026-06-17--dashboard-counts-spools-vs-filaments-are-independent-break-out-master-filaments-github-3) — #3
- [2026-06-11 — HelpTip component for in-place UI help](#2026-06-11--helptip-component-for-in-place-ui-help)
- [2026-06-11 — In-app docs viewer at /docs/:slug](#2026-06-11--in-app-docs-viewer-at-docsslug)
- [2026-06-11 — MappingRow carries `conflict_id`; Synced Records deep-links to Conflicts](#2026-06-11--mappingrow-carries-conflict_id-synced-records-deep-links-to-conflicts)
- [2026-06-10 — Debug: added POST /api/debug/full-reset](#2026-06-10--debug-added-post-apidebugfull-reset)
- [2026-06-09 — Light/dark/system theme infrastructure](#2026-06-09--lightdarksystem-theme-infrastructure)
- [2026-06-09 — Version display, GitHub update check, dev channel marker](#2026-06-09--version-display-github-update-check-dev-channel-marker)
- [2026-06-08 — gated Debug mode with reset tools for clean re-testing](#2026-06-08--gated-debug-mode-with-reset-tools-for-clean-re-testing)
- [2026-06-08 — Browser-local timestamp rendering (`d22cad8`)](#2026-06-08--browser-local-timestamp-rendering-d22cad8)
- [2026-06-08 — Sync-log windows view + `DELETE /sync-log` (`7b0361e`)](#2026-06-08--sync-log-windows-view--delete-sync-log-7b0361e)
- [2026-06-08 — Synced Records enrichment: multicolor, weight, empty, conflict deep-link (`a870950`)](#2026-06-08--synced-records-enrichment-multicolor-weight-empty-conflict-deep-link-a870950)
- [2026-06-08 — Entrypoint chown-then-gosu drop replaces static USER directive](#2026-06-08--entrypoint-chown-then-gosu-drop-replaces-static-user-directive)
- [2026-06-08 — Container runs as non-root 1000:1000; /data chowned in image (superseded)](#2026-06-08--container-runs-as-non-root-10001000-data-chowned-in-image-superseded)
- [2026-06-08 — docker-compose.yml ships bridge-only; full dev stack moved to docker-compose.dev.yml](#2026-06-08--docker-composeyml-ships-bridge-only-full-dev-stack-moved-to-docker-composedevyml)
- [2026-06-03 — CI workflows, registry, and main branch protection](#2026-06-03--ci-workflows-registry-and-main-branch-protection)
- [2026-06-01 — De-adopted the vexp-context-engine standard (sunset homelab-wide)](#2026-06-01--de-adopted-the-vexp-context-engine-standard-sunset-homelab-wide)
- [2026-05-30 — Make docker-compose deployable + SPA route fallback](#2026-05-30--make-docker-compose-deployable--spa-route-fallback)
- [2026-05-30 — Dashboard dry-run: SyncPreviewEntry shape and skip coverage](#2026-05-30--dashboard-dry-run-syncpreviewentry-shape-and-skip-coverage)
- [2026-05-29 — Phase 4 Web UI: SPA scaffold, static mount, deep-link bases, hooks](#2026-05-29--phase-4-web-ui-spa-scaffold-static-mount-deep-link-bases-hooks)
- [2026-05-28 — Canonical build-phase numbering (closes the skipped Phase 2)](#2026-05-28--canonical-build-phase-numbering-closes-the-skipped-phase-2)
- [2026-05-28 — Deep-link routes (corrects PRD NFR-7 / CLAUDE.md)](#2026-05-28--deep-link-routes-corrects-prd-nfr-7--claudemd)
- [2026-05-28 — Docker base images: node:22-alpine (build) + python:3.12-slim-bookworm (runtime)](#2026-05-28--docker-base-images-node22-alpine-build--python312-slim-bookworm-runtime)
- [2026-05-28 — Canonical version file is `backend/app/__init__.py`](#2026-05-28--canonical-version-file-is-backendapp__init__py)

<!-- decisions-topic-index-end -->


## 2026-07-19 — Purge stale filament mappings when Spoolman reuses an id, GitHub #70

**Context.** Adding a Filament DB filament to Spoolman crashed with
`UNIQUE constraint failed: filament_mappings.spoolman_filament_id`. Root cause: Spoolman stores
filaments with a plain SQLite integer PK (no `AUTOINCREMENT`), so it **reissues the highest
deleted id** on the next create. A prior manual orphan-cleanup had deleted Spoolman filaments
but left the bridge's `FilamentMapping` rows behind; a freshly-created filament was handed a
reused id and collided with the leftover mapping.

**Decision.** Two layers, both bridge-local (no upstream deletes):
1. **Crash guard (symptom).** The FDB→Spoolman create path drops any pre-existing mapping on a
   just-minted Spoolman id before inserting the new one — since we just created that id, any
   mapping already on it is definitionally stale.
2. **GC (root cause).** The sync cycle purges any `FilamentMapping` whose Spoolman filament is
   absent from the fetched set (plus that filament's now-defunct spool mappings), so a stale row
   never survives long enough to be silently re-pointed at an unrelated filament that reuses the
   freed id.

**Non-obvious choices.**
- **No auto-purge on identity mismatch.** The one case neither layer heals automatically is a
  mapping whose id was *already* reused to a live-but-unrelated filament (both sides present).
  Detecting that needs a fuzzy identity comparison, which would **false-positive on a filament the
  user legitimately renamed upstream** — purging a valid mapping and re-importing/duplicating,
  worse than the original bug. Deliberately left to explicit user action.
- **GC runs only after a successful upstream fetch.** `run_sync_cycle` early-returns on fetch
  failure, so a partial/empty fetch can never be mistaken for "all filaments deleted" and wipe
  live mappings.
- **Test-fake realism.** Exposed that some engine test fakes returned `get_filaments() == []`
  while a spool referenced a filament (impossible in real Spoolman) — fakes now derive filaments
  from the spools' embedded records.


## 2026-07-02 — Per-IP in-memory login rate-limiting, GitHub #59

**Context.** The 2026-07-02 security audit (M2) found `POST /api/auth/login` had no brute-force
protection beyond bcrypt's work factor.

**Decision.** A **per-IP, in-memory** throttle: after 5 consecutive wrong-password attempts from
one client IP, the endpoint returns HTTP 429 + `Retry-After` for a 5-minute cooldown; a correct
password resets the counter; the throttle is skipped entirely when `AUTH_ENABLED=false`.

**Non-obvious choices.**
- **Per-IP over global.** A single-admin app is often used from several devices; a global counter
  would let one device with a cached wrong password lock out the admin elsewhere. The IP comes from
  `request.client.host`, which uvicorn resolves from `X-Forwarded-For` under `--proxy-headers`.
- **In-memory (not SQLite).** No new dependency; a restart clears it — acceptable, and a restart is
  itself part of the documented recovery path (`AUTH_ENABLED=false` + restart).
- **Throttle check runs BEFORE the password-exists lookup**, so a locked IP gets 429 even in the
  `no_password_set` state (consistent, unbypassable). But **only `invalid_credentials` increments**
  the counter — `no_password_set` does not — so first-time setup is never throttled.
- **5-minute cooldown** over a shorter window: the de-facto standard; meaningfully slows scripted
  brute force while a legitimate user recovers quickly.


## 2026-07-02 — Secrets stored plaintext in SQLite is an accepted risk (M3 won't-fix)

**Context.** The 2026-07-02 security audit noted (finding M3) that the bridge stores its secrets
— `api_token`, `labelforge_token`, `auth_secret`, `admin_password_hash` — as plaintext (or a plain
bcrypt hash) in the SQLite `BridgeConfig` table, and that `GET /api/config` returns `api_token` /
`labelforge_token` to the authenticated Settings UI so the user can view/copy them.

**Decision — accepted risk, not fixed.** For a **single-admin, self-hosted LAN app** this is an
intentional tradeoff, not a vulnerability worth mitigating:
- Any attacker who can read the SQLite file already owns the data volume (and thus everything the
  bridge can do) — encrypting-at-rest with a key that must also live on the same host buys nothing.
- The API token is deliberately displayable so the user can copy it into scripts/Moonraker; it is
  "no more secret than the database file itself" (see the API-token decision).
- `GET /api/config` is auth-gated and only returns the two *display* tokens — never the cookie
  signing key or the password hash (verified: `admin_password_hash` / `auth_secret` are excluded).
- The genuinely damaging leak vector (secrets escaping the box via the **backup** export/import)
  was closed separately — see [Backup boundary excludes auth secrets](#2026-07-02--backup-boundary-excludes-auth-secrets-and-internal-state-github-57).

If the deployment model ever changes (multi-tenant, hosted, secrets shared across a team),
revisit: move to a real secrets store / at-rest encryption with an externally-provided key, and
stop returning tokens in `GET /api/config`. Until then, **won't-fix by design.**


## 2026-07-02 — Proxy-aware Secure cookie flag + response security headers, GitHub #58

**Context.** A security audit found the `fb_session` cookie's `Secure` flag was derived
solely from `request.url.scheme` (`app/api/auth.py:_is_https`), which uvicorn sees as `http`
behind a TLS-terminating reverse proxy — so the cookie shipped without `Secure`. `labels.py`
already trusted `X-Forwarded-Proto`, so the codebase was internally inconsistent. No response
security headers were set.

**Decision.**
- `_is_https` now reads `X-Forwarded-Proto` first, falling back to `request.url.scheme`. This
  is the load-bearing fix and is unit-testable via TestClient (uvicorn's `--proxy-headers` is
  a server-layer setting the test client does not exercise). The Dockerfile CMD also gains
  `--proxy-headers --forwarded-allow-ips=*` for server-layer correctness.
- A tiny `_security_headers` middleware sets `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: same-origin` via `setdefault` (never clobbering a
  route-set header).

**Non-obvious choices.**
- **No shared proto helper extracted.** The pattern is one line; a shared module would force an
  awkward cross-import between `auth.py` and `labels.py`. Behavior is now consistent even
  though the line is written in both places. (Kept per the prompt's "keep it tight" steer.)
- **`--forwarded-allow-ips=*` trust.** Acceptable because the container always sits behind the
  operator's own reverse proxy; a client with direct port-8090 access could spoof
  `X-Forwarded-Proto`. Documented in `docs/security.md` and the Dockerfile — the container must
  not be directly internet-exposed.
- **`Referrer-Policy: same-origin`** over `no-referrer` — preserves the referrer for same-origin
  API calls while suppressing it to Filament DB / Spoolman.
- **CSP and HSTS deferred to the reverse proxy** — a strict CSP for the Vite/React SPA +
  react-markdown docs viewer needs per-feature tuning and risks breakage; HSTS is harmful on
  plain-http LAN deployments and belongs at the TLS terminator.

## 2026-07-02 — Backup boundary excludes auth secrets and internal state, GitHub #57

**Context.** A security audit found the bridge-state backup treated the whole `BridgeConfig`
key→JSON store as opaque. `GET /api/backup/export` (and the nightly on-disk backup) emitted
`auth_secret` (the itsdangerous cookie-signing key), `admin_password_hash`, `api_token`, and
`labelforge_token` in cleartext (H1 — an exported file was a credential dump enabling session
forgery), and `POST /api/backup/import` applied every config key with no allowlist (H2 — a
crafted backup could overwrite the target's password hash or signing key → account takeover).

**Decision.** A single `SECRET_CONFIG_KEYS` frozenset in `app/api/config.py` names every key
that must not cross the backup boundary; export strips them and import skips them. It holds two
semantic groups under one constant (kept together deliberately — both are "must not cross the
backup boundary"): the four **auth secrets** above, and two **write-only internal-state** keys
(`backup_last_run`, `wizard_last_run`) whose per-instance run summaries are meaningless when
restored onto a different instance. The nightly on-disk backup inherits the fix because
`build_state_export` delegates to `export_backup`.

**Consequence (intended behavior change).** A restore no longer carries over the admin password
or API token — the target instance keeps its own credentials. Migrating to a new host now
requires re-setting the password/token via Settings after the restore. Documented in
`docs/security.md` and `docs/backups.md`.

## 2026-06-28 — Reconcile orphaned spools instead of silently skipping them, GitHub #48

**Context.** A Spoolman spool whose `filamentdb_spool_id` extra pointed at a still-existing
FDB spool but had **no `SpoolMapping`** was silently skipped by both the engine
(`if fdb_spool_id and fdb_spool_id in fdb_spool_index: continue  # orphan, skip`) and the
planner (`xref_is_live → action="skip"/"already linked"`). Such an *orphan* exists in both
systems but the bridge has lost the link — from a partial import, a manual merge, or a
**bridge-state reset that clears mappings while the upstream cross-refs survive**. Result:
the spool is invisible to the bridge forever (Synced Records, Mobile Updates) and never
re-detected. Confirmed in production (SM #226: in FDB, no mapping, no conflict, not in the
mobile list).

**Decision.** The engine's new-SM-spool pass now **reconciles** an orphan instead of
skipping it, via `_reconcile_orphan_spool`: when the target FDB spool is unclaimed, it
creates the missing `SpoolMapping` (linked to the FDB filament's `FilamentMapping` when one
exists, else an unlinked mapping). This runs every cycle, so it **auto-heals existing
orphans** — no manual action. Cases, by cross-ref state:

| Cross-ref | Behavior |
|---|---|
| live FDB spool, no mapping, FDB spool unclaimed | **reconcile** — create the SpoolMapping, log a `link` action |
| live FDB spool, mapping already exists | skip (the spool is in `mapped_sm_spool_ids`, handled before the cross-ref check) |
| stale cross-ref (target spool gone) | falls through to normal new-spool handling (conflict / auto-import); the re-import overwrites the dangling id |
| live FDB spool already mapped to a **different** SM spool (collision, e.g. a duplicated Spoolman spool) | don't adopt — fall through to new-spool handling so it gets its own FDB spool / a visible `new_spool` conflict |

**Principle: a spool is never silently skipped** — it is either mapped or visibly waiting in
the conflict queue. The collision guard reuses `_handle_new_sm_spool` (no new conflict
machinery). The planner's `"already linked"` preview is left as-is for now (cosmetic; it
self-heals once the engine reconciles) — a planner mirror is a possible follow-up.

## 2026-06-28 — `new_filament`/`new_spool` conflicts update in place (stable id), GitHub #44

**Context.** `_upsert_new_record_conflict` (`core/engine.py`) used **delete-and-recreate**: every
sync cycle it deleted the open conflict for an unmapped record and inserted a fresh row. Any record
that stayed unmapped across cycles (i.e. the whole migration backlog) got a **new autoincrement id
every ~120s** — observed ids climbed into the millions. The Conflicts UI holds the id from its last
list fetch; the moment a cycle fired, that id was gone, so `GET /conflicts/{id}/filament-suggestions`
and `POST /conflicts/{id}/import` (both `filter_by(id=...)`) returned **404 "No conflict with id N"**,
breaking the Add → link/import flow and leaving the preview greyed out.

**Decision.** Make the upsert **update the matching open conflict in place**, preserving its `id`;
only insert when none exists; prune any extra duplicate open rows. Same one-open-conflict-per-(item,
kind) guarantee and same match key (entity_type, field_name, spoolman_id OR fdb_filament_id OR
fdb_spool_id), but the id is now **stable across cycles**, so a held UI id stays valid. This also
stops the runaway autoincrement churn.

**Frontend guard.** The Conflicts Add flow additionally treats a `404 conflict_not_found` as a
recoverable "the list was refreshed by a background sync — reopen Add and try again" state (reloads
the list via `onResolved`) instead of surfacing the raw error. Defensive — the backend fix removes
the root cause, but it covers pre-existing stale rows and any future churn source.

## 2026-06-24 — Sync spool location in the continuous engine, compared by name (`location_sync`, GitHub #29)

**Context.** The ongoing sync engine never diffed or propagated spool **location**: a location
change made directly in Spoolman (or Filament DB) never reached the other side. Location was only
written at wizard import and the mobile-update path. Spoolman stores the location as a free-text
`location` string; Filament DB references it by `locationId` — the two cannot be compared directly.

**Decision.** Add a new **`location_sync`** category, modelled exactly on the existing `archive_sync`
(lifecycle) category: two axes — `location_sync_direction` (default `two_way`) and
`location_sync_conflict_policy` (default `manual`). `newest_wins` is **rejected (422)** because a
location name has no comparable timestamp (same rationale as `archive_sync`'s boolean).

**Compare by name.** The engine fetches `GET /api/locations` once per cycle and builds an `{_id:
name}` map, threaded into both snapshot builders the way `field_maps` is: `_sm_snapshot_dict` carries
the Spoolman `location` string (free from `model_dump()`); `_fdb_snapshot_dict` carries the FDB
location **name** resolved from `locationId` (unknown/missing id → None, which compares cleanly
against an absent Spoolman location). The differ gets `sm_location_change`/`fdb_location_change`
(None-safe string compare against the snapshot name; a missing baseline defaults to the current value
so first-sight is never a spurious change). A dedicated location pass routes through
`resolve_sync_action`: SM→FDB calls the **shared** `core/locations.py:ensure_fdb_location`
(find-or-create — never duplicated) → `update_spool({locationId})`; FDB→SM writes
`update_spool({location: name})`; both-changed-to-different-names queues a `cross_system` conflict
(`field_name="location"`, dedup via `_has_open_conflict`). After any push both snapshot location names
refresh (anti-ping-pong — a second cycle on the converged state must not re-queue). The #21
dispatcher (`apply_cross_system_conflict`) gets a `location` handler that writes the chosen name to
both sides (find-or-create on FDB) and refreshes both snapshots.

**Ordering.** Unlike the lifecycle pass (which must run *after* the weight pass so a depleted spool's
final decrement settles first), location is **independent of weight** — it has no ordering
requirement. It still lives inside the same per-pair block, immediately after the lifecycle pass, so
it shares the one snapshot-refresh path. The per-cycle FDB-locations fetch is wrapped in its own
try/except: a fetch failure degrades to an empty map (location sync becomes a no-op that cycle)
rather than aborting the whole cycle.

**Consequence.** Location now round-trips bidirectionally for mapped pairs, find-or-creating FDB
locations as needed. No env var (DB-only config, exactly like `archive_sync`). Baseline rows lacking
the `location` key are not mistaken for a change. Weight-pass snapshot refreshes thread the locations
map so they preserve (not clobber) the resolved location name.

## 2026-06-24 — Configurable mobile-scan auth: `mobile_session_days` (0 = public, N = login TTL)

**Context.** The mobile scan flow mirrored the app's auth exactly: when a password is set, a cold
phone scanning a QR label has no session and gets *access denied*. For a common use case (a shared
shop scale, labels on a shelf) the friction of logging in on every phone defeats the feature; but
making the scan flow unconditionally public would be wrong for users who *do* want it gated.

**Decision.** A single runtime setting **`mobile_session_days`** (integer, default **30**) controls
both the gate and the cookie lifetime for the scan flow, and *only* the scan flow:

- **`0` → the scan flow is public.** The three surfaces a cold scan touches — the
  `GET /r/{fil}/{spool}` redirect, the `/api/mobile/*` + `/api/labels/*` endpoints, and the SPA
  `/scan/:filId/:spoolId` route — bypass the app password. **The rest of the app stays
  password-protected.**
- **`>= 1` → the scan flow requires the normal login** (session cookie OR API token OR
  `AUTH_ENABLED=false`), AND the `fb_session` login cookie's lifetime is set to that many days. The
  default `30` reproduces the previous behavior exactly (no change on upgrade).

It is **independent of `mobile_labels_enabled`** — that master gate's 403 still fires on every
mobile/label endpoint and the redirect regardless of `mobile_session_days` (feature-gate first, then
auth).

**Implementation (security-critical wiring).** The `mobile` and `labels` routers and the `/r/`
redirect were previously included in `main.py` with the **global** `_auth_dep`
(`Depends(require_auth)`). They now carry a dedicated **`mobile_auth`** dependency instead:
`mobile_auth` returns early (public) **only** when `mobile_session_days == 0`, and otherwise runs the
**exact same** check as `require_auth` (both delegate to a shared `_has_valid_credentials` helper, so
the gated path can never be weaker than `require_auth`). **No other router was touched** — every
other surface keeps `require_auth`. The `_require_labels_enabled` 403 feature gate stays on each
mobile/label route. The cookie max-age (set on login + `setup`, and the `TimestampSigner` verify
`max_age`) reads `mobile_session_days` days when `>= 1`, else falls back to 30. `GET /api/version`
exposes `mobile_public` (= `mobile_session_days == 0`); the SPA `App.tsx` gate renders the
`/scan/...` route without login only when `mobile_public` (every other path still shows Login).

**Consequence.** Three surfaces become *conditionally* public; the blast radius is bounded to them by
construction (a distinct dependency on exactly those three registrations). The default 30 is a no-op
on upgrade. `mobile_session_days` is validated `>= 0` on write (422 otherwise).

## 2026-06-24 — Lowering a spool weight always goes through an FDB usage entry (issue #28)

**Context.** The mobile "correct weight" path and the #21 conflict-resolve path both used
`core/weight_ops.py:apply_absolute_weight`, which wrote the target to Filament DB with a direct
`PUT {totalWeight}` regardless of direction. But Filament DB only accepts a `totalWeight`
**increase** via PUT — a **decrease** must go through the usage endpoint (FDB has no other way to
reduce a spool's weight; a direct PUT to a lower value is silently ignored). Reported in the field:
a mobile correction 945→931 updated Spoolman + the bridge snapshot but left FDB at 945, and because
the snapshot was refreshed to 931 the engine then saw no discrepancy to re-push. The #21 weight path
had the same latent no-op (it only passed because the FDB client was mocked).

**Decision.** There is ONE correct FDB write rule, already used by the engine's ongoing pass:
**increase → direct `PUT totalWeight`; decrease → `log_usage(delta)`.** Made `apply_absolute_weight`
decrease-aware (it now takes `current_fdb_gross`) and removed the separate `apply_usage_weight`
(redundant). The mobile "direct_correction" and "usage" modes both converge to the absolute net
weight; on a decrease both log an FDB usage entry — the mode only flavours the entry's `source` /
`job_label` (a scale *correction* vs a *usage* decrement). Spoolman is always an absolute set.

**Consequence.** A downward "correction" necessarily creates an FDB usage entry — there is no other
mechanism to lower a spool's weight — so it appears in the FDB usage history (labelled as a
correction). Upward corrections / refills remain a direct write.

## 2026-06-24 — OpenPrintTag drying time is minutes end-to-end (issue #27)

**Context.** The bridge converted OpenPrintTag `dryingTime` (minutes) to **hours** (÷60) in the
cleanup-tool Apply value-builder (`core/opentag_match.py`) via `opentag_drying_time_to_fdb_hours`,
on the belief that Filament DB's `dryingTime` field is in hours. The ongoing material-field sync
then mirrored the Spoolman extra to FDB **1:1**. Validating FDB releases 1.50–1.57 surfaced
1.57.0 #809 ("corrected dryingTime units in the API docs"): FDB's `dryingTime` is in **minutes**
(`480` = 8 h). So the bridge wrote `8` where FDB expects `480` — a 60× error. It round-tripped
numerically (both sides held `8`), so no conflict fired, but the stored value was wrong.

**Decision.** Treat `dryingTime` as **minutes everywhere** — OpenPrintTag, the Spoolman extra
(`openprinttag_drying_time`), and FDB all agree, so the value passes through unconverted like the
other typed OPT fields. Removed `opentag_drying_time_to_fdb_hours` and the ÷60 special-case; the
ongoing 1:1 sync is unchanged (it was never the problem). No data migration — records written
under the old behavior keep the wrong value until OpenTag **Apply** is re-run on them.

**Note.** No breaking API changes were found in FDB 1.50–1.57 for the bridge's integration; this
was a pre-existing unit bug that FDB's docs correction merely revealed.

## 2026-06-23 — Cross-system conflict resolution converges (writes both sides on resolve) (issue #21)

**Context.** Resolving a standard (`cross_system`) conflict was record-only: it stored the
chosen value on the `Conflict` row but wrote nothing upstream and never advanced the snapshot
baseline. Since the underlying divergence was untouched, the next `run_sync_cycle` re-detected
it and queued a brand-new conflict — every cycle, forever. The user's pick had no effect on the
data. The lifecycle (`field_name="lifecycle"`) and `master_divergence` paths already converged
by writing both sides + refreshing snapshots; standard conflicts were the odd one out.

**Decision.** Generalize the lifecycle resolve path to ALL `cross_system` field types via
`core/conflict_apply.py:apply_cross_system_conflict(conflict, resolution, manual_value, db,
spoolman, filamentdb)`, dispatched from `POST /conflicts/{id}/resolve`. For each field it
(1) computes the target value from the conflict's stored values or the manual payload,
(2) writes it to BOTH systems using the SAME client calls + conversions as the matching engine
pass, and (3) refreshes BOTH snapshot keys to the converged value so the differ doesn't
re-detect it. Each family mirrors its pass exactly: `weight` (spool), `cost`, `multicolor`,
`material_tags`, the temperature/native-scalar/OpenPrintTag material-property fields (snapshot
key `_mp_<sm_field>`, FDB temperature objects read-modify-written), and dynamic `FIELD_MAPPINGS`
extras (snapshot baselines live on the SPOOL snapshots under `_extra_decoded` / `_field_values`,
FDB spool id resolved from `SpoolMapping`). `lifecycle` is routed through the unchanged
`apply_lifecycle_conflict`.

**Why a direct absolute weight write (no usage entry).** Ongoing SM→FDB weight *decrements*
log a Filament DB usage entry to preserve the audit trail. A human-approved conflict
resolution is a *correction*, not a print, so weight converges as a direct absolute write to
both sides (SM `remaining_weight = W`; FDB `totalWeight = W + tare`) — the same path the engine
already uses for a weight *increase*. `spoolman` → W = stored SM net; `filamentdb` → W = stored
FDB gross − tare; `manual` → the entered value, interpreted as net (Spoolman units).

**Signature-based fields.** `multicolor` and `material_tags` conflicts store a system-agnostic
*signature* string, not the raw value, so the write payload is re-derived from the chosen side's
LIVE upstream state (via `core/color` / `core/material_tags`). They reject `manual` resolution
(a multicolor/tag-set has no single scalar form) with a 422.

**Failure modes.** Any upstream write failure raises → the endpoint returns 502 and the conflict
stays open with no partial snapshot advance. A `field_name` with no known apply path raises
`UnsupportedConflictField` → 422 (visible), never a silent record-only no-op. Deletion-marker
conflicts (`__record_deleted__`) keep their record-only + mapping-cleanup behavior — there is
nothing to write upstream. `bulk-resolve` was left record-only (out of scope for the per-row fix).

**Proof.** Per-field-family tests queue the conflict via a real cycle, resolve via the endpoint,
then run a SECOND `run_sync_cycle` against the post-write state and assert no re-queue + both
sides converged (`tests/test_cross_system_resolve.py`). The old "resolve does not apply" API
test was rewritten to assert convergence.

## 2026-06-23 — Scheduled nightly backups: bridge-state + FDB snapshot only, on by default (issue #5)

**Context.** The manual `POST /backup/filamentdb` button drops a
`filamentdb-snapshot-<ts>.json` into `DATA_DIR/backups/` every time it's clicked, with no
retention — files accumulate unbounded. Issue #5 asked for an automatic nightly backup with
a "keep x days" retention.

**Decisions.**

- **Scope = bridge-state export + FDB snapshot only. Spoolman is excluded from the
  schedule.** Spoolman writes its server-side backup into its *own* volume and the bridge
  has no way to enumerate or prune it, so scheduling it would leak storage with no retention
  control. The manual `POST /backup/spoolman` button stays as-is for ad-hoc use.
- **On by default**, with a master enable plus two independent sub-toggles (bridge-state,
  FDB snapshot), all ON. The feature runs automatically once deployed.
- **Retention default 7 days**, applied only to the two prefixes the bridge writes
  (`bridge-state-` / `filamentdb-snapshot-`). Spoolman archives and unrelated files in the
  directory are never deletion-eligible. Age comes from the UTC timestamp in the filename
  (mtime fallback).
- **Schedule: nightly at a configurable UTC hour, default 03:00, minute 0** (APScheduler
  `CronTrigger`). The cron reschedules on Settings save when the hour or master-enable
  changes, mirroring the existing `sync_cycle` reschedule.
- **No Alembic migration.** The five keys are runtime-editable `BridgeConfig` KV rows seeded
  from `_DEFAULTS` (auto-seeded by the `seed_defaults` loop); env vars (`BACKUP_*`) are the
  start-up fallback, DB value wins — same env→DB precedence as `sync_interval_seconds`.
- The file-producing logic was extracted into `core/backup_job.py` so both the HTTP
  endpoints and the scheduled job share one writer/prune path (DRY).

The bridge's own `bridge.db` SQLite file still relies on a host-volume backup — the
scheduled job protects mappings/config via the bridge-state export but does not copy the DB
file itself. See `docs/backups.md`.

## 2026-06-21 — OpenPrintTag material settings sync as TYPED Spoolman extras → FDB first-class fields

**Context.** OpenPrintTag carries standardized material settings (temps, drying,
hardness, transmission distance) that Spoolman has no native field for but Filament DB
*can* store. We wanted those to land in Spoolman and mirror into FDB. (Phase 1 plan in
`prompts/done/2026-06-21-opentag-extra-fields-sync.md`.)

**Decisions (signed off 2026-06-21).**

1. **Scope = 7 material extra fields + a weight-model bonus.** The seven: nozzle temp
   min/max, drying temp, drying time, Shore A/D hardness, transmission distance. The
   bonus populates Spoolman's *native* `spool_weight` (from OPT container `emptyWeight`)
   and `weight` (from OPT package `nominalNettoFullWeight`) via a new
   material-slug → package → container lookup (the cache already parses
   `packages_by_material` / `containers_by_slug`; nothing read them before).
2. **Typed, not the legacy all-text pattern.** The seven extras register as Spoolman
   `integer`/`float` fields. `ensure_extra_fields` omits `default_value` for numeric
   fields (Spoolman 422s on a `""` default for a numeric field). Values still travel
   JSON-encoded on the wire (`230` ↔ `"230"`), so `encode/decode_extra_value` is unchanged.
3. **OPT → Spoolman only via the existing review/confirm Apply flow** (not automatic each
   cycle). `opt_to_spoolman_fields` emits the seven extras (and the two native weight
   fields when package/container data is supplied) so they surface as review rows and the
   existing `_build_sm_patch` Apply path writes whatever the user confirms.
   **`dryingTime` is OPT minutes → FDB hours (÷60)** applied at emit time
   (`opentag_drying_time_to_fdb_hours`; sample 360 → 6 h). Verified against the dataset.
4. **Spoolman ↔ FDB rides the existing field-sync logic — no bespoke precedence.** A new
   engine pass `_sync_opentag_material_fields` mirrors the seven SM extras ↔ their FDB
   first-class fields under the **material-properties** category's `direction` +
   `conflict_policy`, structured exactly like `_sync_material_scalars`: per-field
   `_mp_<sm_key>` baseline, `resolve_sync_action`, master/variant gate via
   `should_skip_inherited` (inherited+diverged → `master_divergence`, no write), and BOTH
   snapshots refreshed after any write (anti-ping-pong). The two nozzle-range targets are
   dotted `temperatures.*` and write via a read-modify-write that preserves sibling temps.

**Weight-model interaction (handled carefully).** `spool_weight` is the tare in the
net↔gross conversion. It is only ever written by the **user-confirmed** Apply flow, never
automatically per cycle, so it cannot start a weight loop on its own; and because the
weight sync stores gross on FDB / net on SM and refreshes both snapshots after each
propagation, changing the tare only affects the conversion applied to the *next* genuine
weight change — it does not itself emit a weight write. `weight` (nominal full net) is not
part of the conversion math.

## 2026-06-21 — `never_import_empties` is honored by the ongoing engine (not just the wizard)

**Context.** `never_import_empties` was documented (CLAUDE.md) as making "the wizard AND ongoing
new-spool import skip empty/archived spools," but the engine never referenced the setting. Archived
spools were already excluded from new-spool detection (active-only `sm_spools`, engine.py ~2546),
but **empty (0 g) active** spools fell through to the `manual_review` path and were re-queued as a
`new_spool` conflict every cycle — they can never auto-import, so the conflict just regenerated
forever (observed on Amolen "PLA Basic-High Speed Cream Yellow", SM spool 208).

**Decision.**
- The new-spool detection loop now skips a zero-remaining spool when `never_import_empties` is on
  (mirrors the wizard import gate and the existing archived exclusion), logging a `skip` instead of
  queuing a conflict.
- The stale-conflict pass now also **auto-resolves** any open `new_spool` conflict whose spool has
  since become **archived** (regardless of the gate — archived never enters new-spool detection) or
  **empty with the gate on** (`resolution="resolved_not_imported"`), so pre-existing conflicts from
  before this fix clear themselves rather than lingering.
- **Out of scope (left as-is):** the active-only exclusion at ~2546 unconditionally drops archived
  spools from new-spool detection even when `never_import_empties` is OFF — so the ongoing engine
  never imports an unmapped archived spool as a retired FDB spool the way the wizard does. Not
  changed here (the affected user runs with the gate ON); flagged for a future pass if needed.

## 2026-06-21 — CI is push-only; CodeQL is PR-gated (no dual push+PR triggers)

**Context.** Both `ci.yml` and `codeql.yml` triggered on `push: [dev, main]` AND
`pull_request: [main]`. During an open `dev→main` PR, every push to `dev` fired both
events, producing two check runs with the **same name** (`CI / Lint`,
`CodeQL / Analyze (python)`, …) on the PR head. GitHub branch protection requires those
contexts by bare name, and the duplicate left them stuck at "Expected — Waiting for
status to be reported" — forcing a manual merge bypass (used once, for v0.3.1). Branch
protection on `main` is **non-strict** (`strict: false`), so a check on the PR head
commit satisfies the requirement regardless of which event produced it.

**Decision — each required context is produced exactly once per PR:**
- **`ci.yml` → `push: [dev, main]` only** (dropped `pull_request`). Every dev push still
  gets the full, cheap CI suite (fast feedback); the PR's required CI checks are already
  on the head commit, so the gate is satisfied with no second run. CI is light enough to
  run on every dev push.
- **`codeql.yml` → `pull_request: [main]` + `push: [main]` + weekly cron** (dropped `dev`
  from push). The PR is the gate — `pull_request` scans changes before they can reach
  `main` (the modern replacement for the old direct-to-main scan that originally motivated
  broad push triggers), and `push: [main]` keeps the default-branch baseline current.
  CodeQL is heavy, so it does NOT run on every frequent dev push.

**Trade-off accepted.** CodeQL no longer reports the instant a `dev` push introduces an
issue; it surfaces when the PR is opened (which scans the accumulated diff). With the
batch-dev-then-PR-at-release flow, the PR is the natural checkpoint. A future session
should NOT "restore" `pull_request` on CI or `dev` push on CodeQL — that reintroduces the
duplicate-context bypass.

## 2026-06-19 — CodeQL log-injection FPs are int path params, not `scrub`; no model pack

**Context.** A recurring set of `py/log-injection` (CWE-117) alerts kept needing manual
"false positive" dismissals on every PR. The working assumption (mine and the maintainer's)
was that they were `core/log_safe.scrub()`-sanitized values that CodeQL couldn't recognize
across the helper-call boundary, and the planned fix was a models-as-data `barrierModel` pack
declaring `scrub()`'s return a `log-injection` barrier, published to GHCR.

**Investigation.** Built a local CodeQL 2.25.6 database and decoded the taint paths for all 8
alerts. Two findings overturned the premise:
1. **None of the 8 flow through `scrub`.** Every one traces to an **integer FastAPI path
   parameter** (`conflict_id: int`, `filament_id: int`) logged via `%d`. CodeQL flags them as
   active-threat sources because it doesn't model FastAPI/Pydantic int coercion — but an `int`
   can't carry a newline, so they are genuine false positives of a *different* kind.
2. **`scrub` already sanitizes — with no pack.** CodeQL ships a built-in
   `ReplaceLineBreaksSanitizer` (in `LogInjectionCustomizations.qll`) that recognizes a
   `.replace("\n", " ")` / `.replace("\r\n", …)` call. `scrub`'s final `.replace("\n", " ")`
   matches it, which is why the *exception* / `resp_body` values we already wrap in `_scrub`
   were never flagged. The GHCR pack loaded correctly but changed the alert count by **zero**.

**Decision.**
- **No CodeQL model pack.** The `barrierModel`/GHCR approach was abandoned and fully reverted
  (publish workflow, `.github/codeql/`, `config-file` wiring, `packages: read`). It fixed
  nothing the built-in sanitizer didn't already cover and added permanent maintenance
  (version-bump + republish on every model change). A future session should NOT re-attempt it.
  (An orphaned private package `ghcr.io/crzykidd/log-safe-models@1.0.0` was published during the
  experiment; delete it in the GHCR UI when convenient — harmless if left.)
- **Real fix: route the int path params through `_scrub()`** at the 8 log sites
  (`api/conflicts.py` ×3, `api/opentag.py` ×5), switching their `%d` to `%s`. This sends them
  through the built-in line-break sanitizer; verified locally that `py/log-injection` drops
  **8 → 0**. It's consistent with the same lines that already `_scrub(exc)`.
- **Why bother, since they were dismissed?** Dismissals are per-alert manual toil that recurs
  for every new int-param log line. The code fix turns them from "dismissed" to "fixed" and
  prevents recurrence. Marginal but cheap and proven.

## 2026-06-19 — Defer the per-minor CHANGELOG archive (deviation from release-prep-and-cut)

The adopted `release-prep-and-cut` standard archives the previous minor series into
`docs/CHANGELOG-<minor>.x.md` on every new-minor release. For v0.3.0 we **deliberately skipped**
that step: `CHANGELOG.md` keeps the full history (`0.2.0` + `0.2.1` + `0.3.0`) in one file. We'll
archive at some later point, not per-minor. So a future release session should NOT "fix" the
missing archive — the single-file changelog is intentional until we decide to split it.

## 2026-06-19 — "Missing values" report audits OpenPrintTag, not the user's spools

**Context.** The completeness report had drifted into a *diff against the user's data*: each
missing OPT field carried a "Your value (hint)" pulled from Spoolman, and the audit was
material-only. That conflated two questions and produced false signals — e.g. RED
(`elegoo-pla-red`) showed "Product URL missing" even though its **package** URL is set, because
the report only knew the material-level `productUrl` and had no package/container layer.

**Decision.** The tool audits **OpenPrintTag's master DB**, full stop. The user's inventory only
**scopes which records to audit** (filaments with `openprinttag_uuid`).
- **List every OpenPrintTag-supported empty field** (`v in (None, "", [])`) across **material +
  each package + that package's container**, using the `SUPPORTED_*_FIELDS` constants as the
  single source of truth. No second field list in `api/opentag.py`.
- **Removed the "Your value (hint)" column and all Spoolman-value comparison.** The payload
  dropped `attributes:[{…, your_value, opt_value}]` for `sections:[{scope, fields:[labels]}]`
  (scope = `"material"` | `"package:<slug>"` | `"package:none"` | `"container:<slug>"`).
  `_your_value_hint` and `OpenTagMissingAttribute` were deleted.
- **No applicability / N-A pre-judging.** Every supported empty field is listed regardless of
  material type — the user decides what's worth submitting. (secondaryColors stays conditional
  on multicolor, the one legitimate "doesn't apply" case, preserved from before.)
- **Material `url` vs package `url` are distinct line items**, reported at their own levels, so a
  set package URL no longer masks a real material-URL gap (and vice-versa). Verified live on
  `elegoo-pla-red`: package `url` is set (not flagged), package `gtin` is the real gap (flagged),
  material `productUrl` is genuinely empty upstream and correctly listed under Material.
- **Packages are 1→N**: each package is its own section; a material with **no package** is a gap
  ("No package data").
- **`heatbreakTemperature` is excluded** from the audit (`_REPORT_EXCLUDED_MATERIAL_KEYS`): the
  ingest confirmed 0 upstream occurrences, so it would falsely show "missing" on every record.

**Notes / deviations.**
- "No false material-url gap" from the prompt means the **package** URL (which is set) is no
  longer mis-reported. The material `productUrl` being listed on RED is *correct* — it is truly
  empty upstream; the fix is that the two URLs are now separate signals.
- The compute stays offloaded to `run_in_threadpool`; stale-tag rows are preserved unchanged.

## 2026-06-19 — OpenPrintTag dataset: ingest the full supported schema (material + packages + containers)

**Context.** The completeness report must show *every* OpenPrintTag-supported field that's
empty for a matched record, and the per-record contribution UI needs the real source-of-truth
fields. The parser kept only a material subset and dropped the **package** and **container**
layers entirely. That both omitted real gaps and *mis-reported* — e.g. flagging "Product URL
missing" when the URL actually lives at the package level, and collapsing chamber temp to a
single value.

**Decision.**
- **Material parse keeps the full upstream `properties` set.** Added `hardnessShoreA`,
  `heatbreakTemperature`, and **distinct** `chamberTempMin`/`chamberTempMax` (kept the
  collapsed `chamberTemp` for back-compat so the matcher and existing consumers are
  untouched). The material-level `url` already maps to `productUrl`. ADD-only — no existing
  key renamed.
- **Two new tarball passes over the same single download** build `packages_by_material`
  (`{material_slug: [package…]}`, 1→N per material: `slug`, `uuid`, `gtin`, `brandSpecificId`
  (SKU), package `url`, `nominalNettoFullWeight`, `filamentDiameter`,
  `filamentDiameterTolerance`, `containerSlug`) and `containers_by_slug` (`uuid`, `name`,
  `class`, `brand`, `emptyWeight`, `outerDiameter`, `innerDiameter`, `holeDiameter`, `width`).
  No second fetch.
- **Canonical supported-field schema** lives as module constants in `opentag_cache.py`
  (`SUPPORTED_MATERIAL_FIELDS` / `SUPPORTED_PACKAGE_FIELDS` / `SUPPORTED_CONTAINER_FIELDS`) —
  the single source of truth the completeness report (next task) checks emptiness against.
- **Cache shape is versioned** via `CACHE_SCHEMA_VERSION` (currently 2). An older-shaped
  cache (no `schema_version`, no packages) is treated like a missing cache → forced re-parse
  from the tarball, mirroring the `lexicon_version` self-heal. `_save_cache`/`_load_cache`/
  `get_cache_metadata` carry the new keys; `materials`/`commit_sha`/`fetched_at` untouched.

**Notes / deviations.**
- `heatbreak_temperature` was named in the source prompt's verified facts but does **not**
  exist anywhere in the current upstream dataset (confirmed: zero occurrences across 13k+
  materials; `preheat_temperature` is the only heat-related key). The key is still mapped for
  forward-compatibility but is always `None` today.
- Container `emptyWeight` is the **spool tare** — a strong candidate input for a future
  weight-model improvement (today the bridge defaults missing tare to ~200 g). Ingested now,
  **out of scope** for any weight-model change here.
- FFF-only filter unchanged: ~12.9k of 13.1k materials kept; ~2.8k materials carry packages;
  78 containers.

## 2026-06-18 — Parent/variant + OpenPrintTag rework: PARKED, blocked on upstream

The bridge currently writes all material props + OpenPrintTag identity on each **variant** and
leaves the `generic_container` **master** bare — the inverse of Filament DB's design (FDB
inheritance is value-presence/live-on-read; shared data belongs on the parent, variants override
only color + genuine diffs; OpenPrintTag is meant to be linked at the **parent** so variants
inherit and a single sync propagates). Aligning would mean: shared standardized specs on the
master, variants set only color/colorName/own-OPT-id/diffs (shared fields left null to inherit).

**Parked** pending the upstream author's direction — it hinges on two FDB questions hyiger is
actively analyzing: (1) can a colorless abstract parent hold an OpenPrintTag link without being
forced a color; (2) will the parent "act as a filament" / auto-promote (and is it configurable).
See **hyiger/filament-db #597 and #605**. Do NOT build the rework until that resolves.

Full analysis + the contingent approach + code touch-points are captured in homelab-configs
`projects/3dprinting/docs/parent-variant-and-openprinttag.md`. The master's OpenPrintTag pick
would hook into the wizard's existing "which filament settings to use as master" prompt.

## 2026-06-18 — OpenTag dataset: gate the heavy tarball download behind a commit-SHA check

**Context.** The OpenPrintTag dataset is a large GitHub tarball. Every manual **Refresh
dataset** and every stale auto-reload (`OPENTAG_CACHE_MAX_AGE_HOURS`, default 24 h)
re-downloaded and re-parsed the whole thing, even when upstream hadn't changed. The total
record count isn't knowable without downloading+parsing, so it can't gate the download — but
the upstream `main` HEAD commit SHA is a cheap, exact "did anything change?" signal.

**Decision.**
- Store the upstream `commit_sha` in `opentag_cache.json` next to `count`/`fetched_at`/
  `materials`/`lexicon` (extended `_save_cache`, the cache-shape doc comment, and
  `get_cache_metadata`). A fresh download captures the SHA via `get_upstream_commit_sha()`.
- `get_upstream_commit_sha()` does `GET …/commits/main` with `Accept:
  application/vnd.github.sha` (plain-text 40-char SHA, no JSON parse), short 15 s timeout. It
  is **best-effort and never raises**: timeout / connectivity / non-2xx (GitHub
  unauthenticated rate-limit = 60/hr/IP) / unexpected body all return `None`, and the caller
  falls back to downloading. A failed check must never 500 a refresh.
- `load_opentag_dataset` fetch gate reworked into explicit intents (`force_pull`,
  `force_check`; legacy `force=True` aliases to `force_pull`):
  - **stale or `force_check`** with a stored SHA → fetch upstream SHA; if it matches, rewrite
    **only** `fetched_at` (keep materials/count/SHA/lexicon), return `unchanged=True`, **no
    download**; if it differs / the check failed / no SHA was stored → download.
  - **`force_pull`** → skip the SHA check, always download.
  - **missing/invalid cache** → always download.
- `POST /api/openprinttag/refresh` defaults to the SHA-checked path (returns
  `{ unchanged, count, fetched_at, commit_sha }`); `?pull=true` forces the download. The
  existing timeout/HTTP-error envelopes (504/502) are unchanged.
- UI: a hash-checked Refresh that finds no change shows *"Dataset already up to date (commit ·
  N records)"*, bumps the banner age, and reveals a **Pull contents anyway** button (the
  `?pull=true` variant); when the dataset is unchanged the heavy match recompute is also
  skipped. Count is display-only info; the decision keys off the SHA.
- The match-result cache `dataset` fingerprint now prefers `commit_sha` (`sha:<sha>`), falling
  back to `count:fetched_at` when the SHA is unknown — so a hash-only refresh that doesn't
  change the data doesn't spuriously flag the cached match `stale_inputs`.

**Why not gate on count.** The count requires a full download+parse, so it can't be the cheap
signal. The commit SHA is one tiny request and is exact.

**Why tolerant of SHA-check failure.** GitHub's unauthenticated limit is low (60/hr/IP); a
rate-limited or flaky check must degrade to "download as before," never break refresh.

## 2026-06-18 — OpenTag matching: offload CPU off the event loop + cache the last result

**Context.** `GET /api/openprinttag/matches` ran the dataset load + scoring synchronously on
the FastAPI event loop. Because the matcher scores every Spoolman filament against the
brand-gated slice of the ~11k-entry dataset, a single match blocked *all* other API requests
until it finished (the "everything is busy" symptom). It also recomputed from scratch on
every page visit.

**Decisions.**
- **Offload the pure-CPU work to a worker thread.** All async I/O — the dataset load
  (`load_opentag_dataset`), the BridgeConfig alias read, and `sm.get_filaments()` — is awaited
  on the event loop first, then the scoring runs via `starlette.concurrency.run_in_threadpool`.
  The CPU part was extracted into module-level pure helpers (`_compute_matches`,
  `_compute_completeness`, `_compute_search`) that take plain data and return plain data — **no
  httpx, no SQLAlchemy session, no `request` access inside the thread**. The matcher
  (`core/opentag_match.py`) was verified pure (only dict `.get` / Pydantic reads), so it was
  safe to call from the thread unchanged. Same offload applied to completeness and search.
- **Cache the last match result to a DATA_DIR file** (`opentag_matches_cache.json`), mirroring
  the `core/opentag_cache.py` pattern in a new `core/opentag_match_cache.py`. Stores the
  `OpenTagMatchesResponse` payload + `computed_at` + a fingerprint. `GET …/matches` serves the
  cache instantly when present; it recomputes only on the first match or with `?recompute=true`.
- **Fingerprint on count + fetched_at (documented fallback).** The sibling
  `…-opentag-smart-dataset-refresh` work (stable dataset commit-SHA identity) is **not landed**,
  so the dataset fingerprint is `count:fetched_at`. The fingerprint also covers the Spoolman
  filament count and a sha1 of the alias CSV + material-tag map + openprinttag field names.
  When any component differs from the cached inputs the cache is still served (never silently
  stale) but flagged `stale_inputs` so the UI prompts for a refresh. Swap in the commit-SHA
  when that work lands.
- **Recompute trigger = `?recompute=true` query param** (not a separate endpoint) — it reuses
  the same route, runs the offloaded match, and re-caches. The frontend's Refresh-match /
  Refresh-dataset buttons and post-Apply reloads pass it; ordinary revisits don't.
- **Frontend:** load the cached result on "Match to DB", show "last matched &lt;time&gt;" + a
  stale-inputs hint + a Refresh affordance, and abort the in-flight match fetch on unmount via
  an `AbortController` (the abort alone doesn't fix the server-side freeze — the offload does —
  but it clears the client loading state immediately on navigation).

**Test contract note.** Because a config change between two plain `GET …/matches` calls now
serves the cached result (with `stale_inputs`), the existing alias test was updated to pass
`?recompute=true` on its second call — the documented way to force a re-score under changed
config.

## 2026-06-18 — OpenTag inline unmatch/re-match: scoped FDB settings{} *removal* exception

**Context.** Users could apply an OpenTag identity but had no in-app way to clear or
re-point one — they had to hand-edit Spoolman extras or run the debug bulk-clear. Two
sub-decisions were needed: (1) how to surface alternates for an already-tagged row whose
exact-UUID match bypasses fuzzy scoring, and (2) how "unmatch" removes the identity from
Filament DB given CLAUDE.md's blanket "never touch `settings{}`" rule.

**Decisions.**
- **Un-bypass alternates for tagged rows.** The exact-UUID branch in `opentag.py` still pins
  the matched record at confidence 1.0 / index 0, but now also runs the same gate pipeline
  (extracted into a local `_gated_candidates_for` helper, shared with the untagged branch — no
  logic fork) + `find_best_match(..., top_n=10)` and returns `candidates = [current] +
  alternates` (the pinned UUID is deduped out of the alternates). **No scorer changes.** A
  single-entry brand correctly yields `[current]` only.
- **Unmatch integrates into the existing Apply flow, not an immediate action.** The candidate
  dropdown gains a blank "— unmatch —" option (sentinel index `-1`), shown only for rows that
  already carry an identity. Selecting it stages a decision with `clear_identity=true`; the
  existing Apply step performs the clear. This keeps one apply action consistent with the rest
  of the page (a standalone `POST /api/openprinttag/clear/{id}` exists too, for callers that
  want an immediate clear).
- **Clear = blank SM slug/uuid AND remove only those two keys from the FDB `settings{}` bag.**
  The SM side reuses the debug-clear blanking convention (encode `""`). The FDB side is a new
  **approved scoped *removal* exception**, the mirror of the existing
  `merge_filament_settings`: `FilamentDBClient.remove_filament_settings_keys()` does a
  read-modify-write that deletes ONLY `openprinttag_slug`/`openprinttag_uuid`, preserves every
  other key, and is idempotent (no PUT when neither key is present). It is the only permitted
  removal path; callers must pass only those two keys.
- **`openprinttag_ignore` is NOT cleared by an unmatch** — it is a separate suppression concern
  and clearing it would silently re-enable update banners.
- **FDB removal is best-effort; the SM blank is authoritative.** A missing FDB mapping (no
  `filamentdb_id` cross-ref) or an FDB write error is logged (scrubbed via `core/log_safe`) and
  does not fail the unmatch — the SM identity is still cleared. The FDB filament id comes from
  the decision or is resolved from the SM filament's `filamentdb_id` extra.

## 2026-06-18 — OpenTag completeness report: assess the raw OPT record, not the lossy field path

**Context.** New "Show missing values" report tells the user which OpenPrintTag entries are
worth enriching. We had two ways to read an OPT record's fields: the per-field mapping path
(`opt_to_spoolman_fields` / `_build_candidate`) used by the match-review UI, and the raw
OPTMaterial dict from the cache.

**Decision.**
- **Inspect the raw OPTMaterial dict directly.** The field-mapping path is built for SM↔OPT
  drift, not OPT self-completeness — it strips finishes, remaps/drops temps, hard-codes
  diameter, only emits non-None fields, and omits chamber/preheat/drying/hardness/transmission/
  photo/product entirely. Routing completeness through it would under-report missing fields.
  The endpoint reads `by_uuid[uuid]` and tests each raw key.
- **Missing = empty VALUE, not absent key.** Every OPTMaterial carries all 25 keys, so the
  test is `v in (None, "", [])`. An empty `tags` list counts as missing.
- **Field set = ingested attributes only.** Core + extended FFF attributes, plus conditional
  `secondaryColors` (multicolor only — SM `multi_color_hexes` set OR an OPT `coextruded`/
  `gradient`/`gradual_color_change` tag). Identity and the always-null
  `completenessScore`/`completenessTier` are excluded. The bridge does NOT ingest a few
  upstream fields (`hardness_shore_a`, `heatbreak_temperature`, `max_chamber_temperature`,
  typed/multiple photos); rather than extend the parser now, the report covers ingested fields
  only and the UI/docs note the gap as a possible follow-up.
- **"Your value" is a best-effort hint, never the count driver.** Mapped where sensible
  (type←material, color←color_hex, density, nozzle/bed temps←settings, secondaryColors←
  multi_color_hexes); blank otherwise. The headline is always "the OPT record lacks X."
- **Stale tags surfaced, not dropped.** A tagged filament whose uuid isn't in the current
  dataset is returned as a distinct `stale_match` row (sorted to the top under most-missing)
  so the user can re-match or refresh rather than wonder why it vanished.
- **Default sort = most-missing; complete records hidden by default** with a toggle. Single
  endpoint pass, no pagination (dataset is local and small).

## 2026-06-18 — OpenTag Cleanup: toolbar view-switch in component state; Reprocess moves to banner

**Context.** Toolbar has three actions (Refresh dataset / Match to DB / Show missing values).
The view-switch needs to be tracked somewhere so the toolbar highlights the active action and
gates what renders below.

**Decision.** `toolbarView: 'idle' | 'match' | 'missing-values'` lives in component state on
`OpenTagCleanup`. This is purely presentational routing — no URL change — because the tool is
already a single full-page component with its own internal state machine (`Step`, `viewMode`).
Adding a URL param for three states on an already-stateful page adds nav complexity with no
real benefit (no shareability needed; the match results aren't bookmarkable anyway).

The previous "Reprocess records" and "Refresh dataset" buttons were both in the dataset-status
banner. After the toolbar restructure, **Refresh dataset** became a toolbar action (primary
action, always visible). **Reprocess records** moved to the banner but is now shown only after
a match has been loaded (it's meaningless until then). The banner remains always-visible so
the dataset age/stale state is always readable regardless of which toolbar action is active.

The `getOpenTagMissingValues` stub was added to `client.ts` (endpoint not yet on the backend)
so the completeness-report prompt can import and call it without touching `client.ts` again.

## 2026-06-17 — Dashboard counts: spools vs filaments are independent; break out master filaments (GitHub #3)

**Context.** A user read the Dashboard's "In Sync = 49" next to "Filament DB = 38" as a sync
failure. Verified against the live instance: 49 is the **Spools** In-Sync tile (49 spool
mappings) and 38 is the **Filaments** Total tile (38 real filament mappings); 49 spools live on
38 filaments (6 own >1). Both are correct — it is normal spool-per-filament fan-out, not a bug,
and synthetic masters are already excluded from the 38. The reporter's masters instinct did,
however, expose a real inconsistency: the **Connected systems → Filament DB** tile reported the
raw FDB total (50, including the 13 `(Master)` containers) — the only bridge surface that did
not exclude them.

**Decision (presentational; no count is recomputed as "correct"/"wrong").**
- The fix is clarity, confirmed with the user: row 1 is Spools, row 2 is Filaments, counted
  independently. Added help text on both Dashboard sections stating a filament can hold several
  spools, so the two totals legitimately differ.
- The Connected systems → Filament DB line now **breaks out** real filaments and masters
  (`filaments: 37  masters: 13`) instead of dropping or hiding them — chosen over silently
  showing 37 so the line reconciles with both the rest of the bridge and Filament DB's own UI
  (which shows 50). The breakout appears only when masters > 0, so it is **self-gating**:
  `promote_color`/`unset` installs have no masters and see no change — no `variant_parent_mode`
  branch needed.
- Master detection consolidated into one canonical helper `core/masters.is_master_fdb(fil,
  marker, synthetic_ids)` (signals: synthetic-parent id ∪ `hasVariants` ∪ marker-suffix), now
  reused by `wizard.py`, `reconcile.py`, and the new `services/filamentdb.health()` count, so
  the previously-divergent copies can't drift. `services/filamentdb.health()` gained a
  `container_marker` param and returns `master_filament_count`; `api/health._check_filamentdb`
  resolves the marker from a request-scoped session (the `/health` route now takes
  `db: Session = Depends(get_db)`), and `db` is optional so connectivity-only callers
  (wizard/sync) are unaffected. The marker resolver moved to `api/config` next to the other
  config-store helpers.

## 2026-06-17 — Synced Records FDB color: capture a display hex for every mapped filament (GitHub #2)

**Context.** Synced Records showed "—" for the Filament DB color on solid filaments (e.g.
"Beige"), even when the color was set and matched Spoolman. Verified against the live
instance: FDB "ELEGOO PLA Beige" has `color="#DAC7A0"` and its bridge snapshot carried
`_cost`/`_finish_sig`/`_mp_*` but no `_mc_color`. The detail reads `_mc_color`
(`api/mappings.py`), which was written **only** by the multicolor sync pass `_sync_multicolor`
— and that pass `continue`s on purely-solid filaments before storing anything
(`engine.py`, "purely solid — the generic color field sync handles it"). So 25 of 37 FDB
filament snapshots (the solids) never captured a display color. A secondary problem: when the
pass did write `_mc_color`, it stored the bare `color` field, which is `null` for
coextruded/gradient filaments (real hexes live in `secondaryColors`) → also "—".

**Decision.**
- The display color is captured for **every** mapped filament, not just multicolor ones. The
  capture moved to the top of `_sync_multicolor`'s loop (before the solid-skip `continue`),
  gated on `not dry_run`, using the list-view color; the multicolor path still refines it from
  the variant-resolved detail.
- New helper `core/color.py:fdb_representative_hex(color, secondary_colors, opt_tags)` resolves
  one representative display hex (single → `color`; gradient → primary; coextruded → first
  secondary; colorless container → `None`). Built on the existing `fdb_multicolor_to_sm` so
  multicolor filaments stop rendering "—".
- The stored hex is normalized to the Spoolman convention at the read site
  (`mappings.py:_build_detail` via `to_sm_color`) so a truly in-sync solid color reads as
  matched against `color_hex` (FDB stores `#AEB8C1`, Spoolman stores `AEB8C1`).
- Genuinely colorless records (Master/container parents) correctly stay `None`/"—" — no color
  is synthesized. Existing stale snapshots self-heal on the next sync cycle (no backfill).

## 2026-06-17 — Archive/retire to sync bidirectionally for already-synced spools (FR-21 symmetric, design agreed)

**Context.** Archive/retire lifecycle state is import-only and one-directional today
(FR-21 "Partial"). A mapped spool archived in Spoolman drops out of the active set
(`engine.py:2505` filters `if not s.archived`) and silently stops syncing while staying
live in FDB; a spool retired in FDB never propagates to Spoolman (the differ never reads
`retired`). Users archive/retire depleted spools routinely, so paired spools drift out of
sync. Design agreed with the user; implementation tracked in
`prompts/2026-06-17-archive-retire-bidirectional-sync.md`.

**Decisions.**
- **Keep the bulk-import gate, add post-sync mirroring** — intentionally asymmetric. The
  wizard's `never_import_empties` gate (which also skips archived spools at import) stays:
  unmapped archived spools are NOT auto-imported during ongoing sync. But a spool that
  flips archived/retired *after* it's mapped IS mirrored to the other side. Import is about
  not cluttering FDB with already-dead inventory; mirroring is about keeping already-paired
  spools honest.
- **Split the archived-spool filter by purpose.** New-spool detection keeps the active-only
  set (preserves the import gate); mapped-pair diffing uses active + archived so the
  archive transition reaches the differ. The data is already fetched (the Spoolman client
  returns active + archived).
- **Mirror both directions of the boolean flip** — archive→retire and un-archive→un-retire.
  Same mechanism; un-archiving re-enables weight sync for the pair.
- **New independent policy category `archive_sync`** (two axes: `archive_sync_direction`
  default `two_way`, `archive_conflict_policy` default `manual`), resolved by the existing
  `resolve_sync_action`. No timestamps → `newest_wins` is not applicable to this category.
- **No new conflict type.** Reuse `cross_system`. The common one-sided flip is a clean push,
  not a conflict; only genuine divergence (both sides flipped to opposite states since the
  last snapshot) queues a conflict — consistent with the "never auto-resolve conflicts" rule.
- **Weight settles before the archive bit — ordering is a correctness requirement.** The
  lifecycle pass runs AFTER the weight pass, not before. A spool is usually archived/retired
  right as it hits ~0 g; the final weight decrement and its FDB usage-log audit entry
  (`POST …/usage`, `source:"spoolman"`) must be propagated and both snapshots refreshed
  *before* the archive/retire bit is mirrored. Mirror first and the far side would land
  retired/archived carrying a stale (too-high) weight with its final usage entry lost. Do not
  skip the weight pass for an about-to-be-archived spool; a spool already dead on both sides
  from a prior cycle NOOPs the weight pass naturally (snapshots converged).
- **Anti-ping-pong is mandatory.** After any lifecycle push, refresh BOTH snapshots to the
  converged value (same rule as the 2026-06-10 weight fix below).
- **Reword, don't rename.** The `never_import_empties` config key stays; only its
  human-facing label/help text is reworded to make clear it skips empty AND archived spools
  at import and that ongoing sync mirrors lifecycle state regardless of the setting.

**As built.** Implemented as designed above, with two deviations the implementer flagged:

- **Lifecycle conflict resolution writes upstream** via a scoped
  `core/conflict_apply.py:apply_lifecycle_conflict` rather than the generic record-only
  `cross_system` resolve path. A normal `cross_system` resolution only records the chosen
  value (no upstream write), but a lifecycle conflict's choice is a concrete boolean state,
  so resolving it (`spoolman`/`filamentdb`/`manual`) writes that boolean to BOTH systems
  (`spoolman.update_spool({"archived": …})` + `filamentdb.update_spool({"retired": …})`),
  refreshes both snapshots, and logs under a `conflict_apply` cycle id. The conflicts API
  routes `field_name == "lifecycle"` to this helper before the generic record-only branch;
  an upstream failure leaves the conflict open (`502 upstream_write_failed`).
- **Both-changed-to-same-state collapses to a converge before the resolver is called.** The
  engine detects `both_changed_converged` (both sides flipped this cycle AND landed on the
  same state, e.g. both archived) up front and treats it as a NOOP-with-snapshot-refresh,
  so `resolve_sync_action` / `QUEUE_CONFLICT` is only ever reached for a genuine
  opposite-state divergence. This keeps the common "user archived in both systems"
  case from spuriously queuing a conflict.

**Context.** Filament DB 1.48.0 moved the 5-byte hex roll ID (`instanceId`) from the
filament onto each **spool**, and 1.49.0 made it **user-editable**. Format (verified in
FDB `src/models/Filament.ts`): the auto-generated default is
`crypto.randomBytes(5).toString("hex")` → **10 lowercase hex chars** ("Prusament
format"); a user-set value is validated as `[A-Za-z0-9._-]{1,128}` and must be unique
(partial-unique index, scoped to non-deleted documents). It lives on both the filament
and the spool subdoc during the transition; the spool one is canonical going forward.

**Considered.** Optionally (Settings toggle) mirror the Spoolman spool ID into the FDB
spool's `instanceId` using a user-chosen numeric prefix to stay 10 chars and globally
unique — e.g. prefix `1` + zero-padded id → `1000000042`. This would give a single
human-readable roll number derivable in both systems.

**Decision: declined the write path. The bridge does NOT write `instanceId`. The
Spoolman spool ID stays in the FDB spool `label` field (`FILAMENTDB_SPOOLMAN_ID_FIELD`,
default `label`), backed by the `SpoolMapping` table.**

**Rationale.**
- `instanceId` is FDB's **physical-tag match key** — desktop and mobile scanners resolve
  QR/NFC against it (1.48), and 1.49 made it editable precisely so users can store their
  *real* Prusament roll IDs / NFC tag IDs. Overwriting it with a synthetic cross-ref
  number would break scan-by-tag, stomp user-entered values, and strand already-printed
  labels / written tags (FDB does not re-write tags when the ID changes).
- Linkage is **already solved**: the Spoolman spool ID is stored in the FDB spool `label`
  field *and* in the bridge's SQLite `SpoolMapping`. Encoding it into `instanceId` is a
  redundant third copy.
- It's **one-directional decoration**: Spoolman cannot read FDB's `instanceId`, so it adds
  no new sync capability on either side.
- The proposed `1000000xxx` encoding only holds 3 digits of ID (≤999 spools) before
  overflow; a safe scheme would need `prefix + 9-digit zero-pad`, reinforcing that this is
  fiddly for little gain.

**Future-looking (not implemented).** If `instanceId` is interesting to the bridge at all,
the valuable direction is the opposite — **read** it (and the new `Filament.openprinttagSnapshot`
field added in 1.47.2) so the bridge can *surface* the user's real roll ID / OpenPrintTag
identity (e.g. mirror into a Spoolman extra field), adding information rather than
destroying it. Needs the `openprinttagSnapshot` schema from `/api-docs` before any work.

**Upstream review context.** Reviewed FDB releases 1.43.0 → 1.49.0 (latest): no breaking
changes for the bridge. We address spools by the stable subdoc `_id` and send minimal PUT
payloads (`{label}` / `{totalWeight}`), so the per-spool/editable `instanceId` is never
clobbered; `instanceId` is also in `_strip_computed` for the filament path. 1.44.0
(hide out-of-stock) is a UI-only filter — `GET /api/filaments` still returns all records.
`MIN_FDB` stays `1.33.0`. README "latest tested" should be bumped 1.42.0 → 1.49.0.

## 2026-06-13 — Debug: added POST /api/debug/clear-spoolman-opentag-ids

Added a fourth standalone debug endpoint that blanks the three OpenPrintTag identity
extras (`openprinttag_slug` / `openprinttag_uuid` / `openprinttag_ignore`) on every
Spoolman **filament** that has any of them set. This is the filament-level analog of
the existing `clear-spoolman-fdb-refs` (spool-level cross-ref clearer).

**What it does:** Iterates `get_filaments()`; for each filament with at least one of the
three extras set to a non-blank value, calls `update_filament(id, {"extra": {k: blank}})`
for only those keys. Per-filament write failures increment `failed` without aborting the
batch. If the initial `get_filaments()` call fails, returns 502.

**Spoolman-only.** No bridge DB writes, no Filament DB writes, no record deletion.
Not folded into `full-reset` — it's a standalone testing convenience.

**UI:** Settings Danger Zone now has four buttons in debug mode: "Clear Spoolman
cross-refs (Spoolman only)", "Clear Spoolman OpenPrintTag ids (Spoolman only)", "Reset
bridge DB (bridge only)", and "Full reset (bridge DB + Spoolman links)".

**Rationale:** During OpenTag matcher re-testing, all three identity extras need to be
blanked on every Spoolman filament so the matcher can be re-run from a clean state.
Without this tool, users had to blank each filament manually through the Spoolman UI.

## 2026-06-13 — Remove `opentag_color_keywords` user-override feature

The `opentag_color_keywords` setting (env var `OPENTAG_COLOR_KEYWORDS`, BridgeConfig seed,
Settings "Color word mappings" section) has been **removed** entirely.

**Why.** The v2 matcher policy (locked 2026-06-11) restricts `COLOR_SYNONYMS` to true
linguistic equivalences only — marketing collapses like `galaxy=black`, `cool=grey`,
`jet=black` degrade multicolor matching by collapsing semantically distinct tokens.
The new-install seed was seeding exactly those invalid collapses, and the Settings UI
was actively teaching users to add more. The built-in `DEFAULT_COLOR_KEYWORDS` /
`COLOR_SYNONYMS` map already covers the only legitimate synonyms (`gray→grey`,
`violet→purple`, `magenta→pink`, `transparent→clear`, `navy→blue`), so the override
adds only downside.

**What was removed.** `parse_color_keywords_config` function; `opentag_color_keywords`
field in `Settings` (config.py), `BridgeConfig._DEFAULTS`, `ConfigResponse`,
`ConfigUpdateRequest`, `ConfigUpdateRequest` (frontend types.ts); `colorKeywords` state,
dirty-check clause, `vcolorkw` derived value, save-payload field, and the "Color word
mappings" UI section in Settings.tsx. All docs (CLAUDE.md, configuration.md,
opentag-matching.md) updated in the same commit. No DB migration: existing stored values
simply become dead (never read).

## 2026-06-13 — Reconcile: master/container parents are intentional; shown as variant annotation, never as missing

**Behavior.** The read-only Reconcile report (`GET /api/reconcile`) now excludes
master/container-parent FDB filaments from the `only_in_filamentdb` bucket and from the
summary count.  These filaments have no Spoolman counterpart by design — the bridge creates
them as synthetic hierarchy containers — so surfacing them as "missing" items is noise, not
signal.

**Detection.** The `_is_master` predicate in `reconcile.py` mirrors `_is_master_fdb` from
`wizard.py` verbatim: (1) `FilamentMapping.is_synthetic_parent == True` for bridge-created
containers, (2) `FDBFilament.hasVariants == True` as a fallback for externally-created
parents, (3) name ends with `f" {marker}"` where `marker = _resolve_container_parent_marker(db)`.

**Variant annotation.** Matched rows whose FDB filament carries a non-null `parentId` that
resolves in the fetched filament set now carry `variant_of: str` — the parent's name.  The
frontend renders this as a small muted "Variant of {name}" subtitle under the FDB filament
name in the Matched table.  The parent itself never appears as its own row.

**Tests added.** Five new tests in `test_reconcile.py`: masters excluded via `hasVariants`,
masters excluded via `is_synthetic_parent`, summary count equals filtered list length,
`variant_of` populated for a variant child, `variant_of` is None for a top-level filament.

## 2026-06-13 — OpenTag apply: re-point this filament to exact-named canonical vendor

**Behavior.** The OpenTag cleanup apply path (`POST /api/openprinttag/apply`) standardizes
the manufacturer name by re-pointing only the affected filament to a vendor with OpenTag's
exact canonical brand spelling.  The existing Spoolman vendor record is never renamed; no
other filaments are touched.

**Vendor row surfacing.** `_build_field_rows` now suppresses the vendor row only when the
raw SM vendor name and OpenTag brand string are identical after `.strip()` (case-sensitive
equality).  Previously the comparison used `normalize_vendor` (case-folding + hyphens →
spaces), which silently swallowed case-only differences like "Elegoo" vs "ELEGOO".

**Vendor find-or-create.** `_ensure_vendor` in the apply loop now indexes existing vendors
by exact trimmed name (`vendor_id_by_name: dict[str, int]`) instead of the normalized form.
When the decision value "ELEGOO" does not appear verbatim in the index (even if "Elegoo" id=5
exists), a new vendor "ELEGOO" is created and the filament's `vendor_id` is updated.

**Accepted trade-off.** A case-only difference intentionally creates a near-duplicate vendor
in Spoolman (e.g. "ELEGOO" alongside "Elegoo").  The user was presented this choice and
accepted it.  Only the filament being applied is re-pointed; the old vendor and all other
filaments remain untouched.

**Tests added/changed.** `test_build_field_rows_vendor_row_absent_when_normalized_match`
renamed and inverted to `test_build_field_rows_vendor_row_present_when_only_case_differs`
(asserts row IS present for "PRUSAMENT" vs "Prusament").  New integration test
`test_apply_vendor_case_only_diff_creates_canonical_and_repoints` confirms `create_vendor`
is called with the exact OpenTag spelling and the PATCH carries the new vendor_id, not the
existing near-match id.

## 2026-06-13 — Reconcile page: read-only, on-demand, no fuzzy suggestions

**Feature.** New `/reconcile` page and `GET /api/reconcile` endpoint that compares
Spoolman and Filament DB at the filament level and shows four buckets: matched pairs,
only-in-Spoolman, only-in-Filament-DB, and ambiguous.

**Read-only, write-nothing.** The endpoint fetches from both upstreams but writes
nothing — no mapping rows, no cross-ref fields, no upstream records. Acting on a
missing item remains the Bulk Import Wizard's job. This is enforced by the router
containing zero mutating calls.

**On-demand fetch, not auto-polled.** A full read of both upstream filament + spool
lists is too heavy to poll automatically. The page exposes a visible Refresh button;
`useApi` fires once on mount. `usePoll` was explicitly rejected.

**No fuzzy / near-miss suggestions.** The prompt scope-cut this explicitly. Only the
matcher's existing cross-ref (xref pre-pass) + exact normalized vendor+name+color key
matching is used. Missing filaments are listed plainly with no "possible match" hints.

**`linked` flag semantics.** A matched pair is `linked=True` iff the SM filament's id
appeared in `xref_by_sm_filament` (cross-ref via Spoolman spool `filamentdb_id` extra
field) AND the stored FDB id equals the paired FDB filament's id. A pair matched only
by the exact-key pass is `linked=False`.

**Import pattern.** `_sm_ref` and `_fdb_ref` are imported directly from
`app.api.wizard` rather than being lifted to a shared module, to avoid drift. Both
helpers are pure functions with no side effects.

## 2026-06-13 — find-or-attach on 409 in `_execute_spoolman_to_fdb` (idempotent conflict Add)

**Root cause (proven from live logs).** In `generic_container` mode, conflict Add (via
`POST /api/conflicts/{id}/import`) calls `_execute_spoolman_to_fdb` which tries to create
a synthetic container + variant in FDB. Once those records exist (from a prior Add or wizard
import), FDB returns 409. The old code recorded a failure and skipped the cluster, so
nothing attached and the conflict never resolved — a doom loop of re-Add → 2× 409 → 2 failed
→ conflict stays open.

**Decision.** Make the create path idempotent via find-or-attach on 409:
1. **Container 409**: look up the existing FDB filament by its intended display name
   (case-insensitive, prefer `parentId == null`). If found, use it as the container and
   ensure a `FilamentMapping(is_synthetic_parent=True)` row exists (no duplicate). If no
   match, record a single failure (true collision).
2. **Variant/standalone 409**: look up by the intended variant name (prefer
   `parentId == container_id`). If found, link and patch `parentId` if needed. If no match,
   record a single failure.
3. Helper `_find_fdb_by_name()` added (wizard.py) for case-insensitive name lookup with
   tie-break rules: prefer-parent-id beats prefer-null-parent beats first-match.

**Invariants.**
- Re-running Add for an already-imported record → zero failures, conflict resolves.
- Adding a sibling variant under an existing master → zero failures, conflict resolves.
- A genuinely new record (no name match in FDB) still creates fresh.
- A true name collision with no findable existing match still records a failure.
- Bulk-wizard execute shares the same code path — its behavior is unchanged for the
  success case; find-or-attach only fires on 409.

**Tests.** Four new tests in `test_conflicts_import.py`: re-run Add doom-loop scenario;
sibling variant attach; fresh create regression; container 409 no-match still fails.

## 2026-06-13 — FilamentMapping.identity column + filament-only rows in Synced Records

**Why.** Spool-less imported filaments (Spoolman filament IDs 10, 14, 115, 120) had a
`FilamentMapping` and existed in Filament DB but no `SpoolMapping` → invisible in Synced
Records ("shows up in FDB, not in bridge"). The root cause: `build_mapping_rows` was
spool-keyed (one row per `SpoolMapping`). The previous attempt failed because filament
snapshots store only an `_mp_*` comparison projection — no name/vendor/color — so
filament-only rows rendered blank.

**Decisions (locked 2026-06-13).**

- **Display data:** persist a JSON identity blob `{vendor, name, color_hex, material}` on a
  new nullable `FilamentMapping.identity` column (add_column, nullable, no data migration).
  Written at `FilamentMapping` creation time by both `_execute_spoolman_to_fdb` and
  `_execute_fdb_to_spoolman` in `wizard.py`, using the existing `_sm_filament_identity` /
  `_fdb_filament_identity` helpers from `engine.py`. Synthetic container parents leave
  `identity=NULL`. `build_mapping_rows` degrades gracefully on NULL (name/vendor/color=None).

- **Opportunistic backfill:** when an existing `FilamentMapping.identity` is None and the
  SM/FDB filament is in hand during a sync cycle, the engine sets it so legacy rows self-heal
  next cycle without a data migration.

- **Row discriminator:** `kind: Literal["spool","filament"] = "spool"` on `MappingRow`.
  Filament-only rows are `kind="filament"` with null spool ids/weights. FE hides
  relink/unlink for `kind==="filament"` rows; DeepLinks already null-handles spool id.

- **Shared status helper:** `core/filament_status.py::filament_mapping_status()` extracted
  from the inline logic in `api/sync.py` and used by BOTH `sync.py` and `mappings.py` so
  the filament-only row status (in_sync/pending/conflict) never drifts from the dashboard.

- **Conflict Add "link" UX (P2):** new endpoint `GET /conflicts/{id}/filament-suggestions`
  runs `match_filaments` (exact-key, score=1.0) then a fuzzy fallback built only from
  existing normalizers (`normalize_vendor`, `strip_color_and_words`, `normalize_color`; top 8,
  all score < 1.0). FE replaces the bare 24-char text field with a dropdown of suggestions
  plus a manual 24-hex override (takes precedence when filled).

- **single_record_import:** confirmed a thin wrapper over `_execute_spoolman_to_fdb` — no
  drift; identity is set via the shared wizard execute path. Explicit-master parenting
  (`master_filamentdb_id`) is single-record-only (no auto-cluster) — documented in
  `docs/conflicts.md`.

## 2026-06-11 — OpenTag matcher v2.1: soften hard gates + capture fill-composite descriptors

**Why.** v2's name-driven scoring was correct, but two pre-v2 hard gates still ran
*before* scoring and discarded name-perfect matches:

1. **Color-profile gate** (`profiles_compatible`) classified "Temperature Color Change
   Purple to Red" as `single` because `secondaryColors` had only one entry and no
   arrangement tag. The SM filament was multicolor, so `profiles_compatible("multi_unknown",
   "single")` returned `False` and the entry was dropped before scoring. The gate trusted
   incomplete OPT hex data over the name.

2. **Polymer-family gate** excluded PHA-typed OPT entries for PLA SM filaments. ColorFabb
   composites (woodfill, copperfill, bronzefill, …) are inconsistently typed as `PHA` in
   OpenPrintTag even though the physical product is a PLA/PHA blend. The gate was correct
   in principle but the dataset was inconsistent.

3. **No descriptor for *fill composites.** `decompose_name("PLA Woodfill")` produced no
   modifiers — "woodfill" was residual noise. Woodfill and steelfill were indistinguishable
   by the scorer; steelfill (PLA-typed) won on family gate alone.

**Decisions (locked 2026-06-11 — confirmed in plan before implementation).**

- **PLA-biopolymer bucket (user-confirmed):**
  `PLA_BIOPOLYMER_BUCKET = {"pla","pha","pla/pha","lw-pla","htpla","rpla"}`.
  All pairs inside the bucket are gate-compatible via `families_gate_compatible()`.
  All other families remain strictly separate (ABS, ASA, PETG, PC, PA/nylon, TPU, etc.).
  Do NOT collapse LW-PLA/HTPLA/rPLA inside `material_family` — equivalence lives only in
  the gate, so the 0.15 material score still rewards exact-family matches.

- **Gates stay GATES (not penalties).** Widening the family gate by the bucket and making
  the color-profile gate name-aware keeps the candidate-set bounding and the
  `multicolor_mismatch` UX without requiring score re-weighting.

- **Color-profile gate → `color_profile_compatible_soft`** (v2.1):
  - Strict path when BOTH sides have explicit arrangement tags AND OPT hex data is complete
    (`hex_count >= 2`): keep `profiles_compatible` semantics.
  - Soft path otherwise: use `opt_color_arity = max(hex_count, name_color_count)` to
    determine OPT arity. For a multicolor SM side (arity >= 2), keep OPT candidates whose
    arity is also >= 2. "Purple to Red" (name → 2 colors → arity 2) now reaches scoring.

- **`ngram_index` / `effective_synonyms` built once** in `opentag_matches` and passed to
  both the gate (`color_profile_compatible_soft`) and `find_best_match`. Avoids O(candidates)
  redundant rebuilds.

- **`COMPOSITE_DESCRIPTOR_SEED` unioned unconditionally into the modifier lexicon:**
  woodfill, steelfill, stonefill, copperfill, bronzefill, corkfill, glowfill, metalfill,
  marblefill, brassfill, bamboofill, granitfill. Plus a `len>=6 and endswith("fill")`
  fallback in `decompose_name`'s unigram branch for novel tokens not in the seed.
  Rides the existing modifier Jaccard component (weight 0.15) — no score re-weight.
  Effect: "PLA Woodfill" → modifier `{"woodfill"}`; woodfill OPT → `{"woodfill"}` →
  Jaccard 1.0 vs steelfill → Jaccard 0.0.

- **No score re-weight.** Weight vector unchanged:
  `material×0.15 + brand×0.15 + color-multiset×0.40 + modifier-jaccard×0.15 + finish±0.10
  + hex×0.05 + string≤0.05`.
  AMOLEN "Silk Shiny Gradient Silver & Shiny Blue" #1 confirmed (regression preserved).

- **`LEXICON_VERSION` bumped 2 → 3** (COMPOSITE_DESCRIPTOR_SEED changes mined output →
  warm caches self-heal by re-mining from cached materials without network fetch).

**Proof.** Golden test `test_cc3d_temp_change_purple_red_ranks_first`: purple-to-red #1,
green-to-yellow strictly below. `test_colorfabb_woodfill_ranks_first`: woodfill #1 over
steelfill and copperfill. `test_petg_candidate_gate_dropped_for_asa_filament`: ASA vs PETG
separation preserved. Full truth table in `test_families_gate_compatible_truth_table`.

## 2026-06-11 — OpenTag matcher v2: structured token decomposition + mined lexicons

**Why.** The v1 scorer collapsed color names to a single base color via
`DEFAULT_COLOR_KEYWORDS` (`"silver" → "grey"`, `"galaxy" → "black"`, etc.) and scored
them with string similarity. Two failure modes:

1. **Multicolor order collapse.** "Silk Shiny Gradient Silver & Blue" and "Dual Color
   Blue & Fuchsia" both reduced to `{grey, blue}` after the silver→grey collapse — the
   correct target was indistinguishable from the wrong one.
2. **Color-word pollution.** Genuine color names like turquoise, fuchsia, emerald appeared
   in too few brands to reach the mining threshold and leaked into the modifier vocabulary.

**v2 design (locked 2026-06-11).**

- **`decompose_name`** decomposes filament names into `ParsedName(material_family,
  finish_ids, modifiers, colors: Counter)`. Both the Spoolman and OpenTag names are
  decomposed identically before comparison — no side-specific heuristics.
- **Color multiset score (weight 0.40).** Order-independent, count-aware:
  `matched / (matched + extra_a + extra_b)`. Neutral 0.5 when either side has no color
  tokens. This correctly handles "Silver & Blue" (two distinct colors) without collapsing.
- **Modifier Jaccard (weight 0.15).** Captures silk/matte/gradient/dual agreement without
  requiring exact name matches.
- **Material / vendor / finish / hex weights** updated to 0.15 / 0.15 / ±0.10 / 0.05;
  full-string tiebreaker adds 0–0.05.
- **`COLOR_SYNONYMS` = synonyms only.** `DEFAULT_COLOR_KEYWORDS` is now an alias for a
  short map of genuine equivalences (`gray→grey`, `violet→purple`, `magenta→pink`,
  `transparent→clear`, `navy→blue`). All marketing collapses dropped.
  The `opentag_color_keywords` env/setting feeds additional synonyms, not primary colors.
- **`BASE_COLORS` seed** prevents color-word leak into the modifier vocabulary for words
  that appear in too few brands to reach the mining threshold.
- **Stop-list** excludes material codes (`gfN`, `rfid`, `esd`, `htpla`, `rpla`, `rpetg`)
  from modifier mining.
- **`LEXICON_VERSION = 2`**: cache self-healing on version bump (re-mine from cached
  materials without network fetch).
- **Manual search endpoint** (`GET /api/openprinttag/search`) runs the same scorer with a
  synthetic filament built from `brand + material + q`. No duplicate scoring path.
- **UI search box** per FilamentCard; injected result is prepended to
  `candidates[]` (deduplicated by slug/uuid) and becomes active immediately.

**AMOLEN regression preserved.** "Silk Shiny Gradient Silver & Shiny Blue" ranks #1
over "Dual Color Blue & Fuchsia" with ≥ 0.10 gap in `test_opentag_golden.py`.

## 2026-06-11 — New-record handling: two-tier policy model (new_filament_policy / new_spool_policy)

**Why.** The ongoing engine had no policy for new filaments: it never created filaments
(only the wizard did), so a brand-new Spoolman filament sat unmapped forever and every
spool under it flooded the conflict queue with a dismissible `new_spool` notice — no
action was possible beyond "dismiss". The half-built state meant auto-import was missing
entirely and the conflict queue had no actionable "Add" path for new records.

**Two-tier design.** A filament is a container; sync flows top-down (parent → filament →
spool). A spool can only be created once its filament is mapped. Two independent policy
keys control each tier:

- `new_filament_policy`: `manual_review` (default) | `auto_import` — governs whether a
  detected unmapped filament is queued for review or created automatically.
- `new_spool_policy`: `manual_review` (default) | `auto_import` — governs whether a
  detected unmapped spool on an already-mapped filament is queued or created automatically.

Both default to `manual_review` for fresh installs (via `seed_defaults`) and for existing
installs (via `_migrate_sync_config` in `main.py`). The `manual_review` default means the
live behavior is unchanged for existing users: new records surface in the conflict queue
for human review instead of being silently auto-created.

**Variant/unset interaction (LOCKED Q2).** When `variant_parent_mode == "unset"` (the
must-choose sentinel) and the filament looks like it belongs to a variant cluster
(`sm_variant_cluster_key` returns a key), the engine HOLDS the filament for manual review
even if `new_filament_policy == "auto_import"`. Auto-grouping a variant filament without a
chosen parent mode would produce an incorrect hierarchy that's hard to undo. The choice:
fall back to `manual_review` for that filament, queue a `new_filament` conflict, and wait
for the user to configure variant_parent_mode first.

**`new_filament` conflict type.** A new conflict type (`entity_type="filament"`,
`field_name="new_filament"`) is queued when an unmapped filament is held for review. It
carries `spoolman_id` (the SM filament id) or `fdb_filament_id` in `spoolman_value` (JSON).
These are actionable — the `POST /api/conflicts/{id}/import` endpoint processes them.

**Scoped single-record import endpoint.** `POST /api/conflicts/{id}/import` accepts a
`ConflictImportRequest` (`dry_run`, `filament_action`, `filamentdb_id`, `tare_override`,
`master_filamentdb_id`). It validates the conflict is open and of type `new_filament` or
`new_spool`, resolves the SM filament id, calls `import_single_sm_filament()` (the shared
helper), and on success marks the conflict resolved with `resolution="imported"`, also
auto-resolving any paired `new_filament` conflict for the same SM filament.

**Shared single-record import helper.** `app/core/single_record_import.py` wraps
`_execute_spoolman_to_fdb` / `_execute_fdb_to_spoolman` scoped to a single-element
filament list. Called by both the engine auto-import paths and the endpoint. This ensures
one create-path that can never drift apart. The helper defers its wizard imports to the
function body to avoid the engine→wizard→engine circular import chain.

**Anti-ping-pong invariant.** After any auto-create in the engine, both sides' snapshots
are refreshed to the agreed post-create state. This is the FR-11 invariant — without it,
the newly created record looks like a fresh change next cycle and is re-queued. Proven by
`test_auto_import_no_pingpong` in `tests/test_engine.py`.

## 2026-06-11 — OpenTag "ignore future updates" flag stored as Spoolman extra field

**Why.** The "updates available" banner needs per-filament suppression that persists across
bridge restarts and survives cache-file deletion. Two options considered:

1. **Spoolman extra field** (`openprinttag_ignore`): the flag travels with the record, is
   visible in Spoolman's own UI, and is checkable on every `GET /api/openprinttag/matches`
   run without any bridge-DB JOIN. Downside: requires registering one more extra field.
2. **Bridge-local SQLite table**: no external dependency, but the flag is detached from the
   filament record and lost on a bridge DB reset.

**Decision: Spoolman extra field.** The flag is stored as `openprinttag_ignore` (text,
`"1"` = ignored, `""` = not ignored) on the Spoolman filament entity. It is registered in
`ensure_extra_fields()` alongside the existing OpenTag fields and keyed by the env var
`SPOOLMAN_FIELD_OPENPRINTTAG_IGNORE` (default `openprinttag_ignore`). The matches endpoint
reads it per-filament, sets `ignored_updates: true` on the match row, clears `has_update`,
and excludes the filament from `updates_count`. Un-ignoring is a single PATCH to Spoolman
via `POST /api/openprinttag/ignore/{id}?ignored=false`.

## 2026-06-11 — Filament-level dashboard counts + wizard execute per-type breakdown

**Why.** The bridge was entirely spool-centric: the dashboard counts reflected
SpoolMapping state only. A filament with no active spools (or a variant/container
filament) could be created and linked but appear as "0" everywhere in the counts,
giving users no signal about the filament-pair sync state.

**Dashboard: `filament_counts`.** `GET /api/sync/status` now returns a separate
`filament_counts: {in_sync, pending, conflict, total}` map alongside the existing
spool `counts`. Computation (in `api/sync.py`):

- Iterates all `FilamentMapping` rows where `spoolman_filament_id IS NOT NULL`
  (real cross-system pairs). Synthetic NULL-`spoolman_filament_id` container
  parents (generic_container mode) are excluded — they have no Spoolman counterpart.
- **conflict** — an open `Conflict` row references the `filamentdb_id`.
- **in_sync** — both SM and FDB filament `Snapshot` rows exist (mapping has been
  baselined).
- **pending** — one or both snapshots are missing.

The existing spool `counts` dict shape is unchanged — frontend code and tests that
read `counts` are unaffected.

**Execute: per-type breakdown.** `WizardExecuteResponse` gained eight new fields
(`created_filaments`, `created_spools`, etc.) computed from `res.records` by type
+ action at the end of `wizard_execute`. The flat `created`/`updated`/`skipped`/`failed`
totals are kept unchanged — only additive fields added.

**UI.** `Dashboard.tsx` renders a "Spools" section (existing four-card grid, now
labelled) followed by a "Filaments" section (in_sync / pending / conflict / total).
`Step6Execute.tsx` shows a "Nf / Ns" breakdown line under each non-zero counter card.

**No decision is controversial here** — this is purely additive visibility.

## 2026-06-11 — Archived Spoolman spools import as retired FDB spools (not silently dropped)

**Root cause.** The wizard's `sm_spools_by_filament` builder (planner.py:316) filtered
out archived Spoolman spools *before* the `never_import_empties` gate. A user with SM
filament 63 ("Light Purple PLA") and only one spool (#65, archived, `used_weight 1047.98 >
initial_weight 1000.0` → remaining = −47.98) saw the filament created in FDB but zero
spool mappings — so it never appeared in Synced Records.

**Decision O1 (locked): archived ⇒ retired.** Archived SM spools are no longer
categorically excluded from import. They flow through the same `never_import_empties` gate
as active spools:
- `never_import_empties = false` (default): import all spools, including empty/archived ones.
  Archived spools become **retired** FDB spools (`retired: true` on the spool payload and
  the seed snapshot). **Only the spool is retired — the filament is always a normal,
  non-retired filament** (in Spoolman the archived flag is spool-level; the filament
  remains live).
- `never_import_empties = true`: skip spools whose `remaining_weight ≤ 0.0`, whether active
  or archived. An archived spool with positive remaining weight still imports as retired.

**Decision O2 (accepted): no un-archive flip-back.** The ongoing engine does NOT flip a
retired FDB spool back to active when the SM spool is un-archived later. `archived`/`retired`
is set once at import; subsequent state changes are not a synced field. (Engine guardrails:
the mapped-pair archived branch at engine.py:2380 skips retired/archived pairs; new-spool
detection uses active-only lists; differ has no `retired` field.)

**Decision O3 (empty gate): `remaining_weight ≤ 0.0`.** The empty gate now uses `<= 0.0`
everywhere (was `== 0.0` in some sites). The proven real-world case has
`remaining_weight = -47.98` (used 1047.98 g from a 1000 g spool), which `== 0.0` would
miss. Changed at: planner.py:461, wizard.py:613 (`spool_ids_per_filament`), and the
`_compute_empty_active` bucket.

**Transparency.** The wizard Preview step's "Empty/archived spools" bucket now includes all
spools with `remaining ≤ 0` or `archived = True`. Each archived entry displays an
"archived → imports as retired" badge. The execute sync-log record for a retired spool
create carries `detail = "imported as retired (archived in Spoolman, spool #N)"`.

**Sites changed** (from the plan's table): A (planner.py:316 — the bug), B (planner.py:461
empty gate + retired flag), D (wizard.py:613 spool_ids_per_filament), F (wizard.py:291 xref
map), G (wizard.py:397 wizard_weights), H (wizard.py:1129 generic_container parent scan),
I (wizard.py:1880 _compute_empty_active). Sites C/E/J/K/L kept active-only (heuristics and
engine guardrails — no change per plan).

## 2026-06-11 — Startup state dump retries the upstream fetch (~2 min) instead of one-shot

`write_startup_dump` initially fetched once, ~2 s after boot — which always lost the race
when the compose stack starts together (`depends_on` orders container start, not
readiness), so the dump silently never appeared. It now retries the data fetch
(12 × 10 s) before giving up, and fetches versions only after the data succeeds (forcing a
fresh FDB version read past `get_version()`'s first-call cache, which may have cached a
boot-time failure). Failure after the budget is still swallowed — the dump never blocks
startup.

## 2026-06-11 — OpenTag dataset: direct GitHub tarball fetch (no FDB proxy)

**Context.** The bridge originally fetched the OpenTag material list via Filament DB's
`GET /api/openprinttag` JSON feed and then made a second request to the raw GitHub tarball
to recover secondary colors (which FDB's denormalized feed left empty). This created two
sources of truth, required a live FDB connection for the cache step, and meant the bridge
broke if FDB was temporarily unreachable even when GitHub was fine.

**Decision.** Fetch the OpenPrintTag tarball directly from
`https://api.github.com/repos/OpenPrintTag/openprinttag-database/tarball/main` in a single
download. Brand names, material properties, primary colors, and secondary colors are all
parsed in one two-pass loop (`_parse_tarball` in `core/opentag_cache.py`):

1. Pass 1 — index `data/brands/<slug>.yaml` → `{slug: name}`.
2. Pass 2 — parse every `data/materials/**/*.yaml`; skip `class != FFF`; emit one
   `OPTMaterial` dict per file, with `brandName` resolved from the index, and
   `secondaryColors` populated directly from `secondary_colors[].color_rgba`.

The emitted dict shape is **backward-compatible** with the old FDB feed shape so all
downstream consumers (`core/opentag_match.py`, the apply endpoint, the sync engine's
`_sync_opentag_identity` pass) continue unchanged.

**Consequences.**
- `core/opentag_secondary.py` is deleted (its `_rgba_to_hex` helper was folded into
  `opentag_cache.py`; its `fetch_secondary_colors` function is no longer needed).
- `FilamentDBClient.get_openprinttag()` is deleted (the FDB API proxy is no longer used).
- `load_opentag_dataset` no longer takes an `fdb_client` argument.
- Error handling simplified: only GitHub connectivity errors can occur (timeout→504,
  non-2xx→502 `opentag_fetch_failed`, RequestError→502 `opentag_fetch_failed`).
  The `opentag_unavailable` error code (previously used for FDB 404 / version-gate) is gone.
- `_fetch_from_tarball(http=None)` is the injectable seam for tests (the conftest autouse
  fixture stubs it out; tests that need real parse behavior use the module-level
  `_real_fetch_from_tarball` alias captured before the patch fires).

## 2026-06-11 — Durable `changes.log` file (`CHANGES_LOG_ENABLED` / `CHANGES_LOG_PATH`)

**Why a file sink vs. the existing SQLite Sync Log.** The Sync Log page in the
UI queries `SyncLog` rows, which live in the bridge's SQLite database at
`/data/bridge.db`.  After a bad release or accidental config change, users want
an independent record they can inspect with a text editor (`tail -f changes.log`,
`grep spoolman changes.log`) — without needing the UI, the DB, or the bridge
running at all.  The file is human-readable and survives schema migrations.

**Hook point: `_log()` in `core/engine.py`.** Every upstream mutation (create /
update / delete / usage) that the engine, wizard execute, and `conflict_apply`
make goes through `_log()`.  Adding a `record_change()` call at the bottom of
`_log()` means all write sites are covered for free — including the
`_mp_*` scalar pass, cost, temps, multicolor, finish tags, new-spool creates,
and opentag identity merge.  The OpenTag apply endpoint (`api/opentag.py`) does
not use `_log()`, so it gets direct `_record_change()` calls after each
successful upstream write.

**Actions recorded.** Only `create`, `update`, `delete`, and `usage`.  `skip` /
`info` / `conflict` / `error` / dry-run entries are filtered out — they do not
represent real upstream writes.

**Format (one line per change):**
```
2026-06-10T21:45:03Z  UPDATE  filamentdb  spool sp42  weight: 916.9 → 905.1   (cycle abc123)
2026-06-10T21:45:04Z  CREATE  filamentdb  filament 665f…
2026-06-10T21:45:05Z  UPDATE  spoolman  filament #7  opentag_apply: ["material","color_hex"]   (opentag-apply)
```

**Rotation.** Size-based: roll `changes.log → .1 → .2 → .3` past 10 MiB; keep
3 backups.  Configurable via module constants (`_ROTATION_BYTES`, `_ROTATION_COUNT`).

**Robustness.** All file I/O in `record_change()` is wrapped in `try/except`;
errors are logged at WARNING level and swallowed — a disk-full or permissions
failure never breaks sync.

**Relationship to `DEBUG_STARTUP_DUMP`.** The startup dump (`core/state_dump.py`,
`DEBUG_STARTUP_DUMP=true`) captures a point-in-time snapshot of both systems at
boot.  `changes.log` records what the bridge writes afterward.  Together they
give a full before/after picture useful during post-incident review.

**Module:** `backend/app/core/change_log.py`.  Env vars: `CHANGES_LOG_ENABLED`
(default `true`) and `CHANGES_LOG_PATH` (default `{DATA_DIR}/changes.log`).

## 2026-06-11 — Debug startup state dump (`DEBUG_STARTUP_DUMP`)

**Why env-level, not runtime BridgeConfig.** The dump runs during the lifespan
startup sequence (before the scheduler starts), so gating on a SQLite-stored
runtime flag would require an extra DB round-trip inside the async client
context — and would add latency before `ensure_extra_fields`. Using an
env-level bool (`DEBUG_STARTUP_DUMP`, default `false`) keeps the gate at
configuration time, avoids that round-trip, and makes the boot-time behavior
visible in the process environment rather than buried in the database.

**Format — human-readable diff-friendly text.** Four sections
(SPOOLMAN FILAMENTS / SPOOLMAN SPOOLS / FILAMENT DB FILAMENTS / FILAMENT DB
SPOOLS), one record per line, stable field order.  Sorted by id within each
section (numeric for Spoolman, lexicographic ObjectId for Filament DB).
Built entirely in memory before writing (`Path.write_text`) — no partial
writes possible.

**Extras policy.** Only bridge-controlled extra fields (the six configured key
names) are printed on Spoolman records.  Decoded via `decode_extra_value`.
Empty string / `None` / empty list values are omitted to keep lines compact.
Values longer than 20–24 characters are truncated with `…`.

**Retention: newest 10 dumps.** `prune_dumps(dir, keep=10)` is called after
each write.  It globs `startup-state-*.txt`, sorts lexicographically (ISO basic
timestamp prefix → chronological), and unlinks everything beyond the 10 most
recent.  Non-matching files in the directory are not touched.

**Robustness.** `write_startup_dump` is wrapped in a broad `try/except`; any
fetch or write error is logged as a warning and swallowed.  The task is
scheduled via `asyncio.create_task` and a reference is held so it can be
cleanly cancelled on shutdown if still running.

**Location.** Module is `backend/app/core/state_dump.py`.  Files land in
`{DATA_DIR}/state-dumps/startup-state-<UTC ISO basic ts>.txt`.

## 2026-06-11 — HelpTip component for in-place UI help

**Component design.** `HelpTip` (`frontend/src/components/HelpTip.tsx`) renders a small circled `?` button (14 px, tabIndex=0) that shows a plain-text tooltip on hover, keyboard focus, and tap/click. Tooltip appears above the icon (`bottom-full`, `z-50`), max width 18 rem, dark-mode aware (`bg-gray-800`/`bg-gray-700`). Escape or blur closes; no layout shift (absolutely positioned). Optional `learnMoreHref` renders a "Learn more ↗" link that navigates in-app (`/docs/<slug>`) or opens externally (`target=_blank`).

**Copy placement.** All tooltip text lives at each call site — no central registry. This keeps the text visible in context and avoids an indirection layer that would complicate future edits. Short copy (1–3 sentences) is the rule; surfaces with good existing sub-text were skipped per the inventory.

**Surfaces covered.** Settings (11 tips), Dashboard (6 tips on counts cards + Sync now + Dry run + Next sync), Synced Records (SM weight header, FDB weight header, Hide empty spools, Snapshot values label), Conflicts (Master divergence chip, Bulk resolve), Wizard Step 2 (direction cards), Step 3 (Status/% column header, Master/Parent pill), Variances (Empty-reel tare, master radio, suggest-standalone chip, attach-to-existing buttons), Preview (4 flag section cards), Execute (tare overrides label), OpenTag Cleanup (confidence badge, keep mine, ignore match, Hide already-tagged).

## 2026-06-11 — In-app docs viewer at /docs/:slug

**Serving approach.** Markdown files in the repo `docs/` directory are shipped
inside the Docker image as static files under `static/docs-md/` (a single
`COPY docs/ ./static/docs-md/` in the Dockerfile Stage 2, placed with the
other static-file copies so layer caching stays optimal). The existing SPA
fallback in `backend/app/main.py` already serves arbitrary files under
`static/`, so `GET /docs-md/variant-parent-mode.md` works with no backend
changes. In dev mode a minimal `configureServer` vite plugin (15 lines in
`vite.config.ts`) maps `/docs-md/*.md` requests to `../docs/*.md` directly.

**Dependencies added.** `react-markdown@^10.1.0` and `remark-gfm@^4.0.1`
(both production deps). Neither drags in vite, esbuild, or vitest peer deps;
vite stayed at 5.4.21 and vitest stayed at 2.1.9 (confirmed post-install).

**Link rewriting rule.** In the `a` component override, any href matching
`^([a-z0-9-]+)\.md(#...)?$` is rewritten to `/docs/<slug>` (using
react-router `Link` for in-app navigation). External `https?://` links open
in a new tab. All other relative refs (anchor-only, unknown paths) pass
through as plain `<a>` tags.

**Settings link.** The dead `<a href="/docs/variant-parent-mode" target=_blank>`
in `Settings.tsx` was replaced with a react-router `<Link to="/docs/variant-parent-mode">`,
so it navigates in-app (same tab, no SPA fallback needed).

## 2026-06-11 — Small-fix batch (compose image, interval, pagination, dry-run, Settings copy)

Five independent bugs fixed in one pass (from the 2026-06-11 full-code audit):

**B9 — Wrong published image in docker-compose.yml.**
`docker-compose.yml` referenced `ghcr.io/hyiger/filament-bridge:latest` (the Filament DB
author's namespace). Corrected to `ghcr.io/crzykidd/filament-bridge:latest` to match the
registry declared in `.github/workflows/publish.yml` and `standards.md`. The same stale
reference was fixed in `docs/decisions.md` and `CHANGELOG.md`.

**B5 — Dashboard `next_sync_at` ignored the runtime interval.**
`api/sync.py:sync_status` computed `next_sync_at` using `settings.sync_interval_seconds`
(the env-var default), not the DB-overridden value stored in BridgeConfig. Fixed to use
`_effective_sync_interval(db)` from `api/config.py`, the same helper used by the scheduler
reschedule logic.

**B7 — Spoolman pagination cap.**
`services/spoolman.py` fetched a single page of 1 000 records for `get_spools`,
`get_filaments`, and `get_vendors`. Libraries larger than 1 000 entries were silently
truncated. Added a `_paginate()` helper that loops `limit=1000, offset=n*1000` until a
short page is returned, and updated all three methods to use it.

**Dashboard dry-run inconsistency with wizard settings.**
`core/dryrun.py:plan_dry_run` called `_plan_spoolman_to_fdb` without
`include_empty_spools` or `variant_keywords`, so empty-spool filtering and variant grouping
diverged from what the wizard preview shows. Fixed to read both from BridgeConfig via
`get_config_value` and `_resolve_variant_keywords` (inlined to avoid api→core cross-import),
matching the logic in `api/wizard.py:wizard_preview`.

**Settings interval copy mismatch.**
The Settings page said "Minimum 30 seconds (0.5 min)…" but the input's `min` is 1 minute
(values are whole minutes). Updated copy to "Minimum 1 minute. Takes effect immediately
without a restart." (The 30 s API floor is irrelevant for UI callers.)

## 2026-06-11 — Backup export/import fidelity: `is_synthetic_parent`, `conflict_type`, and auth secrets

**Bug A — `is_synthetic_parent` round-trip loss.**
`api/backup.py` export omitted `FilamentMapping.is_synthetic_parent`, so restoring a
`generic_container`-mode backup turned bridge-owned container parents into ordinary
mappings — synthetic-parent exclusions and the "spool on container parent" guard stopped
applying. Additionally, the import upsert keyed synthetic rows on `spoolman_filament_id`
(which is `NULL` for every synthetic parent), causing `filter_by(spoolman_filament_id=None)
.first()` to match an arbitrary existing synthetic row. Fixed: synthetic-parent rows are
now upserted on `filamentdb_id + is_synthetic_parent=True`; regular rows continue to use
`spoolman_filament_id`. Old backups without the key import as `is_synthetic_parent=False`
(safe default for pre-existing non-synthetic mappings).

**Bug B — `conflict_type` round-trip loss.**
`open_conflicts` export omitted `Conflict.conflict_type`, so restored `master_divergence`
conflicts came back as `cross_system` — the resolve endpoint treated them as record-only
and the UI lost the action workflow. Fixed: `conflict_type` is now included in the export
dict and in the `Conflict(...)` insert. Old backups without the key default to
`"cross_system"` (`.get("conflict_type", "cross_system")`), preserving backwards
compatibility without a schema-version bump. `BACKUP_SCHEMA_VERSION` stays at 1.

**Decision — schema compatibility over version bump.**
Both new keys are optional on import (`.get(..., default)`), so v1 backups produced by
older bridge versions still import without error. A version bump would have made old
backups unimportable for a pure additive change; that tradeoff was not worth it.

**Decision — auth secrets included in backup export.**
`auth_secret`, `admin_password_hash`, and `api_token` are intentionally included in
`GET /api/backup/export` so a restore is fully fidelity (no re-setup of credentials
required). `docs/security.md` now notes that backup files should be stored with the same
care as the bridge database volume.

## 2026-06-11 — Honor configured cross-reference field names in ensure_extra_fields + engine orphan guard

Two bugs only affecting users who override the cross-ref field env vars (`SPOOLMAN_FIELD_FILAMENTDB_ID`, `SPOOLMAN_FIELD_FILAMENTDB_PARENT_ID`, `SPOOLMAN_FIELD_FILAMENTDB_SPOOL_ID`, `FILAMENTDB_SPOOLMAN_ID_FIELD`).

**Bug A.** `ensure_extra_fields` had a module-level `_REQUIRED_SPOOL_FIELDS` list hard-coding the default key names. The filament section already built its field list at call time from `_settings`; the spool section did not. Fixed by replacing the static list with a `runtime_spool_fields` list built from `_settings.spoolman_field_filamentdb_{id,parent_id,spool_id}` inside the function body, matching the existing filament-section pattern.

**Bug B.** The new-FDB-spool detection block in `engine.py` (`run_sync_cycle`) read `getattr(fdb_spool, fdb_field_name, None) if fdb_field_name == "label" else None`. The guard was a no-op for any non-default field name, so a spool that already carried a Spoolman ID in a custom field was treated as brand-new → duplicate spool created. Fixed by removing the `== "label"` condition; `FDBSpool` has `extra="allow"` so any configured field name is accessible via `getattr`.

## 2026-06-11 — Fix wizard Pass-2.6 finish-tag wire format (CSV not JSON array)

`api/wizard.py` Pass 2.6 was calling `encode_extra_value(finish_ids)` where `finish_ids` is a Python list, producing a JSON-array wire value (`[17]`) that Spoolman 400s on. Fixed to `encode_extra_value(serialize_material_tags(finish_ids))` matching the engine path. The failure was silently swallowed as a warning, so the `filamentdb_material_tags` extra field was never stamped during wizard import.

## 2026-06-11 — FR-11 fix: FDB `_field_values` now persisted in spool snapshots

**Bug:** `engine.py:_fdb_snapshot_dict` requires both `filament_detail` and `field_maps`
to embed `_field_values`, but every snapshot-refresh call site in `run_sync_cycle` passed
only the spool object. Result: `fdb_snapshot._field_values` was always absent, so the
differ saw `fdb_then = None` for every mapped field every cycle — any non-None FDB value
looked like a perpetual FDB-side change (spurious PATCH to Spoolman every cycle under
`filamentdb_to_spoolman`; spurious conflicts under `two_way`).

**Fix approach (snapshot-merge after the field-mapping pass):**

- `_apply_field_changes` return type changed from `None` to
  `tuple[dict, dict] | None` — returning `(fdb_field_values_after, sm_extra_decoded_after)`.
  Both dicts reflect any writes made this call (anti-ping-pong: FDB→SM writes update
  `sm_extra_decoded[sm_key]`; SM→FDB writes update `fdb_field_values[fdb_path]`).
- After `_apply_field_changes`, the caller calls `_merge_snapshot` (read-modify-write)
  to store `_field_values` into the FDB spool snapshot and `_extra_decoded` into the SM
  spool snapshot. `_merge_snapshot` was already used by filament-level passes; it's now
  shared for spool-level use too — safe because spool snapshot rows are also keyed
  `(source, entity_type, entity_id)`.
- **First-sight baseline path**: when `field_maps` is non-empty, the engine now fetches
  `fdb_detail` and passes it to `_fdb_snapshot_dict`, so `_field_values` is stored in
  the very first baseline. This means the next cycle can diff real changes rather than
  always seeing None as the prior value.

**Files changed:** `backend/app/core/engine.py`, `backend/app/core/version.py`
(stale header comment on `MIN_FDB`/`MIN_SPOOLMAN` updated to reflect hard-gate behavior).

## 2026-06-11 — MappingRow carries `conflict_id`; Synced Records deep-links to Conflicts

`MappingRow` (both `schemas/api.py` and `frontend/src/api/types.ts`) includes `conflict_id: int | None`
populated by `build_mapping_rows()` from the already-computed `conflict_id_by_sm` / `conflict_id_by_fdb`
lookup. This lets the frontend jump directly to the specific conflict from a Synced Records row.

UI surface: Synced Records rows where `status === "conflict"` show a **"See conflict"** button
(amber, icon + label, dark-mode aware) that calls `useNavigate('/conflicts?highlight=<conflict_id>')`.
The Conflicts page reads the `highlight` query param via `useSearchParams`, auto-expands the matching
row, applies a 2.5 s amber ring highlight, and scrolls it into view. If the target id is absent from
the open queue (already resolved or never existed) a dismissible amber notice is shown instead.
The `highlight` param is cleared from the URL after handling so refreshes don't re-flash.

## 2026-06-10 — Engine: stale spool mappings purge instead of queuing deletion conflicts

A deletion conflict is only warranted when there is a **live, still-linked counterpart to protect**. Otherwise the connection is stale and the engine purges it from its own DB (bridge-local rows only — never upstream records).

**Rule (enforced in `core/engine.py`, spool-mapping loop):**

- **One side deleted, the OTHER side still exists AND is still linked** → queue a `__record_deleted__` deletion conflict (ask the user whether to delete the surviving side too). "Still linked" for the surviving Spoolman spool means its `filamentdb_spool_id` extra field is non-empty.
- **Both sides gone**, OR **FDB spool deleted and the Spoolman spool no longer carries the `filamentdb_spool_id` cross-reference** (user cleared it / unlinked) → **stale connection**: purge the `SpoolMapping` + its `Snapshot` rows, auto-resolve any open `__record_deleted__` conflict for it (`resolution="auto_stale_purge"`), increment `result.skipped`. No conflict surfaced.

**`_purge_stale_mapping` helper** (added to `engine.py`): mirrors `_cleanup_orphaned_mapping` in `api/conflicts.py` — deletes Snapshots, resolves open deletion conflicts, deletes the SpoolMapping, and emits a sync-log audit entry.

**Dry-run behavior:** emits a `{"action":"skip", "reason":"stale connection — would remove from bridge (upstream deleted, no live link)"}` preview entry and mutates nothing.

**Secondary cleanup (same cycle):** after the spool loop, orphaned `FilamentMapping` rows (non-synthetic-parent, no remaining `SpoolMapping` referencing them, FDB filament absent) are also purged with their filament-level `Snapshot` rows. Conservative: all three conditions required.

This self-corrects after a full upstream wipe (like the user scenario that triggered this) so Synced Records matches the Dashboard on the next sync cycle.

## 2026-06-10 — Wizard planner validates mappings against live FDB; stale → recreate + replace

When the wizard planner (`core/planner.py:_plan_spoolman_to_fdb`) encounters a local
`FilamentMapping` or `SpoolMapping` whose FDB target no longer exists (user deleted the
FDB record but the bridge mapping lingered), it now treats the mapping as **stale** rather
than skipping the record as "already linked".

**Phase A (filament):** if `existing.filamentdb_id` is not present in the live `fdb_by_id`
index → stale: store the mapping on `_FilamentPlanItem.stale_filament_mapping`, skip the
"already linked" path, and route through the normal decision logic (create/link). The plan
item carries `detail="stale mapping (FDB filament gone) — recreating"` for logging.

**Phase C (spool):** if a `SpoolMapping` row exists for the SM spool but its
`filamentdb_spool_id` is not in the live FDB spool-id set → stale: store the mapping on
`_SpoolPlanItem.stale_spool_mapping` and route as a create instead of a skip.

**Execute cleanup (`api/wizard.py`):** two new helpers — `_delete_stale_filament_mapping`
and `_delete_stale_spool_mapping` — delete the stale row + its `Snapshot` rows before
writing the fresh mapping, leaving exactly one correct mapping and no orphan. The filament
mapping helper also handles the case where `fil_map_by_sm` (loaded before the plan) still
holds the stale object: the execute path checks `fil_map is item.stale_filament_mapping`
and replaces it.

This fix is scoped to the wizard re-import path only. Engine-side stale-mapping purging is
a separate prompt (`prompts/2026-06-10-purge-stale-orphaned-mappings.md`).

## 2026-06-10 — Debug: added POST /api/debug/full-reset

Added a third debug endpoint that performs both one-sided cleanups in a single
call, resolving the half-cleaned state problem when users forget to run both.

**What it does:**
1. Runs `_blank_spoolman_xrefs()` first (blanks the three cross-ref extras on
   every Spoolman spool that has any set).
2. Runs `_reset_bridge_tables()` second (deletes all five bridge state tables —
   FilamentMapping, SpoolMapping, Snapshot, Conflict, SyncLog — and resets
   `wizard_completed` to false).

**Failure handling:** If the Spoolman fetch fails, the bridge DB reset still
completes and the error is reported in the `spoolman_error` field of
`FullResetResponse` (not a 502). This avoids a stranded state where the user
cannot reset at all because Spoolman is temporarily unreachable.

**Shared helpers:** `_blank_spoolman_xrefs()` and `_reset_bridge_tables()` are
now the canonical implementations — the two existing one-sided endpoints
(`clear-spoolman-fdb-refs` and `reset-bridge-state`) delegate to these helpers.
No logic is duplicated.

**UI:** Settings Debug zone now shows three buttons with clear scope labels:
- "Clear Spoolman cross-refs (Spoolman only)" — blanks Spoolman extras only
- "Reset bridge DB (bridge only)" — resets bridge tables only
- "Full reset (bridge DB + Spoolman links)" — does both; has a dedicated confirm
  dialog stating it does NOT delete records in Filament DB or Spoolman.

## 2026-06-10 — Wizard import: created FDB filament naming rule (variant + standalone)

When the wizard creates a Filament DB filament from Spoolman, the FDB name must always
include vendor + material so names are globally unique and never bare-color-only.

**Naming rule:**
- `base_name` = vendor + stripped-material + finish-line (produced by `_filament_base_name`
  in `core/planner.py`, shared by both the planner and `_container_display_name`).
- **Variant creates** (Phase B): `"{base_name} {sm.name}"` where `sm.name` is the color label.
  The base_name is derived from the master SM filament, so master and variant names share the
  same prefix and can never drift (e.g. "Hatchbox PLA Red" → "Hatchbox PLA Light Blue").
- **Standalone creates** (Phase B.5): same formula applied to the filament itself.
- **Dedup guards** (all case-insensitive):
  1. sm.name already starts with base_name → return sm.name unchanged (full name stored in SM).
  2. base_name already contains/ends with sm.name → return base_name (color = material token).
  3. sm.name starts with the bare material prefix that is already in base_name → strip material
     prefix and append suffix (e.g. "PLA Red" + base "ELEGOO PLA" → "ELEGOO PLA Red").
- **Link actions** (standardized/existing): name is never changed.
- **Master/container marker** (`(Master)`) appears only on the synthetic container parent in
  `generic_container` mode, not on variants or standalones.
- `_compute_name_collisions` naturally works against the new names since it reads `fdb_payload["name"]`.

Motivation: raw Spoolman names are often bare colors ("Light Blue", "Beige"). Two filaments
from different lines with the same color both produce "Light Blue" → FDB 409 → silent import
failure. Qualifying with vendor+material makes them unique.

## 2026-06-10 — Wizard execute response: added `label` field to `WizardExecuteRecord`

`WizardExecuteRecord` (in `schemas/api.py` and `api/types.ts`) gained a new optional
`label: str | None` field carrying a human-readable record identifier (e.g. "ELEGOO PLA Red"
or "ELEGOO PLA Red (spool 42)"). The field is populated at every `res.add()` call site in
`api/wizard.py` using the new `_sm_label()` and `_fdb_label()` helpers. It is `null` on
records from older clients / preview plan rows (`WizardPreviewResponse.plan_rows` reuses the
same model but those rows are written by `planner.py` which is out of scope). Any consumer
may treat a null `label` as "use the ID fallback".

Motivation: the previous response carried only IDs and a free-text `error` string. A failed
re-import showed only a count; the user could not identify which records failed or why.

## 2026-06-10 — Phase B: master_divergence resolve→apply workflow

### A — Resolve endpoint is now async and writes upstream for master_divergence conflicts

`POST /conflicts/{id}/resolve` was a sync, record-only endpoint. Phase B converts it to
`async def` and injects `SpoolmanClient` + `FilamentDBClient` from `request.app.state`
(the same pattern used in `api/sync.py`). For conflicts with `conflict_type == "master_divergence"`
it now calls `core/conflict_apply.apply_master_divergence()` before marking the conflict
resolved. All other conflict types continue to be record-only (no upstream writes).

### B — Three resolution actions for master_divergence conflicts

The `ConflictResolveRequest` schema gains an optional `action` field
(`"apply_all" | "variant_override" | "ignore"`). For `master_divergence` conflicts `action`
is required (422 if missing); for other types it is silently ignored.

| Action | FDB writes | Spoolman writes |
|---|---|---|
| `apply_all` | Master + any variant with explicit override of field F | Every SM filament mapped to a variant in the line |
| `variant_override` | This variant only (per-variant override) | None (SM is the source) |
| `ignore` | None | None |

### C — Snapshot refresh anti-ping-pong

After every apply action, `_merge_snapshot` is called for every touched record on both
sides, setting `_mp_<sm_field>` to the agreed value. This mirrors the engine's
post-weight-write snapshot refresh (see weight-propagation note in decisions.md). Without
this, the next sync cycle would re-detect the change as a fresh divergence and re-queue
the conflict.

`apply_all` skips the snapshot refresh for any record whose upstream write failed (tracked
in `failed_fdb_ids` / `failed_sm_ids`). The prior behavior stamped a "synced" baseline on
those records even though the write never landed, suppressing re-detection. With the fix,
failed records keep their old baseline so the next cycle re-detects and retries the write.
Inherited variants (never written individually) are still refreshed correctly because their
effective value resolves from the master via FDB inheritance.

### D — Sibling auto-resolve for apply_all

`apply_all` writes the new value to the entire filament line. Any other open
`master_divergence` conflicts for the same SM field on variants of the same master are
auto-resolved at the same time (marked `resolution="apply_all"`, `resolved_value=new_value`)
since the write that satisfies them has already happened.

### E — Upstream failure handling

If any upstream write fails, `apply_master_divergence` re-raises the exception without
marking the conflict resolved. The router catches it and returns 502 with the error detail.
The conflict remains open so the user can retry.

### F — GET /conflicts/{id}/divergence-context endpoint

New read-only endpoint for the UI. Fetches live FDB data to show: master id + name + current
value, plus the full variant list with current value, inherited/overridden status, and
Spoolman filament id (for deep links). Only valid for `master_divergence` conflicts; returns
400 for other types.

### G — apply logic in core/conflict_apply.py

All write logic is isolated in `core/conflict_apply.py` (testable async module, no router
dependency). The router imports and calls `apply_master_divergence()` / `build_divergence_context()`.
Engine helpers `_log` and `_merge_snapshot` are reused directly.

### H — _variants field uses Pydantic field name

`FDBFilamentDetail._variants` is exposed as `variants` (Pydantic alias). Code that accesses
the list uses `getattr(detail, "variants", None)` and reads `.id` on each `FDBVariantRef`
object (not `["_id"]` dict access). `_inherited` similarly maps to `inherited_fields`.

## 2026-06-10 — Phase A: native shared-filament scalar sync + conflict_type column

### A — Five native scalars synced directly (not via extra-field mapper)

SM `material` / `density` / `diameter` / `spool_weight` / `weight` are **native Spoolman
filament fields** with direct FDB counterparts (`type`, `density`, `diameter`, `spoolWeight`,
`netFilamentWeight`).  The generic extra-field mapper (`resolve_field_map` / `_apply_field_changes`)
handles Spoolman *extra* fields only — it does not reach native SM filament fields.  A new
dedicated pass `_sync_material_scalars` in `engine.py` handles the five pairs, mirroring
`_sync_cost` and `_sync_material_props` in structure.

Snapshot keys `_mp_<sm_field>` coexist with `_mc_sig`, `_cost`, `_finish_sig` via
`_merge_snapshot` (no clobbering).  FDB values are read from the **detail view** (not the list
view), since inherited values resolve there.

### B — Master/variant gate for PUSH_SM_TO_FDB

The blanket `should_skip_inherited` rule (used in `_apply_field_changes`) was too coarse for
the native-scalar pass — it silently skipped any inherited field regardless of whether the SM
value matched or diverged from the master.  The scalar pass instead implements a three-way
gate:

1. **Standalone OR already overridden** (`not has_parent OR not inherited`) → write directly.
2. **Inherited AND SM value matches resolved (inherited) value** → skip (no redundant override
   that would detach the field from the master for zero benefit).
3. **Inherited AND SM value diverges** → queue `master_divergence` conflict (record-only; no
   write; Phase B owns the apply workflow).

### C — conflict_type column: "cross_system" vs "master_divergence"

A new `conflict_type` column (SQLite `server_default="cross_system"`) was added to the
`conflicts` table (Alembic migration `f8d3e9c1a7b2`).

- `"cross_system"` — standard both-sides-changed conflict (all prior passes; remains the
  default so existing rows are unaffected).
- `"master_divergence"` — SM→FDB would override an inherited field that differs from the SM
  value; record-only pending Phase B (no upstream write).

`_has_open_conflict` accepts an optional `conflict_type` parameter so cross_system and
master_divergence conflicts on the same `(entity_type, field, spoolman_id, fdb_filament_id)`
tuple are deduplicated independently — a resolved master_divergence does not suppress a
subsequent cross_system conflict on the same field, and vice versa.

### D — Synced Records display fixed: _mp_* and _mc_color from snapshots

`_build_detail` in `api/mappings.py` previously returned `None` for material, density,
diameter, and color on the FDB side (hard-coded).  It now reads:

- `_mp_material`, `_mp_density`, `_mp_diameter` from the FDB filament snapshot (populated by
  `_sync_material_scalars`).
- `_mc_color` from the FDB filament snapshot (populated by `_sync_multicolor`, added in Phase A).

Values are `None` until the first sync baseline is stored — displayed as "—" in the UI.

## 2026-06-09 — Light/dark/system theme infrastructure

### A — localStorage-only persistence, no backend config entry

Theme preference is stored in `localStorage` key `fb_theme` (values `'light'|'dark'|'system'`).
Not persisted to the backend `BridgeConfig` table. Rationale: theme is a per-browser/per-device
UI preference, not a server-side setting. Multiple browsers visiting the same instance can
independently choose their own theme without conflict.

### B — Pre-paint inline script in index.html

A short inline `<script>` in `index.html` `<head>` reads `localStorage('fb_theme')` and
immediately adds the `dark` class to `<html>` (and sets `color-scheme`) before any React
code executes. This prevents the white-flash-on-dark-OS-preference problem that would occur
if theme was applied only after React hydrates. The script mirrors the logic in
`ThemeContext.tsx:applyTheme()`.

### C — Three-mode system: `light` | `dark` | `system`

`system` (the default) tracks `window.matchMedia('(prefers-color-scheme: dark)')` via an
`addEventListener('change')` listener attached in `ThemeProvider`. When the OS switches
(e.g. auto-dark at sunset), the UI follows without a page reload.

### D — Incremental dark-polish for large Wizard files

Step3Matches (687 lines), StepVariances (1301 lines), StepNPreview (548 lines), and
OpenTagCleanup (1215 lines) received outer structural dark polish only (loading states,
error banners, headings, action bars, outer container cards, table chrome). Inner
sub-components (`MemberRow`, `StatusPill`, `FTag`, `OptBadge`, `FilamentCard`,
`FieldReviewRow`, `GroupSection`, plan-detail and flag-section internals) are left for
a follow-up task. The primary surfaces and shared chrome are fully dark-correct.

## 2026-06-09 — Version display, GitHub update check, dev channel marker

### A — Backend-proxied GitHub release check, cached 6 h

The backend calls `https://api.github.com/repos/crzykidd/filament-bridge/releases/latest`
and caches the result in-memory for 6 hours. The browser never calls GitHub directly.
Rationale: avoids CORS complexity; allows the endpoint to degrade gracefully (cached value
or `null`); a single caching point is easy to reason about. No new Python dependency —
`urllib.request` from the stdlib handles the call.

### B — `/api/version` is PUBLIC (no auth required)

`GET /api/version` is registered without `require_auth`, alongside `/api/health` and
`/api/auth/*`. Rationale: the current version / channel / commit are not sensitive
information. Making it public lets the version badge render immediately even if the session
has expired, matching the LabelForge pattern. A future change that returned private data
would warrant moving it behind auth; the current payload does not.

### C — Dev channel + short SHA baked in at image build time

`BRIDGE_CHANNEL` and `BRIDGE_COMMIT` are set via Docker build args (`BUILD_CHANNEL`,
`GIT_COMMIT`). The running container has no `.git` directory, so runtime detection is not
possible. The ARG/ENV lines are placed near the very end of the Dockerfile, immediately
before EXPOSE/CMD, to avoid busting earlier cache layers on every commit. The default
channel is `release` so a plain `docker build` (and the prod compose) need no extra wiring.

### D — Update nag suppressed on dev builds

When `channel != "release"`, `update_available` is forced to `false` even if `latest >
current`. Rationale: dev builds run ahead of the latest release; showing "update
available" on a dev build would be misleading. `latest` is still returned so operators
can see what the latest release is without acting on the nag.

### E — Per-version localStorage dismissal; no popup on first run

The release-notes modal is shown when `update_available` is true AND a previous version
was stored in `localStorage['fb_last_seen_version']` AND that stored value differs from
`latest`. Omitting the popup on first run (no stored value) prevents alarming users of
fresh installs. This mirrors the LabelForge pattern.

**Revisit when:** a server-side notification delivery mechanism is warranted, or when
the GitHub call should be opt-in (currently always-on).

## 2026-06-09 — Single-account auth + API token + first-login required-settings gate

### A — Stateless signed cookie (no sessions table)

Used itsdangerous `TimestampSigner` rather than a DB-backed sessions table. Rationale:
no migration needed, no GC job, survives concurrent instances. The signing secret
(`auth_secret`) is auto-generated on first startup and persisted in `BridgeConfig`.

### B — API token stored in BridgeConfig (plaintext)

The API token value is stored in `BridgeConfig` as plaintext so the Settings UI can
display it (masked). For a single-user self-hosted app the token is no more sensitive
than the SQLite database file. Hashing the token was considered but rejected because
it would prevent display without a reveal-once UX that adds complexity for no
meaningful gain in this threat model.

### C — change-password endpoint does NOT require the session cookie

The `POST /api/auth/change-password` endpoint is mounted on the `auth_router` which
is public (no router-level `require_auth` dependency). However, it verifies the
current password before accepting the new one, providing equivalent security without
needing the cookie. This also works in the `AUTH_ENABLED=false` recovery flow where
a cookie may not be present.

### D — required_settings_unset as a list in ConfigResponse

Added `required_settings_unset: list[str]` to `ConfigResponse` (and
`GET /api/config`) rather than a separate endpoint. Rationale: the frontend already
calls `/api/config` on Settings load; piggybacking the required-settings check avoids
a second round-trip. The list is computed server-side so future required settings can
be added without frontend changes.

### E — `require_auth` applied via router-level `dependencies=` in main.py

Rather than decorating each individual route handler, `require_auth` is applied
as a router-level dependency on the 9 protected `include_router()` calls in
`main.py`. The 4 public exceptions (health + auth endpoints) are simply left
without the dependency. This is explicit, easy to audit, and avoids accidentally
forgetting auth on a new route inside a protected router.

## 2026-06-09 — Configurable container marker, Master/Parent badge, editable collision rename

### A — Container marker changed from `" Master"` to `"(Master)"` and made configurable

`_CONTAINER_MASTER_SUFFIX = " Master"` constant removed from `api/wizard.py`. In its place,
`_container_display_name()` accepts a `marker` parameter (default `"(Master)"`). The marker
is appended as `base_name + " " + marker` when non-empty, or just `base_name` when empty.

Rationale for the parenthesised form: `"(Master)"` visually separates the marker from the
filament name so `"ELEGOO PLA (Master)"` reads as "container" at a glance and is clearly
distinct from a color child like `"ELEGOO PLA Red"`. The plain `" Master"` form was easy to
confuse with part of the filament name.

The marker is runtime-configurable via `container_parent_marker` BridgeConfig key (env
`CONTAINER_PARENT_MARKER`, default `"(Master)"`). Settings UI shows a checkbox + text field
inside the Variant parent mode card, visible only when `generic_container` is selected.

**Migration note (accepted risk):** changing the marker does not rename existing containers.
A re-run with a changed marker will not find the old container via the cluster-tuple lookup
and will attempt to create a new container under the new name. The resilient-409 backstop
and the new per-cluster collision rename/skip UI handle any resulting collision. This was
accepted as preferable to a migration that renames records in FDB without user consent.

### B — `master_fdb` RowStatus for synthetic container parents in wizard Matches step

Bridge-owned FDB container parents (those with `FilamentMapping.is_synthetic_parent=True`,
or `hasVariants=True`, or a name ending in the configured marker) previously showed as
"Unmatched (FDB)" — an alarming, actionable status implying they need to be linked or skipped.

Added `'master_fdb'` RowStatus to `Step3Matches.tsx` with purple badge "Master / Parent".
These rows: do not count toward the "unmatched" total, are excluded from bulk-select
operations, do not show skip/link actions. Detection order: `is_synthetic_parent` mapping
(authoritative) → `hasVariants=True` (fallback for non-bridge parents) → marker-suffix
heuristic (last resort, for display consistency before mappings are created).

### C — Editable container-name override at Preview (skip cluster)

Container-name collisions at Preview now render an editable text box and a "Skip cluster"
control in `StepNPreview.tsx`. Overrides persist as `wizard_container_name_overrides` in
`BridgeConfig` (a `dict[cluster_key_str, {name_override, skip}]`).

In execute (`_execute_spoolman_to_fdb`):
- **Skip:** all SM filament IDs in the cluster are added to `_skipped_gc_sm_ids` before
  the container loop continues. Pass 1 and Pass 2 check this set and skip items, emitting
  a "cluster skipped per container-name override" log entry. No orphan records are created.
- **Rename:** the `name_override` string is used as `display_name` instead of the generated
  container name. The resilient-409 backstop catches any collision that slips through.

Cluster keys are stored as `str(cluster_tuple)` (e.g. `"('elegoo', 'pla', '')"`) since JSON
dict keys must be strings and tuples are not JSON-serializable.

## 2026-06-08 — OpenTag matching fixes + unmatched-UI enrichment

### A — normalize_vendor: hyphens treated as spaces

`normalize_vendor()` in `core/matcher.py` now runs `re.sub(r"[-_]+", " ", n)` before collapsing
whitespace. This is a shared function (variant clustering, vendor dedup, OpenTag brand gate).
Treating a hyphen like a space is correct for vendor names generally — the full backend test
suite was run and no existing test encoded the old hyphen behavior; 0 regressions.

The root cause: Spoolman vendor `"VOXEL-pla"` → `"voxel-pla"` while OpenTag brand `"Voxel PLA"`
→ `"voxel pla"`, so the brand bucket lookup returned 0 candidates and scoring never ran.

### B — Color-words map + score rebalancing

Added `DEFAULT_COLOR_KEYWORDS` (dict[str, str]) in `core/opentag_match.py` mapping color and
marketing words to canonical base colors (e.g. `"galaxy" → "black"`, `"cool" → "grey"`).

The `score_candidate` function was updated:
- Hex weight: 0.10 → **0.15** (hex is ground truth, not brand marketing)
- Color-name component: 0.30 → **0.25 token-sim + 0.05 base-color bonus**
- Total weight is unchanged (sums to 1.0 for a perfect match)

The base-color bonus is only awarded when token similarity < 1.0 (no double-credit for exact
matches) and both sides reduce to the same non-empty base via the map. This means "Jet Black" and
"Galaxy Black" (both → "black") now score above the 30% threshold even though their token sets
are disjoint.

The color map is user-extendable via `OPENTAG_COLOR_KEYWORDS` env var or the new "Color word
mappings" Settings field. User entries are merged on top of the seed defaults.

The scoring change was validated: all 747 existing backend tests pass; the accepted
"orange vs copper" regression test still passes; no previously-correct match regressed.

### C — Unmatched section enrichment (UI only)

Each row in the OpenTag Cleanup unmatched `<details>` section now renders: color swatch,
filament name, vendor (or red "No manufacturer" badge when missing), material badge, Spoolman
deep link, confidence badge, and `no_match_reason`. No backend changes were required —
`OpenTagFilamentMatch` already carried all these fields; only the frontend was using `{name}
({vendor}) — {pct}%`.

## 2026-06-08 — Container naming "Master" suffix + resilient 409 execute

### P0.1 — Strip finish word from material before composing container name

`_container_display_name` now calls `strip_finish_words(material, tag_map)` before composing
the display name. This prevents "PLA Silk Silk Master" when `rep.material = "PLA Silk"` — the
finish word is already in the material, and was being appended a second time from
`extract_finish_line`. `planner.py` already does this with `base_type = strip_finish_words(...)`.

### P0.2 — " Master" suffix on container names (decided: always append)

The container parent name always ends with `_CONTAINER_MASTER_SUFFIX = " Master"` (e.g.
"ELEGOO PLA Silk Master"). Rationale: without the suffix, the container name is the same prefix
as each child (e.g. "ELEGOO PLA Silk" vs "ELEGOO PLA Silk Red"), and Filament DB's global
uniqueness constraint for `name` makes it trivial to produce a collision if the user happens to
have a filament already named "ELEGOO PLA Silk". The suffix makes the container namespace
distinct. The constant is in `api/wizard.py` so it's easy to change later without grep.

If the "… Master" name still collides (pre-existing record), the Preview step surfaces it as a
name collision with an actionable "Fix variant mapping" link. A 409 on execute is now per-record
(P1.1), so a container collision does not abort the rest of the batch.

### P0.3 — optTags patch on container reuse

On re-run with a pre-existing container, the wizard computes the intersection of finish tags
across all cluster members and PATCHes them onto the container if any are missing. The merge
preserves existing unrelated tags. This is idempotent and non-fatal (errors are logged as
warnings). It brings containers created before the finish-tag logic current without a full reset.

### P1.1 — Resilient 409 on filament/container create

Each `create_filament` call in `_execute_spoolman_to_fdb` (container pre-pass, Pass 1 masters,
Pass 2 variants) is now individually wrapped to detect `httpx.HTTPStatusError` with
`response.status_code == 409`. A 409 is recorded as `failed` with detail
`"name collision: <name>"` and the batch continues. This avoids the "bomb out on second filament"
failure mode seen in live testing. The `_is_409(exc)` helper is the single detection point.

## 2026-06-08 — Generic container parent mode for Bulk Import Wizard

### Feature summary

`variant_parent_mode` is a new `BridgeConfig` key (`"unset"` / `"promote_color"` /
`"generic_container"`) that controls how the wizard structures the Filament DB parent/variant
hierarchy when importing from Spoolman. The wizard is now **gated** on a non-`unset` choice:
`GET /wizard/preview` and `POST /wizard/execute` return `409 variant_parent_mode_unset` when
the import direction is Spoolman and the mode is still `"unset"`. This prevents silent imports
using an implicit default the user never chose.

### Why `unset` instead of a hard default

Making the gate an explicit `"unset"` state (rather than silently defaulting to
`"promote_color"`) forces a one-time deliberate choice. Existing installs that already ran the
wizard before this setting was added continue to work — their mappings are valid regardless;
only _new_ wizard runs are gated.

### Synthetic container parent — bridge ownership model

In `generic_container` mode, the wizard creates a **colorless FDB-only parent** for every
cluster (including single-color clusters). The container:

- Has `spoolman_filament_id = NULL` in `FilamentMapping` (no Spoolman counterpart).
- Has `is_synthetic_parent = True` in `FilamentMapping` — a flag that marks it as
  bridge-owned metadata.
- Is excluded from `filament_mappings_by_sm`, `filament_mappings_by_fdb`, and
  `_sync_opentag_identity` in the engine so it never participates in sync, never generates
  conflicts, and never appears as an orphan.
- If a spool is placed directly on a container parent in FDB (user error), the engine logs a
  warning and skips it.

### Why nullable `spoolman_filament_id` is safe under UNIQUE

SQLite (and SQL standard) allows multiple NULLs in a UNIQUE column — `NULL != NULL`.
Alembic migration `a1b2c3d4e5f6` uses `batch_alter_table(recreate="always")` to rebuild the
table in SQLite (which doesn't support ALTER COLUMN natively).

### Idempotency

On re-run, the wizard recovers the existing container's FDB id by:
1. Checking the Spoolman spool's `filamentdb_parent_id` extra field for a value matching a
   known synthetic parent `filamentdb_id`.
2. Falling back to `FilamentMapping` rows where `filamentdb_parent_id` points to a synthetic
   parent id.

Already-linked SM filaments skip Phase A of the planner and are excluded from the new-container
pre-pass (their `resolved=True` / `action="skip"` item is included in the cluster so the
container is found/re-confirmed, but no duplicate container is created).

### Container naming collision prevention

The lookup key for existing synthetic containers uses the full cluster tuple
`(vendor_norm, material_norm, finish_norm)` — the same key as variant-cluster assignment —
not the display-name string. Two clusters that normalize to the same display name but differ
by vendor, material, or finish are treated as distinct containers.

### FDB v1.35.2 / issue #597

Filament DB v1.35.2 fixed parent-swatch rendering for colorless parents (GitHub issue #597).
Both modes render cleanly in modern FDB. `generic_container` is a pure organizational
preference — it is NOT a rendering workaround. This rationale is documented in
`docs/variant-parent-mode.md` so users understand the scope of the choice.

## 2026-06-08 — Browser-local timestamp rendering (`d22cad8`)

All timestamps in the UI are rendered in the browser's local timezone.
`frontend/src/utils/datetime.ts` appends `"Z"` to naive UTC strings (no timezone suffix)
before passing them to `toLocaleString`, so the browser interprets them as UTC and converts
to local time rather than treating them as local time.

## 2026-06-08 — Conflicts page rework + `ColorDisplay` + multicolor in `_conflict_identity` (`eb9af66`)

The Conflicts page was rebuilt with collapsible rows, sort controls, expand-all, and resolve
clarity. A `ColorDisplay` component renders multicolor swatches. `_conflict_identity` in
`backend/app/api/conflicts.py` now extracts `multi_color_hexes` and `multi_color_direction`
from the Spoolman snapshot so conflict cards can show multicolor filament colors.
`new_spool` conflict action buttons are labelled "Dismiss" (not "Resolve") for clarity.

## 2026-06-08 — Sync-log windows view + `DELETE /sync-log` (`7b0361e`)

`GET /api/sync-log?windows=N` returns only the most recent N distinct `cycle_id` values
(default: all). This lets the UI page through recent cycles without downloading the full log.
`DELETE /api/sync-log` truncates the entire sync log table; gated to non-dry-run use and
exposed in Settings for user-initiated clear.

## 2026-06-08 — Synced Records enrichment: multicolor, weight, empty, conflict deep-link (`a870950`)

`MappingRow` (returned by `GET /api/mappings`) now carries `multi_color_hexes`,
`remaining_weight`, `is_empty` (remaining_weight == 0), and `conflict_id` (id of any open
conflict for this pair). The Synced Records table gains a hide-empty toggle, a multicolor
color swatch, a conflict deep-link icon, and an empty-state illustration.

## 2026-06-07 — Wizard OpenPrintTag flag + filter (`db8a4c6`, `4b5db3f`)

`FilamentRef` in the wizard matches response gains `openprinttag` (bool, `True` when the
Spoolman filament's `openprinttag_uuid` extra field is non-empty). The match-step filter bar
gains a "Tagged only" toggle that hides filaments without the flag, and a "Hide tagged"
toggle that hides already-tagged ones. An OPT badge appears on tagged rows in the table.

## 2026-06-07 — OPT stamped badge on OpenTag Cleanup cards (`7eb5e98`)

Each OpenTag Cleanup match card header shows an `OpenTagStampedBadge`: grey when the
Spoolman filament's `openprinttag_uuid` matches the selected candidate (in-sync); orange
when a UUID is set but differs from the candidate (drifted). No badge when unset.
`getExistingUuid` is extracted as a shared helper.

## 2026-06-07 — PLA+/grade modeling: base polymer + grade in name; no material guard (`memory/pla-plus-modeling-decision.md`)

PLA+ and grades (PLA-CF, PLA Marble, etc.) are modeled as base polymer type (`PLA`) with
the grade in the filament name — per the OpenTag spec. The bridge deliberately does NOT add
a material guard that preserves the literal string "PLA+"; the polymer-family gate in the
matcher maps both `PLA` and `PLA+` to the `pla` family so they remain mutually matchable.

## 2026-06-08 — gated Debug mode with reset tools for clean re-testing

Added a `debug_mode` bool config flag (default `false`) that gates two destructive
reset endpoints at `POST /api/debug/*`:

- **`clear-spoolman-fdb-refs`** — fetches all Spoolman spools and blanks the three
  cross-ref extras (`filamentdb_id` / `filamentdb_spool_id` / `filamentdb_parent_id`)
  on every spool that has any of them set. Writes to Spoolman; per-spool errors are
  logged without aborting the batch.
- **`reset-bridge-state`** — deletes all rows from `FilamentMapping`, `SpoolMapping`,
  `Snapshot`, `Conflict`, and `SyncLog` (local only — no upstream writes). Also resets
  `wizard_completed` to `false` so the wizard can be re-run cleanly. All other
  `BridgeConfig` keys (including `debug_mode`) are preserved.

Both endpoints return **403** unless `debug_mode` is currently `true` in `BridgeConfig`.
Debug mode is enabled/disabled via the standard `PUT /api/config` endpoint.

**Rationale:** When Filament DB is wiped for testing but Spoolman still carries stale
xref extras, the bridge floods the conflict queue with deletion conflicts on first sync.
These two tools provide a clean-slate path without manual database surgery.

**Decision — reset `wizard_completed`:** on `reset-bridge-state`, `wizard_completed` is
reset to `false` (not left as-is) so the user can cleanly re-run the wizard and rebuild
all mappings from scratch. This is the more useful behavior for the testing scenario
these tools target.

In the Settings UI, a "Debug mode" toggle reveals a red "Danger zone" block with both
buttons when enabled. The clear-refs button is gated behind `BackupSafetyDialog`
(writes to Spoolman); the reset-state button uses a plain `window.confirm` (local only).

## 2026-06-08 — multicolor writes always include multi_color_direction (Spoolman 422 fix)

Spoolman rejects a filament PATCH that sets `multi_color_hexes` without also setting
`multi_color_direction` with a 422: "Multi-color filament must have multi_color_direction set."
This caused thermochromic OpenTag entries (SM #12/#13 — 2 `secondaryColors`, a
`temperature_color_change` tag, no coextruded/gradient arrangement tag) to 422 on OpenTag
apply. These entries are classified `multi_unknown`; the `len(all_hexes) >= 2` branch in
`opt_to_spoolman_fields` was only setting `multi_color_direction` when `has_arrangement` was
true, leaving `multi_unknown` entries without a direction.

**Fix:** `opt_to_spoolman_fields` in `backend/app/core/opentag_match.py` now ALWAYS sets
`multi_color_direction` in the `len >= 2` branch:
- `gradient` arrangement → `"longitudinal"`
- `coextruded` arrangement → `"coaxial"`
- no/unknown arrangement (`multi_unknown`) → `"coaxial"` (safe default; Spoolman just
  requires *a* direction — coaxial is used for thermochromic and other entries where spatial
  arrangement is unknown)

`fdb_multicolor_to_sm` in `backend/app/core/color.py` was already safe — both multicolor
branches always paired `multi_color_hexes` with a direction.

The comment above the color rule in `opt_to_spoolman_fields` was updated to document that
direction is ALWAYS set for multicolor (defaulting to coaxial for unknown arrangements).

## 2026-06-08 — Entrypoint chown-then-gosu drop replaces static USER directive

The `USER 1000:1000` Dockerfile directive approach broke when users upgraded from a
root-owned `bridge-data` volume: the container process (uid 1000) could not write to
root-owned `/data`, producing `sqlite3.OperationalError: attempt to write a readonly
database` at startup.

**Change:** replaced the static `USER` directive with the standard entrypoint privilege-drop
pattern:

1. `gosu` is installed in the runtime image (`apt-get install -y --no-install-recommends gosu`).
2. `docker-entrypoint.sh` (POSIX `sh`, copied to `/usr/local/bin/`) runs as root:
   - Reads `PUID` / `PGID` (default `1000`).
   - `mkdir -p "${DATA_DIR:-/data}"` and `chown -R "${PUID}:${PGID}" "${DATA_DIR:-/data}"` with
     `|| true` so a read-only or odd FS never prevents startup.
   - If running as root: `exec gosu "${PUID}:${PGID}" "$@"` — drops to the target uid and
     execs the app with no remaining root capability.
   - If already non-root (e.g. if someone re-adds `user:` to compose): `exec "$@"` directly.
3. `USER 1000:1000` and `user: "1000:1000"` are removed from the Dockerfile and both compose
   files; the entrypoint is the single authority on runtime uid/gid.
4. The `groupadd` / `useradd` / `chown /app` / `mkdir /data` steps remain so fresh volumes
   start correctly and `/app` is still owned by the app user.

**Result:** the app always runs as uid 1000:1000 (or `PUID:PGID`); pre-existing root-owned
volumes are corrected automatically on every container start; no manual chown is ever needed.
Documented in README.md and docs/configuration.md.

## 2026-06-08 — Container runs as non-root 1000:1000; /data chowned in image (superseded)

The original approach (same date) used `USER 1000:1000` in the Dockerfile and explicit
`user: "1000:1000"` in both compose files, with a documented one-time chown step for
pre-existing root-owned volumes. This was superseded by the entrypoint chown-then-gosu
pattern above, which handles pre-existing root-owned volumes automatically.

## 2026-06-08 — docker-compose.yml ships bridge-only; full dev stack moved to docker-compose.dev.yml

`docker-compose.yml` previously bundled `filament-db`, `mongo`, and `spoolman` alongside the
bridge. Filament DB and Spoolman are separate upstream projects that users typically run
themselves; shipping them in the standard compose implied the bridge repo owns their lifecycle,
which it does not.

**Split:**

- `docker-compose.yml` — bridge-only standard deployment. Uses the published image
  (`ghcr.io/crzykidd/filament-bridge:latest`), a single `bridge-data:/data` volume, and
  placeholder `FILAMENTDB_URL` / `SPOOLMAN_URL` env vars pointing at the user's existing
  Spoolman and Filament DB instances. No `depends_on`, no upstream service definitions.
- `docker-compose.dev.yml` — full local stack for development and testing. Builds the
  bridge from source (`build: .`) and also brings up `filament-db`, `mongo`, and `spoolman`
  with internal network URLs (`http://filament-db:3000` / `http://spoolman:7912`). Uses
  named volumes (`bridge-data`, `mongo-data`, `spoolman-data`). Intended only for contributors
  and local testing — not for production deployments.

README Quick start updated to lead with `docker-compose.yml` (standard deploy) and reference
`docker-compose.dev.yml` for the full local stack.

## 2026-06-07 — Renamed to Bulk Import Wizard; ongoing SoT removed from wizard step; never_import_empties global setting

### Wizard renamed to "Bulk Import Wizard"

The "Initial Sync Wizard" is re-runnable any time (the execute path is idempotent — already-linked
records are skipped). The name "initial sync" was misleading for subsequent runs. All nav and heading
references now say "Bulk Import Wizard". The route (`/wizard`) and step paths are unchanged.

No hard "wizard already completed" block was implemented — the wizard is always accessible.

### Ongoing source-of-truth section removed from Step 2

`Step2Direction.tsx` previously contained a full "Ongoing source of truth" section (Weight / Material
properties / New spools) with Spoolman / Filament DB toggle buttons. These fields were already dead
(the ongoing sync engine reads `weight_sync_direction`, `material_properties_sync_direction`, etc. from
Settings, not from wizard state). The wizard `POST /wizard/direction` handler translated the binary
SoT choices into the new direction+policy keys, but that translation is now bypassed entirely.

**Removed:** `weight_source_of_truth`, `material_properties_source_of_truth`, `new_spool_source_of_truth`
from `WizardDirectionRequest` (backend schema) and `WizardDirectionRequest` (TS type). The wizard
direction POST now only persists `import_direction` (1 key → `persisted: 1`). Step 2 heading changed
from "Sync direction & source of truth" to "Import direction". A one-line note in the step tells users
where ongoing-sync and empty-spool settings live (Settings page).

Tests updated: `test_wizard_direction_persists_choices`, `test_wizard_direction_persists_new_direction_keys`,
`test_wizard_direction_filamentdb_sot_maps_to_fdb_direction` all reflect the simplified behavior.

### never_import_empties replaces the per-run "Include empty spools" checkbox

The per-run "Include empty / depleted spools" checkbox in Step 2 was confusing: users set it once per
wizard run and then forgot about it. Empty-spool import behaviour is a site preference, not a
per-import decision.

**Backend config:** `never_import_empties` (default `false`) added to:
- `BridgeConfig._DEFAULTS` seed → `"false"` (existing installs get the new default without migration)
- `ConfigResponse.never_import_empties: bool = False`
- `ConfigUpdateRequest.never_import_empties: bool | None = None`
- `_config_response()` in `api/config.py` reads the key
- `PUT /api/config` accepts and persists the value

**Wizard execute + preview:** `wizard_execute`, `wizard_preview`, and `wizard_variances` now read
`never_import_empties` from BridgeConfig and derive `include_empty = not never_import_empties`.
The `_plan_spoolman_to_fdb` planner's `include_empty_spools` parameter is unchanged — only the call
sites changed. The old `wizard_include_empty_spools` key is abandoned (no migration needed; it was
never exposed in the config API or Settings UI).

**Settings UI:** "Never import empties" toggle added to the "New spools" section in `Settings.tsx`.
Label: "Empty/depleted spools are skipped on import; the filament definition is still imported."
Saved via the main Save button (same as all other config fields).

**Preview (StepNPreview.tsx):** the `empty_active` flag section fetches config via `useApi(getConfig)`
and labels the section dynamically:
- `never_import_empties=false` → "Empty/depleted spools (will be imported)" with blue badge (info)
- `never_import_empties=true` → "Empty/depleted spools (skipped — 'Never import empties' is on)" with
  amber badge (flag)

No `NEVER_IMPORT_EMPTIES` environment variable is added — this is a runtime DB config value only
(consistent with other runtime settings like `sync_interval_seconds` and `never_import_empties` is a
user preference not an infrastructure setting).

## 2026-06-08 — Sync interval + log retention are runtime-configurable; no in-app log-file rotation

### Runtime sync interval

`BridgeConfig.sync_interval_seconds` (default 0) overrides `Settings.sync_interval_seconds`
(the `SYNC_INTERVAL_SECONDS` env var) when non-zero.  `_effective_sync_interval()` in
`backend/app/api/config.py` applies the override and clamps to ≥ 30 s.

At startup, `main.py` reads the DB override once (via `_effective_sync_interval`) to set the
initial APScheduler job interval.  When `PUT /api/config` receives a `sync_interval_seconds`
update, the config endpoint calls `scheduler.reschedule_job("sync_cycle", trigger="interval",
seconds=N)` on `app.state.scheduler` — no restart required.  Tests that don't wire the full
lifespan set no `app.state.scheduler`, so the reschedule path is silently skipped (no error).

`ConfigResponse` and `ConfigUpdateRequest` now expose `sync_interval_seconds` (ge=30 on
update) and the UI converts minutes ↔ seconds: value stored in seconds, displayed in minutes.

### Sync-log retention

`BridgeConfig.sync_log_retention_days` (default 30; 0 = keep forever).  `prune_sync_log(db,
retention_days)` in `backend/app/api/config.py` issues a single `DELETE` for rows older than
`now - retention_days` and returns the deleted count for logging.  No-op when
`retention_days == 0`.

Pruning runs at the start of each auto-sync tick, but auto-sync is **off by default** — so a
user on manual sync triggers would otherwise never prune (#22, fixed 2026-06-25). The
auto-sync-independent call sites all go through the wrapper `prune_sync_log_now(db)` (reads
the retention config, prunes, commits, swallows errors): the manual sync trigger
(`POST /sync/trigger`), the nightly backup job (before its master-switch gate, so it prunes
even when scheduled backups are off), and a one-shot at startup (mirrors the backup startup
prune). The original auto-sync-tick prune stays as-is.

### No in-app log-file rotation

The app logs to stdout only (structured JSON via `_JSONFormatter`); Docker/container runtime
rotates container logs.  No log-file rotation is implemented in the bridge itself, and no
`SYNC_LOG_RETENTION_DAYS` env var is added — retention is purely a runtime DB config value.

### Settings UI: "Scheduler & Logs" section

Added to `frontend/src/pages/Settings.tsx` (separate from the main Save flow for auto-sync
toggle; all other fields save via the existing Save button):

- **Auto-sync enabled** toggle: enabling is gated behind `BackupSafetyDialog` (same as
  Dashboard); disabling runs immediately.  Calls `POST /api/sync/auto` — not part of the
  config PUT.
- **Sync interval (minutes)**: number input (min 1); converts min ↔ sec for the API; shows
  an amber warning when interval > 5 minutes ("Longer intervals … raising the chance of merge
  conflicts").
- **Sync-log retention (days)**: number input (0 = keep forever).
- **Stdout note**: "Application logs go to the container's stdout — rotation is handled by
  your Docker logging driver."

## 2026-06-07 — new_spool conflicts: dedup + auto-resolve on map

Two bugs caused `new_spool` conflicts to pile up and go stale after a spool was mapped:

1. **No dedup.** `_handle_new_sm_spool` and `_handle_new_fdb_spool` called `_queue_conflict`
   unconditionally every cycle, creating a duplicate `new_spool` row each run. Fixed by
   adding an `_has_open_conflict` guard (keyed on `spoolman_id` for the SM side, on
   `filamentdb_spool_id` for the FDB side) before each `_queue_conflict` call — mirrors the
   existing pattern used by the field-conflict passes.
2. **Stale conflicts never cleared.** Once a spool mapping existed, the old open `new_spool`
   conflict was never resolved. Fixed by adding a clear-on-map pass in `run_sync_cycle`
   immediately after `mapped_sm_spool_ids` / `mapped_fdb_spool_ids` are built (non-dry-run
   only): any open `new_spool` conflict whose `spoolman_id` is in `mapped_sm_spool_ids` or
   whose `filamentdb_spool_id` is in `mapped_fdb_spool_ids` is resolved with
   `resolution="resolved_mapped"`. Covers both wizard-created and engine-created mappings.
   Deletion-conflict (`DELETION_FIELD`) behavior is unchanged.

## 2026-06-07 — Pre-write backup safeguard dialog gates destructive actions

A `BackupSafetyDialog` component (`frontend/src/components/BackupSafetyDialog.tsx`) gates
three destructive actions before they execute:

1. **Wizard Execute** (`Step6Execute.tsx`) — clicking "Execute sync" opens the dialog; `onProceed` runs `postWizardExecute`.
2. **OpenTag Apply** (`OpenTagCleanup.tsx`) — clicking "Apply N writes" in the ConfirmStep opens the dialog; `onProceed` runs the apply payload.
3. **Enable auto-sync** (`Dashboard.tsx`) — only the enable path is gated; disabling runs immediately without a dialog.

**Spoolman backup:** the dialog has a "Back up Spoolman now" button that calls
`POST /api/backup/spoolman` on the bridge backend. The backend proxies this to Spoolman's
`POST /api/v1/backup` (via `SpoolmanClient.trigger_backup()`), which writes an archive to
Spoolman's own data volume. On error the endpoint returns `{ success: false, detail: "…" }`
— never a 500.

**Filament DB backup:** FDB DOES have a backup API: `GET /api/snapshot` returns a full JSON
backup (`{version, createdAt, collections}` — filaments, nozzles, printers, locations, print
history, catalogs, tombstones; schema v4). The dialog has a "Back up Filament DB now" button
that calls `POST /api/backup/filamentdb` on the bridge backend. The backend fetches the FDB
snapshot and writes it to `DATA_DIR/backups/filamentdb-snapshot-<UTC-timestamp>.json`. Because
FDB delivers the snapshot to the caller (unlike Spoolman which writes to its own volume), the
bridge persists it in its own data volume. The mongodump command is retained as a secondary
"raw MongoDB" option in a small note.

**Proceed gate (original):** the Proceed button was disabled until EITHER backup succeeded (Spoolman OR
Filament DB; HTTP 200, `success: true`) OR the acknowledgment checkbox was checked. See
2026-06-18 entry — the dialog was later made unconditionally friendly (no checkbox, Proceed
always enabled) and the strict gate moved to a separate `DebugConfirmDialog`.
`docs/spoolman-writes.md` is unchanged — this is a trigger, not a field write.

## 2026-06-08 — Filament DB backup API correction

Earlier documentation (README and docs) incorrectly stated that Filament DB has no backup
API and recommended only `mongodump`. Filament DB exposes `GET /api/snapshot` for a full
JSON backup and `POST /api/snapshot` for restore. The bridge now uses this:

- `FilamentDBClient.get_snapshot()` in `backend/app/services/filamentdb.py` calls
  `GET /api/snapshot` with a 300 s timeout (snapshot can be large).
- `POST /api/backup/filamentdb` in `backend/app/api/backup.py` fetches the snapshot, creates
  `DATA_DIR/backups/` if missing, and writes `filamentdb-snapshot-<UTC-ts>.json`.
- The pre-write `BackupSafetyDialog` now shows a "Back up Filament DB now" button alongside
  the existing Spoolman button.
- README Backups section and `docs/prd.md` FR-24 updated accordingly.

## 2026-06-07 — Wizard pre-matches records by filamentdb_id cross-reference before fuzzy matching

`match_filaments` in `backend/app/core/matcher.py` now accepts an optional
`xref_by_sm_filament: dict[int, str] | None = None` parameter.  When provided,
a first pass runs before the fuzzy key pass: for each SM filament whose id maps
to an existing FDB filament id, both sides are immediately matched at confidence
1.0 and consumed so they cannot appear in fuzzy or unmatched buckets.  A stale
xref (FDB id not present in the current FDB list) falls through unchanged to fuzzy
or unmatched.  Passing `None` (default) preserves the original behaviour.

`wizard_matches` in `backend/app/api/wizard.py` builds this map by fetching all
Spoolman spools and extracting the `filamentdb_id` extra field (using
`_settings.spoolman_field_filamentdb_id` for the key and `decode_extra_value` to
decode the JSON-encoded string).  Archived spools and spools without a filament are
skipped; one xref per SM filament id is kept (first non-empty wins).  The resulting
map is passed to `match_filaments`.

This makes the wizard idempotent on re-run: already-linked records — including
multicolor filaments whose SM `color_hex` is `None` while FDB has an explicit color
(e.g. SM #86 → FDB `6a260f0ebba9189cd60f81de`) — are recognized as matched instead
of being shown as unmatched.

## 2026-06-08 — Single-hex OpenTag entries use color_hex; multi_color_hexes requires ≥2

Spoolman rejects a filament PATCH where `multi_color_hexes` contains only one color with a
422: "Must specify at least two colors in multi_color_hexes".  A thermochromic or other
one-color OpenTag entry (e.g. "Temperature Color Change PLA" with one `secondary_color` and
no `primary_color`) must therefore be written as `color_hex`, never as `multi_color_hexes`.

**Count-based color rule** (implemented in `opt_to_spoolman_fields` in
`backend/app/core/opentag_match.py` and guarded in `fdb_multicolor_to_sm` in
`backend/app/core/color.py`):

1. Collect `all_hexes` = primary (if present) + secondaries, normalised and de-duplicated.
2. `len >= 2` → `multi_color_hexes`; direction only when arrangement tag present; no `color_hex`.
3. `len == 1` and no arrangement tag → `color_hex` (single-color write).
4. `len == 1` and arrangement tag → emit NO color fields (leave Spoolman's existing
   `multi_color_hexes` untouched; writing a lone `color_hex` would 422 against it).
5. `len == 0` → no color fields.

`fdb_multicolor_to_sm` (the engine FDB→SM sync path) applies the same guard: coextruded or
gradient with fewer than 2 assembled hexes falls back to `color_hex` (or None), never emits
a one-hex `multi_color_hexes`.

`opt_color_profile` was also updated: a no-arrangement-tag entry with fewer than 2
`secondaryColors` is classified as `"single"` (not `"multi_unknown"`), since a one-color
entry cannot produce a valid multicolor Spoolman record.

## 2026-06-08 — OpenTag no-match reason taxonomy + group collapse UX

**no_match_reason** on `OpenTagFilamentMatch` (backend field, TS type, UI display):
Four mutually exclusive cases in priority order — (1) brand key not in `materials_by_brand`
→ "Manufacturer X not found in OpenTag (add a mapping in Settings)"; (2) brand found but
`filtered_candidates` empty after color-profile + polymer-family gates → "No X match for Y
in OpenTag"; (3) candidates were found but SM is multicolor (`sm_profile != "single"`) →
"Spoolman is multicolor; no multicolor OpenTag match"; (4) candidates scored but none reached
`min_confidence` → "No confident match (best N%)".  Matched rows always leave the field None.
Case 3 and 4 are distinguished by `mismatch` before `find_best_match` (not by its return);
the multicolor gate fires only when `filtered_candidates` is non-empty.

**Group collapse** defaults ALL groups collapsed (keyed by group key in `collapsedGroups`
state, default `true`).  Expand all / Collapse all buttons iterate `displayGroups`.
Collapsed header shows "N matched · M no-match · K tagged (total)" summary; "tagged" =
`existingUuid` non-empty (same logic as `OpenTagStampedBadge`, extracted to `getExistingUuid`).

**Group-level ignore** toggle on each header calls `setIgnoredIds` for all member
`spoolman_filament_id`s; `stopPropagation` prevents header click from toggling collapse.

**Sort by Spoolman ID**: ascending numeric `a.spoolman_filament_id - b.spoolman_filament_id`.

## 2026-06-07 — OpenTag cleanup: reviewable Manufacturer field reassigns Spoolman vendor via find-or-create

When the OpenTag cleanup matches a Spoolman filament to an OpenTag material across a vendor
name difference (e.g. via the `prusa=prusament` alias, or any case where the normalized SM
vendor name differs from the normalized OPT brand name), the review UI now shows a
**Manufacturer** field row (field key `"vendor"`) so the user can standardize the Spoolman
filament's vendor to match the OpenTag brand — or keep their current value.

**Surface (matches endpoint):**
`opt_to_spoolman_fields` in `backend/app/core/opentag_match.py` now includes
`result["vendor"] = opt.get("brandName")`.  `_build_field_rows` in
`backend/app/api/opentag.py` handles `"vendor"` specially via `_current_spoolman_value`
(`sm_filament.vendor.name`), and **only includes the row when
`normalize_vendor(sm_value) != normalize_vendor(opt_value)`** — omitting it when both sides
already agree (no alias or same-vendor match).

**Apply (vendor find-or-create reassignment):**
`_build_sm_patch` extracts the `vendor` field decision as a separate `vendor_name` string
(not included in the native PATCH dict, because vendor is a relation — `vendor_id`, not a
scalar).  In `opentag_apply`, a per-apply-call vendor index is built once from
`sm.get_vendors()`, keyed by `normalize_vendor(v.name)`.  `_ensure_vendor(name)` resolves
the chosen name to an existing `vendor_id` via normalized lookup, or calls
`sm.create_vendor({"name": name})` and caches the new id — ensuring no duplicate is
created even if the same vendor name appears in multiple decisions within the same apply
run.  `vendor_id` is then included in the filament PATCH payload alongside native/extra
fields.  `"vendor"` is reported in `fields_written`.

**No changes to the existing keep-mine, ignore, or other field mechanics.**

## 2026-06-07 — Spoolman multicolor: `multi_color_hexes` only; `color_hex` never set for multicolor

Spoolman rejects a filament PATCH that sets both `color_hex` and `multi_color_hexes`
with a 422: "Cannot specify both color_hex and multi_color_hexes".  The correct Spoolman
multicolor representation is `multi_color_hexes` (comma-separated hex values, first = primary
for gradient) + `multi_color_direction`, with `color_hex` **unset**.

`fdb_multicolor_to_sm` in `backend/app/core/color.py` was returning `color_hex` in both
multicolor branches — for coextruded it synthesised the primary from the first secondary,
and for gradient it repeated the primary.  This caused 422 errors on real filaments (SM #7,
#147).

**Fix:** both multicolor branches now return `color_hex: None` and put ALL colors in
`multi_color_hexes` (coextruded: all secondaries; gradient: primary + secondaries).
Single-color branch is unchanged.  The engine `_sync_multicolor` FDB→SM write omits
`color_hex` from the PATCH payload when None.  `opt_to_spoolman_fields` (opentag_match.py)
already guards on None, so the OpenTag cleanup path also no longer sends `color_hex` for
multicolor.

## 2026-06-07 — Color-name tokens split on non-alphanumeric; multicolor descriptor noise dropped

`_color_name_tokens` in `backend/app/core/opentag_match.py` previously split the
color-name residual on whitespace only, so "Green/Purple" became the single token
`green/purple` and never matched the OPT space-separated "Green Purple".  All of a
brand's dual-color variants therefore tied at the same confidence (intersection
contained only the descriptor words `dual`, `color`, etc.).

**Fix 1 — tokenize on `[^a-z0-9]+`** so `/`, `-`, `&`, and other punctuation all act
as token separators (e.g. "Green/Purple" → `{"green","purple"}`).

**Fix 2 — drop a small explicit NOISE set** (`color`, `dual`, `tri`, `multi`,
`multicolor`, `tricolor`, `dualcolor`) that are structural descriptors appearing on
every dual/tri candidate and contribute nothing to discriminating the correct color combo.
After both fixes, SM "Matte PLA Dual Color Green/Purple" → `{"green","purple"}` and OPT
"PLA Matte Dual Color Green Purple" → `{"green","purple"}` → Jaccard 1.0, while
"Blue Pink" → `{"blue","pink"}` → Jaccard 0.0 → correct combo ranked first.

`_name_similarity` is unchanged; the empty-set → 0.5 neutral path still applies when
stripping leaves no color tokens (e.g. a name containing only descriptor words).

## 2026-06-07 — OpenTag cleanup lets the user pick from best + top-5 alternates; each candidate carries its own field comparison

The matches endpoint now returns a structured `candidates` list on every `OpenTagFilamentMatch`.
`candidates[0]` is the best match; `candidates[1..5]` are the top alternates in descending
score order.  Each `OpenTagCandidate` carries `opt_uuid`, `opt_slug`, `opt_brand`, `opt_name`,
`opt_color_hex`, `confidence`, `multicolor_mismatch`, and a full `fields: list[OpenTagFieldRow]`
built by running `_build_field_rows(sm_fil, opt_to_spoolman_fields(candidate, tag_map))` for
that specific candidate — so every candidate shows a real Spoolman-vs-OpenTag comparison for
its own values.

`find_best_match` in `opentag_match.py` now also returns `alternate_scores: list[float]`
alongside `alternates`, so the endpoint can pair each alternate material with its score and
build a full `OpenTagCandidate` (including a non-zero confidence) rather than defaulting to 0.

On the frontend, a per-filament dropdown appears in the card header whenever `candidates.length > 1`.
Each option is labeled `"{brand} · {name} (confidence%)"` with a color swatch.  Selecting an
alternate resets that filament's field decisions to the new candidate's default OPT values and
records the selection index.  The `handleApply` and `ConfirmStep` paths both read the selected
candidate's `opt_slug`/`opt_uuid` for the identity write, and use the selected candidate's
`fields` as the authoritative field list.  The "ignore match" control is unchanged (per filament,
ignores regardless of which candidate is selected).  Exact-UUID matches return a single candidate
at confidence 1.0 (no dropdown).

## 2026-06-07 — OpenTag secondary_colors recovered from raw tarball; multicolor mismatch flag

### Problem

FDB's `/api/openprinttag` feed leaves `secondaryColors` **empty on all 12,501 records**.
FDB's parser reads flat `secondary_color_0..4` keys, but the OpenPrintTag YAML schema stores
them in a `secondary_colors` ARRAY — so the bridge can't bring in gradient/multicolor colors.
Result: the OpenTag cleanup can't produce `multi_color_hexes` / `multi_color_direction` updates
for any filament even when OpenTag has the data.

### Fix: recover from raw tarball

New module `backend/app/core/opentag_secondary.py` — `fetch_secondary_colors(http?)`:
- Fetches `https://api.github.com/repos/OpenPrintTag/openprinttag-database/tarball/main`
  (gzipped tar, ~3 MB) with `httpx.Timeout(120.0)`.
- Untars in-memory (`tarfile` over `io.BytesIO`); for each `data/materials/**/*.yaml`,
  `yaml.safe_load`s it and extracts `secondary_colors[].color_rgba` → hex strings
  (`_rgba_to_hex('#000000ff') → '000000'`, strip `#`, drop trailing alpha, uppercase).
- Returns `{ uuid: [hexes], slug: [hexes], ... }` (both keyed for uuid-primary / slug-fallback).
- Errors (network, bad tar, YAML) → `{}` and a logged warning (non-fatal).

`load_opentag_dataset` in `opentag_cache.py` now calls `fetch_secondary_colors()` after every
FDB fetch, then merges by uuid (fallback: slug) for materials whose `secondaryColors` is empty.
The merged dataset is written to `opentag_cache.json` so the merge happens once per refresh,
not per request. If the raw fetch returns `{}`, the FDB feed is used unchanged (graceful degrade).

`PyYAML>=6.0` added to `backend/requirements.txt`.

### Colors now flow as cleanup updates

With `secondaryColors` populated, `opt_to_spoolman_fields`'s `if secondary:` branch runs —
delegates to `fdb_multicolor_to_sm` for gradient/coextruded materials, producing `color_hex` +
`multi_color_hexes` + `multi_color_direction` together (no Spoolman 422). The empty-secondaries
guard from the previous session stays as a fallback for any record still lacking secondaries.

### multicolor_mismatch flag

`OpenTagFilamentMatch` gains `multicolor_mismatch: bool` (default `False`):
- `True` when SM filament is multicolor (`sm_color_profile != "single"`) AND the matched OPT
  entry is single-color (no `secondaryColors` AND no arrangement tag).
- Also `True` on no-match rows when SM is multicolor (brand has no compatible multicolor OPT entry).
- Frontend (`OpenTagCleanup.tsx`): small amber "multicolor mismatch" badge on the filament card
  header when `multicolor_mismatch` is true.

## 2026-06-07 — OpenTag review: exact-UUID match, existing identity display, reviewable name

### Exact-UUID match (confidence 1.0)

`GET /api/openprinttag/matches` now builds a `by_uuid` index over the full materials list.
Before fuzzy scoring, if the SM filament's `extra.openprinttag_uuid` (decoded) exists in
that index, the corresponding material is returned directly with `confidence = 1.0`,
bypassing brand-filter and all fuzzy scoring. This covers SM filaments that were already
tagged by a prior cleanup run — they are immediately re-identified without re-scoring.

### Review shows existing OpenTag identity

`_build_field_rows` in `backend/app/api/opentag.py` now **includes** `extra.openprinttag_slug`
and `extra.openprinttag_uuid` as review rows (previously excluded, commit 48c05d6 was reversed).
Each row's `spoolman_value` is the SM filament's current decoded extra value — blank/`None` when
unset, showing the existing identity when already set.  The removal of the frontend's explicit
slug/uuid push in `OpenTagCleanup.tsx` (`~274-275`) prevents duplicates: the rows are now
the single source, and `_build_sm_patch` deduplicates via the `if key not in native["extra"]`
guard for anything that also comes through `decision.openprinttag_slug/uuid`.

### Reviewable name field (default OpenTag)

`opt_to_spoolman_fields` in `backend/app/core/opentag_match.py` now includes
`result["name"] = opt.get("name")` — the OpenTag material name is offered as the
Spoolman filament name.  The `name` row flows through the generic field-rows path: default =
OpenTag value, keep-mine toggle supported, `_build_sm_patch` writes it as a native Spoolman
field when not kept.  `spoolman_value` for the `name` row is set to `sm_fil.name` by
`_current_spoolman_value` (native attribute lookup).

## 2026-06-07 — filamentdb_material_tags stored as CSV string in Spoolman text extra field

Spoolman's text extra fields accept a JSON-quoted string value (e.g. `"17,28"` on the wire
becomes `'"17,28"'` in the PATCH body). They do NOT accept a JSON array (`"[17]"` → 400 Bad
Request). The bridge was passing a Python list through `encode_extra_value` which does
`json.dumps(value)` — so `[17]` became `"[17]"`, a JSON array, causing every PATCH to
`filamentdb_material_tags` to 400. The field has therefore never persisted any values.

**Fix:**

- `serialize_material_tags(ids)` in `backend/app/core/material_tags.py` converts an iterable
  of ints to a sorted comma-separated string (`"17"`, `"17,28"`, `""`).
- `parse_material_tags(raw)` in the same module parses back to `list[int]`, tolerating the new
  CSV string form, an empty string, the legacy JSON-array string (`"[17]"`), and a real Python
  list (all backward-compatible).
- The two write sites now call `encode_extra_value(serialize_material_tags(ids))`:
  - `opt_to_spoolman_fields` in `backend/app/core/opentag_match.py` (OpenTag apply path)
  - FDB→SM finish-tag write in `backend/app/core/engine.py` `_sync_finish_tags`
- The read site (`_sm_finish_ids_from_filament` in engine.py) now uses `parse_material_tags`
  after `decode_extra_value` instead of the old `isinstance(decoded, list)` branch.
- The apply error handler in `backend/app/api/opentag.py` now logs `exc.response.text` when
  available so future 4xx errors show Spoolman's detail message.

The snapshot signature (`",".join(str(i) for i in sorted(ids))`) was already CSV — now the
stored value matches it, so the round-trip is stable (no flapping).

## 2026-06-07 — OpenTag apply no longer writes multi_color_direction when secondaryColors is empty

`opt_to_spoolman_fields` in `backend/app/core/opentag_match.py` previously set
`multi_color_direction` ("coaxial" or "longitudinal") in the branch where an arrangement
tag is present but `secondaryColors` is empty (always the case in FDB's denormalized feed).
Spoolman rejects a PATCH with `multi_color_direction` but no `multi_color_hexes` → 422,
causing the entire filament apply to fail for multicolor filaments (e.g. SM #86 Silk Gradient).

The fix removes the `multi_color_direction` assignment from that branch entirely.  When OpenTag
carries no `secondaryColors`, neither `multi_color_direction` nor `multi_color_hexes` is
emitted — Spoolman's existing arrangement data is left untouched.  The `if secondary:` branch
(which sets both fields together when real secondary colors are present) is unchanged.

This is correct because the SM filament already has the right multicolor hexes + direction
(that's how the match was found in the first place via `sm_color_profile` reading
`sm.multi_color_direction`).  The apply has nothing new to add for those fields when OPT
provides no secondary colors.

## 2026-06-07 — OpenTag apply self-creates required extra fields; ensure_extra_fields is per-section resilient

### Root cause

The OpenTag apply endpoint (`POST /api/openprinttag/apply`) was 422-ing on every filament
because the Spoolman filament extra fields `openprinttag_slug` and `openprinttag_uuid` were
never created. `ensure_extra_fields` creates these at startup but is wrapped in a swallow-all
`try/except` in `main.py`, so a transient/partial failure at startup left them missing
silently — with no log entry visible to the user.

### Fix 1: apply self-heals (`backend/app/api/opentag.py`)

`opentag_apply` now calls `await sm.ensure_extra_fields()` once before the decision loop.
`ensure_extra_fields` is idempotent (only POSTs fields not yet defined), so calling it on
every apply is safe and cheap. A failure in this call returns a clear 502
`opentag_field_setup_failed` error with a descriptive message, rather than letting the first
PATCH attempt fail with a 422 for each filament.

### Fix 2: per-section isolation in ensure_extra_fields (`backend/app/services/spoolman.py`)

The spool field section and the filament field section now each wrap their
`get_field_definitions(...)` call (previously un-try'd) in independent try/except blocks.
A failure in the spool section logs a warning and continues to the filament section; a
failure in the filament section does not block the spool section. This means a transient
Spoolman error against one entity type cannot silently leave the other type's fields
uncreated.

The per-field creation `except` was broadened from `httpx.HTTPStatusError` only to
`(httpx.HTTPStatusError, httpx.RequestError)`, so transient connection/timeout errors
on individual field POSTs are logged and skipped rather than bubbling up and aborting
the remaining fields.

### Fix 3: main.py docstring tidied

The startup comment (step 4) previously said "the three cross-ref fields". It now
accurately lists the full set: cross-ref spool fields +
`filamentdb_material_tags` / `openprinttag_slug` / `openprinttag_uuid`.

All field creation stays via the Spoolman REST API (`POST /api/v1/field/{entity}/{key}`),
never touching the DB directly.

## 2026-06-06 — OpenTag matcher: arrangement-from-tags, polymer-family gate, finish-aware scoring

Three systematic failures found via a real-data audit (bridge matcher run over live Spoolman DB
+ the 12,501-record OpenTag cache) were fixed in `backend/app/core/opentag_match.py` and
`backend/app/api/opentag.py`:

### 1. Arrangement derived from tags, not secondaryColors (critical)

FDB's denormalized OpenTag feed leaves `secondaryColors` **empty on all 12,501 records**.
Arrangement is only present in the string `tags` array (e.g. `"coextruded"`,
`"gradual_color_change"`).  `opt_color_profile` previously checked `secondaryColors` first
— when empty it returned `"single"`, so every multicolor SM filament got 0 candidates.

**Fix:** `opt_color_profile` now checks the `tags`/`optTags` arrangement FIRST (via
`arrangement_from_tags`), regardless of `secondaryColors`.  Only falls back to
`secondaryColors` for the `multi_unknown` case (secondaries present, no arrangement tag).

**Apply-side guard:** `opt_to_spoolman_fields` no longer writes `multi_color_hexes` when
the OPT entry has empty `secondaryColors` (which is always in the real feed) — Spoolman's
existing multicolor hex data is preserved.  `multi_color_direction` is still set from the
arrangement tag.

### 2. Polymer-family hard gate in the matches endpoint

`material_family(material)` normalises a material string to a base polymer family:
`PLA/PLA+` → `pla`; `PETG` → `petg`; `ASA` → `asa`; `ABS` → `abs`; `PC` → `pc`;
`TPU/TPE` → `tpu`; `PA/Nylon/PA-CF/PA6` → `pa`; `PVA` → `pva`; unknown → passthrough.
Strips finish words first so `"PLA Silk"` → `"pla"`.

In `GET /api/openprinttag/matches`, after the brand + color-profile filters, candidates are
further filtered to the same `material_family` as the SM filament.  An empty/unknown SM
material bypasses the gate (all candidates scored).  This kills PC→ASA, ASA→PETG.
PLA↔PLA+ remain matchable (same family).

### 3. Finish-aware scoring with finish-word stripping

**Rebalanced weights** (old → new):

| Component | Old | New |
|---|---|---|
| Type/material (exact) | 0.25 | 0.20 |
| Vendor/brand (exact) | 0.25 | 0.20 |
| Color-name similarity | 0.35 | 0.30 |
| Finish component | +0.05 reward only | +0.075 neutral / +0.15 reward / −0.10/−0.15 penalty |
| Color hex proximity | 0.10 | 0.10 |

**Finish-word stripping:** `_color_name_tokens` already removed finish words; these were
already included in the `tag_map` iteration (silk, matte, transparent, etc.).  This means
`"Transparent Orange"` → `{orange}` and `"Silk Bronze"` → `{bronze}` BEFORE the name-
similarity comparison — finish mismatch is handled entirely by the finish component.

**`_finish_score(sm_ids, opt_ids)` returns:**
- both empty (solid vs solid): `+0.075` (neutral)
- perfect finish match: `+0.15`
- partial overlap: `jaccard × 0.15`
- one solid, one finished (clear mismatch): `−0.15`
- both finished but disjoint (matte vs silk): `−0.10`

This drops a wrong-finish candidate (Transparent Orange, Silk White) below the correct
plain/solid one when the SM filament has no finish tags.

Verified by 562 passing tests including 24 new tests covering: tag-based profile with empty
secondaryColors; coaxial SM matches coextruded OPT (the real-data path); apply-side guard
preserves multi_color_hexes; polymer-family gate (PC≠ASA, ASA≠PETG, PLA=PLA+); finish
scoring (solid vs silk, solid vs transparent, matte vs silk, finish-word stripping).

## 2026-06-06 — OpenTag matching hard-filters by color profile; apply sets multi_color_direction + handles empty primary

The OpenTag matcher was arrangement-blind — a multicolor Spoolman filament (coaxial/longitudinal)
could wrongly match a solid OpenTag product, or the wrong arrangement.

**Phase 1 — Color-profile pre-filter in `GET /api/openprinttag/matches`:**

Three pure helpers added to `backend/app/core/opentag_match.py`:

- `sm_color_profile(sm)` — `single` (no `multi_color_hexes`), `coextruded` (`coaxial`),
  `gradient` (`longitudinal`), or `multi_unknown` (hexes present, direction absent).
- `opt_color_profile(opt, tag_map)` — `single` (no `secondaryColors`), `coextruded` (optTag 29
  or string tag "coextruded"), `gradient` (optTag 28 or "gradual_color_change"), `multi_unknown`.
  Reads both the integer `optTags` array and the string `tags` array for arrangement detection,
  reusing `color.arrangement_from_tags`.
- `profiles_compatible(a, b)` — hard rules: `single↔single` only; `coextruded↔coextruded` only;
  `gradient↔gradient` only; `multi_unknown` (either side) matches any multicolor but never `single`.

In `opentag_matches` (`backend/app/api/opentag.py`), after the brand pre-filter, candidates are
further filtered to those whose profile is compatible with the SM filament's profile. `find_best_match`
remains pure — receives the already-filtered list.

**Phase 2 — Complete `opt_to_spoolman_fields` multicolor mapping:**

- When the matched OPT entry is coextruded (optTag 29) or gradient (optTag 28), delegates to
  `fdb_multicolor_to_sm(opt_color, secondary, opt_tags_int)` so the OPT→SM mapping is consistent
  with the FDB→SM sync direction. This sets `multi_color_direction` (`"coaxial"` or `"longitudinal"`),
  `multi_color_hexes`, and `color_hex`.
- Empty primary `color` (common for coextruded) is handled automatically: `fdb_multicolor_to_sm`
  synthesises `color_hex` from the first secondary for coextruded filaments.
- For `multi_unknown` (secondaries present, no arrangement tag), the hexes are preserved in
  `multi_color_hexes` but no direction is set.
- Single-color OPT entries are unchanged (primary `color` → `color_hex`, no multi fields).

Verified by 538 passing tests including 44 new tests for profile detection (both sides, incl.
empty-primary dual-color), profile compatibility rules, `opt_to_spoolman_fields` multicolor output,
and endpoint integration (coaxial SM matches only coextruded; single never matches multicolor;
longitudinal matches gradient).

## 2026-06-06 — OpenTag matcher: color NAME is the key within-brand/material discriminator; hex demoted

`score_candidate` in `backend/app/core/opentag_match.py` previously ignored the color
name entirely — it scored brand (0.30) + material (0.40) + hex-proximity (0.20) +
finish (0.10). Within a brand+material, all color variants received the same 0.70
baseline and the tiebreaker was RGB distance, which is unreliable (e.g. CB6D30 "Orange"
is closer in RGB to AF784D "Copper" than to some true-orange hex).

**Fix:** rebalanced weights and added a color-name similarity component:

| Component | Old weight | New weight |
|---|---|---|
| material/type (exact) | 0.40 | 0.25 |
| vendor/brand (exact) | 0.30 | 0.25 |
| **color-name similarity** | — | **0.35** |
| color hex proximity | 0.20 | 0.10 |
| finish tag overlap | 0.10 | 0.05 |

Two new pure helpers:
- `_color_name_tokens(name, vendor, material, tag_map)` — strips vendor tokens, material
  tokens (base + full), and finish keywords from the name string; returns the remaining
  lowercase token set (the isolatable color name).
- `_name_similarity(sm_tokens, opt_tokens)` — Jaccard similarity with a containment bonus
  for single-token colors; returns 0.5 (neutral) when either side has no color token so
  naming gaps don't nuke an otherwise-good match; returns 0.0 when both sides have tokens
  and they're disjoint.

With these changes, "Orange / Hatchbox / PETG" scores the OpenTag Orange candidate strictly
higher than the Copper candidate of the same brand+material, even when the Orange hex is
RGB-closer to Copper. Verified by `test_orange_vs_copper_bug_orange_scores_higher` and
`test_find_best_match_returns_orange_not_copper`.

## 2026-06-06 — OpenTag cleanup: instant dataset banner + staged fetch/match progress

Added `GET /api/openprinttag/status` — a side-effect-free endpoint that reads local
cache metadata via `opentag_cache.get_cache_metadata()` without calling FDB. Returns
`{ exists, fetched_at, count, stale, max_age_hours }`. New `OpenTagCacheStatus` Pydantic
model; matching `OpenTagCacheStatus` TypeScript interface + `getOpenTagStatus` client fn.

The `OpenTagCleanup.tsx` page now has two-phase startup:

1. **Instant banner** — `getOpenTagStatus()` fires on mount and populates the dataset
   banner (count + relative age + stale chip) immediately, before any slow work starts.
   While the status call is in-flight the banner reads "Checking dataset cache…".

2. **Staged loading messages** — once the status resolves, a `runLoad(skipRefresh)` call
   begins. A spinner + `statusMsg` string is shown prominently during work:
   - Cold run (cache missing or stale): "Fetching the OpenTag dataset from Filament
     DB… (first load downloads ≈11k records — up to a minute)" while `POST /refresh`
     runs, then "Matching your Spoolman filaments…" while `GET /matches` runs.
   - Warm run (cache fresh): skips the fetch stage entirely, shows only
     "Matching your Spoolman filaments…".
   - Refresh button always forces cold run.

The existing review → confirm → apply flow is unchanged.

## 2026-06-06 — OpenTag matching pre-filters candidates by normalized brand for performance; progress logged

`GET /api/openprinttag/matches` was hanging because `find_best_match` scored all ~11k
OpenTag materials for every Spoolman filament — hundreds × 11k scoring ops per request.

**Fix:** in `opentag_matches` (`backend/app/api/opentag.py`), a `materials_by_brand`
index is built once from the full dataset, keyed by `normalize_vendor(m.get("brandName"))`.
For each SM filament, only its brand's candidates are passed to `find_best_match`.
A SM vendor with no matching OpenTag brand gets an empty candidates list → no-match (correct;
brand is a strong signal). `find_best_match` is unchanged in signature and behavior.

**Progress logging added** before and after the scoring loop:
- Before: `opentag matches: scoring N filaments against M materials across B brands`
- After: `opentag matches: X matched, Y no-match`

These were absent, which is why the user saw "no log entries" during the long hang.

## 2026-06-06 — FDB /api/openprinttag returns OPTDatabase wrapper; bridge extracts .materials; cache self-heals malformed data

### Root cause

`GET /api/openprinttag` on Filament DB returns an **OPTDatabase wrapper object**, not a bare
list of OPTMaterial dicts:

```json
{ "brands": [...], "materials": [...], "cachedAt": "...", "totalFFF": N, "totalSLA": N }
```

The bridge's `get_openprinttag()` was doing `return resp.json()` and treating the whole dict
as the materials list. Downstream code iterated the 5 dict *keys* (strings `"brands"`,
`"materials"`, etc.) — hence "saved 5 materials" in the log and
`AttributeError: 'str' object has no attribute 'get'` in `score_candidate` when a key string
was passed as an OPTMaterial.

### Fix

**`FilamentDBClient.get_openprinttag()`** now extracts the nested `materials` array:

```python
data = resp.json()
if isinstance(data, dict):
    return data.get("materials", []) or []
return data  # already a list (defensive)
```

`brandName` is already present on each OPTMaterial dict, so the separate `brands` list is
not needed by the bridge.

**`load_opentag_dataset()` in `opentag_cache.py`** self-heals a malformed cache: if the
stored `materials` list is not a non-empty list of dicts (e.g. contains string keys from the
old bug), the loader treats the cache as stale and re-fetches — no manual Refresh required.

**`find_best_match()` in `opentag_match.py`** defensively filters out any non-dict candidate
before scoring, so a single bad entry cannot 500 the whole matches endpoint.

## 2026-06-06 — OpenTag cleanup API renamed to /openprinttag/*; 120 s fetch timeout; structured fetch errors

### Route rename: /opentag/* → /openprinttag/*

The bridge's OpenTag cleanup routes were at `/api/opentag/matches`, `/api/opentag/refresh`,
and `/api/opentag/apply`. The token `opentag` (without "print") collides with the "Qubit
OpenTag" web-analytics product, which EasyList and uBlock filter lists block at the network
layer. Chrome reported `net::ERR_BLOCKED_BY_CLIENT` for every request, while the bridge log
showed nothing (the requests never reached the backend).

The routes are now at `/api/openprinttag/matches|refresh|apply`. The string `openprinttag`
does not contain the blocked `opentag` substring, and FDB already exposes
`/api/openprinttag` through the same ad blocker without issues. The client-side SPA route
`/opentag-cleanup` is unchanged (browser navigation is not a network request and isn't
blocked). Function and type names in the codebase are unchanged.

### 120 s per-request timeout for get_openprinttag()

`FilamentDBClient.get_openprinttag()` now passes `timeout=httpx.Timeout(120.0)` to the
HTTP GET. The global client timeout stays at 15 s for all other endpoints. The cold fetch
downloads FDB's ~3 MB gzip tarball and extracts it on the server, which takes 20–60 s.

### Structured fetch errors (504/502) with logger.error

`opentag_refresh` and `opentag_matches` now catch `httpx.TimeoutException`,
`httpx.HTTPStatusError`, and `httpx.RequestError` from `load_opentag_dataset` and raise
`api_error(...)` responses with stable codes:

- `httpx.TimeoutException` → 504 `opentag_fetch_timeout`
- FDB 404 `HTTPStatusError` → 502 `opentag_unavailable` (FDB too old)
- other HTTP/request errors → 502 `opentag_fetch_failed`

Each failure branch calls `logger.error(...)`. The frontend renders the backend `message`
field in a visible error box, and shows a descriptive loading message during the long cold
fetch (noting 20–60 s is expected).

## 2026-06-06 — OpenTag cleanup tool + scoped FDB settings-bag exception

### OpenTag cleanup tool

New standalone tool (`/opentag-cleanup` page, `GET /api/openprinttag/matches`,
`POST /api/openprinttag/refresh`, `POST /api/openprinttag/apply`) that:

1. Fetches the OpenPrintTag dataset from FDB's `GET /api/openprinttag`, caches it
   locally in `DATA_DIR/opentag_cache.json` with a configurable 24-hour staleness
   threshold (`OPENTAG_CACHE_MAX_AGE_HOURS`).
2. Scores each Spoolman filament against the cached OPTMaterial list using a
   weighted scoring function (type/material 40%, vendor/brand 30%, color proximity
   20%, finish-tag overlap 10%).
3. Shows a per-field review UI with Spoolman value vs OpenTag value (default OpenTag,
   editable, per-field "keep mine"). "Ignore match" dismisses a whole filament.
4. Shows a full confirm screen listing every write before any action is taken.
5. On Apply, PATCHes each Spoolman filament with only the non-keep_mine fields
   (including `openprinttag_slug` + `openprinttag_uuid` as extra fields), then calls
   `merge_filament_settings()` on the linked FDB filament to carry the two identity
   keys into FDB's `settings{}` bag.

Reuses `#1`'s finish-tag map (`filamentdb_material_tags`) and `material_tags.py`.
Does not change any existing sync or wizard behavior.

### Scoped FDB settings{} bag exception (Phase 5)

**Rule relaxed:** CLAUDE.md prohibits touching FDB's `settings{}` bag (slicer passthrough).

**Exception granted (2026-06-06):** `FilamentDBClient.merge_filament_settings()` in
`backend/app/services/filamentdb.py` is the only approved path. It ONLY merges the
two keys `openprinttag_slug` and `openprinttag_uuid` — never reads, removes, or
modifies any other key.

**Implementation:** read-modify-write — fetch current filament detail, read existing
`settings` bag (default empty dict), check if both keys are already equal (idempotent,
no HTTP PUT if equal), merge only those two keys, write back. The `_STRIP_BEFORE_PUT`
stripping is bypassed for this path because `settings` is in that strip set — the
merged `settings` bag is re-attached to the PUT payload after stripping.

**Wire points:**
- `backend/app/api/opentag.py` → `POST /api/openprinttag/apply` calls it after writing
  each SM filament when `fdb_filament_id` is provided.
- `backend/app/core/engine.py` → `_sync_opentag_identity()` is called once per live
  sync cycle (not dry-run) to ensure any SM filament with slug/uuid extras has them
  mirrored into FDB. Non-fatal per pair.
- `backend/app/api/wizard.py` → Pass 2.7 in `_execute_spoolman_to_fdb` pushes slug/uuid
  from newly-created FDB filaments' SM counterparts on wizard execute.

**Not wired for FDB→SM direction** (FDB's settings bag is not read by the bridge for
other purposes; the SM side is the authoritative source for these identity keys).

## 2026-06-06 — Name-collision detection is vendor-aware

`_compute_name_collisions` in `backend/app/api/wizard.py` now keys both the
`existing` FDB filament map and the `incoming` create-plan map on
`(normalize_vendor(vendor), normalize_name(name))` instead of `normalize_name(name)`
alone.

**Why non-obvious:** the original name-only key caused false-positive collision flags
when two vendors happen to sell a filament with the same name (e.g. "Beige" from
ELEGOO and "Beige" from Bambu Lab). The bridge's own matcher already keys on
vendor+name+color, so the collision check should be at least as precise. Same
vendor+name still flags correctly (genuine potential duplicate); different vendors
with the same name do not.

## 2026-06-06 — Conflict cards carry snapshot-derived identity

Each conflict card now shows a compact identity header (color swatch, label,
material chip, hex chip, SM spool id, FDB filament id, FDB spool id) so the
user can identify the record at a glance without following deep-link icons.

**Where the data comes from:** `_conflict_identity(db, c)` in
`backend/app/api/conflicts.py` loads the Spoolman snapshot for the conflicting
entity — the **spool** snapshot (`source="spoolman", entity_type="spool"`) for
spool conflicts, the **filament** snapshot for filament conflicts — and extracts
`filament.name`, `filament.vendor.name`, `filament.color_hex`, `filament.material`
(spool path) or the top-level equivalents (filament path). The composed label is
`"{vendor} {name}".strip()` falling back to `"SM #{spoolman_id}"` when the
snapshot is absent.

**Read-only enrichment only:** the `_conflict_identity` helper performs no writes
and does not participate in conflict detection or resolution logic. The five new
fields (`label`, `vendor`, `name`, `color_hex`, `material`) are nullable on
`ConflictResponse` — existing consumers that don't need them are unaffected.

## 2026-06-06 — FDB create_spool returns the filament doc; extract spool _id by label match

`POST /api/filaments/:id/spools` returns the **filament document** (with its embedded
`spools[]` array), not the new spool subdocument. The bridge was reading `raw["_id"]`
directly, which is the **filament** id — so every `SpoolMapping.filamentdb_spool_id`
was set to the filament id instead of the spool id. This caused every per-spool lookup
(deletion detection, weight sync, field sync) to fail with "Record deleted upstream"
because the filament id was never found in `fdb_spool_index` (keyed by real spool ids).

**Fix:** `extract_created_spool_id(resp, *, label_field, label_value)` in
`backend/app/services/filamentdb.py` finds the just-created spool inside `resp["spools"]`
by matching `label_field` (the `FILAMENTDB_SPOOLMAN_ID_FIELD`, default `"label"`) against
`label_value` (the Spoolman spool id stored on create). Falls back to the last entry in
`spools[]` if no label match; handles a bare-spool response defensively. Applied at both
call sites: `wizard.py` (`_execute_spoolman_to_fdb`) and `engine.py`
(`_handle_new_sm_spool`).

**Pre-fix mappings are corrupt** — every `spool_mappings` row written before this fix has
`filamentdb_spool_id == filamentdb_filament_id`. The user should clear these rows and
re-run the wizard import to produce correct mappings. Any open `__record_deleted__`
deletion conflicts for those spools are stale artifacts and can be dismissed.

## 2026-06-06 — Stale cross-ref no longer skips spool creation; spoolWeight from resolved tare

### Bug A: stale filamentdb_spool_id cross-ref blocked spool creation

When Filament DB is wiped or a spool is deleted, Spoolman spools still carry the old
`filamentdb_spool_id` extra pointing at a now-deleted FDB spool. Previously, the planner
(`_plan_spoolman_to_fdb` Phase C) and the ongoing engine new-spool detection both treated
any non-empty cross-ref as "already linked" and skipped creating the FDB spool — leaving
filaments with no spools after re-import.

**Fix:** a cross-ref only causes a skip when the referenced FDB spool id actually exists
in the current FDB dataset (`existing_fdb_spool_ids` in the planner; `fdb_spool_index` in
the engine). A stale xref falls through to create, and the write-back overwrites the stale
id automatically. A live SpoolMapping row still always skips (unchanged).

The `plan_dry_run` step-4 filter is updated to also remove engine-generated `new_spool`
conflicts for cross-ref orphans (previously they were not cleaned up in the stale-xref path
because the stale-xref check in the engine used to skip before reaching
`_handle_new_sm_spool`).

### Bug B: FDB filament spoolWeight was written from raw sm.spool_weight (often NULL)

The wizard computes a resolved tare per filament (user override → spool spool_weight →
filament spool_weight → 200 g default) and uses it to compute spool `totalWeight`. But
`_fdb_filament_payload_from_sm` wrote `spoolWeight` from raw `sm.spool_weight`, which is
NULL for many Spoolman filaments. Result: FDB got the correct `totalWeight` but
`spoolWeight=null`, so the % bar math was wrong (gross - 0 = full rather than gross - tare).

**Fix:** thread the resolved tare into `_fdb_filament_payload_from_sm` via a new
`resolved_tare` parameter. Phase A of `_plan_spoolman_to_fdb` computes
`_resolve_filament_tare(sm_fil, fil_spools, tare_by_sm_spool)` (same resolution chain as
the Phase C gross computation) and passes it through. `spoolWeight` is now always set to
the resolved tare (guaranteed ≥ 200 g), not the raw Spoolman field.

## 2026-06-06 — Import now sets FDB netFilamentWeight from Spoolman filament weight

When the wizard imports a Spoolman filament into Filament DB, `_fdb_filament_payload_from_sm`
now sets `netFilamentWeight` (the full spool capacity) on the create payload so that Filament
DB can compute and render the spool fill % bar immediately after import.

Resolution order: use `SpoolmanFilament.weight` when set; fall back to the `initial_weight`
of the first spool (sorted by id, mirroring `resolve_effective_cost`) that has a non-null
value; omit the field entirely if neither is available (Filament DB continues to show "—",
no fabricated value). `spoolWeight`, `totalWeight`, `planned_gross`, and all weight math are
unchanged — this is a purely additive create-payload field.

Because FDB already logs Spoolman weight decrements as usage entries (FR-9), the % bar will
track downward automatically as usage accrues once `netFilamentWeight` is set — no
ongoing-sync change is needed. Backfilling `netFilamentWeight` on filaments imported before
this fix is a possible follow-up, not implemented here.

## 2026-06-06 — Dry-run preview lists in-sync pairs as "matched — no updates"

Spool pairs that are already in sync produced no preview entry, making the dry-run
invisible for synced data. Each such pair now emits a `{"action": "matched", "reason":
"in sync — no updates", ...}` entry in the dry-run preview — spool-pair scoped (weight
and field-mapping passes only; filament-level multicolor/cost passes emit their own
separate rows and are unaffected).

**Dry-run only.** The `_preview_len_before_pair` sentinel tracks whether any preview
entry was appended during the weight + field passes for the pair iteration. If the
preview length is unchanged at the end of the pair block and `dry_run=True`, a single
"matched" entry is appended. Real (non-dry-run) cycles never emit it.

**First-baseline pairs are excluded.** Pairs without prior snapshots fall into the
existing `skip` (baseline) path and `continue` before reaching the matched block —
correct behavior preserved.

**Frontend:** `SyncPreviewEntry.action` gains `"matched"`. The Dashboard dry-run
summary includes a muted "Matched — no updates (N)" section with a "Show/Hide" toggle
(default shown), and the counts bar shows a "Matched: N" figure when N > 0.

## 2026-06-06 — New-spool direction enforced; wizard writes new keys; old source-of-truth removed

### New-spool creation is now a real enforced direction (default two_way)

`new_spool_sync_direction` replaces the dead `new_spool_source_of_truth` config key.
The old key was read from the DB but never checked — all new-spool detection paths
always ran bidirectionally. The new key is enforced in `core/engine.py`'s new-spool
detection block:

- `two_way` (default) → both `_handle_new_sm_spool` (SM→FDB) and `_handle_new_fdb_spool`
  (FDB→SM) run — identical to pre-deploy behavior.
- `spoolman_to_filamentdb` → only SM→FDB creation runs (new SM spools get an FDB spool;
  new FDB spools are NOT created in Spoolman).
- `filamentdb_to_spoolman` → only FDB→SM creation runs.

The startup migration (`_migrate_sync_config`) sets `two_way` if the key is absent,
preserving current behavior for existing deployments.

### Wizard direction step now configures ongoing sync

The `POST /api/wizard/direction` handler previously wrote old `*_source_of_truth` keys
which the engine no longer read — so onboarding configuration had no effect on
ongoing sync. The handler now translates the wizard's binary per-category choice
(`spoolman` / `filamentdb`) into the new direction + conflict policy keys:

- `weight_source_of_truth=spoolman` → `weight_sync_direction=spoolman_to_filamentdb` +
  `weight_conflict_policy=manual`
- `weight_source_of_truth=filamentdb` → `weight_sync_direction=filamentdb_to_spoolman` +
  `weight_conflict_policy=manual`
- Same mapping for `material_properties_*` and `new_spool_*` categories.

The wizard's frontend payload (`WizardDirectionRequest`) is unchanged — the UI still
presents the binary per-category choice. A richer wizard UI with full
direction+policy selection is a later nicety.

### Old source-of-truth fields removed from the config surface

`weight_source_of_truth`, `material_properties_source_of_truth`, and
`new_spool_source_of_truth` are no longer present in `ConfigResponse`,
`ConfigUpdateRequest`, or the frontend `types.ts` / `Settings.tsx`. The keys remain
readable in `_DEFAULTS` and `_migrate_sync_config` for backward-compatible migration
reads only.

The Settings UI "New spools" row is replaced with a `DirectionSelect` (Two-way /
Spoolman → Filament DB / Filament DB → Spoolman) bound to `new_spool_sync_direction`.

## 2026-06-06 — Per-category sync direction + conflict policy (two-axis model)

### Replaced "source of truth" with two independent per-category axes

Each data category (`weight`, `material_properties`) now has two settings:

- **Write direction**: `two_way` | `spoolman_to_filamentdb` | `filamentdb_to_spoolman`
- **Conflict policy**: `manual` | `spoolman_wins` | `filamentdb_wins` | `newest_wins`
  (weight only for `newest_wins`; material_properties rejects it with HTTP 422)

### Two-way: lone change always propagates

In `two_way` mode, a lone change on either side always propagates to the other — no SoT
gating. The conflict policy is consulted ONLY when both sides changed since the last
snapshot. This enables true bidirectional sync without forcing a manual conflict review for
every single change.

### One-way modes never queue conflicts

In `spoolman_to_filamentdb` or `filamentdb_to_spoolman` mode, the locked destination's
drift is a NOOP — never queued as a conflict. The source side wins on the next cycle that
sources a change. This preserves backward-compatible behavior for users who relied on the
old SoT (one-way) semantics.

### newest_wins is weight-only

Spoolman exposes no per-filament modification timestamp (only `last_used`/`registered` at
the spool level). It cannot be used honestly for material_properties conflicts. The API
rejects `material_properties_conflict_policy=newest_wins` with HTTP 422. For weight,
`newest_wins` is anchored to the snapshot's `captured_at` (bridge last-sync time) — a
side's timestamp is only counted if it is strictly after that anchor, preventing stale
clocks from winning. When both timestamps are missing, equal, or indeterminate, the policy
falls back to `QUEUE_CONFLICT`. This is best-effort and clock-skew-prone; frequent syncing
is the reliable mitigation.

### Multicolor now follows material_properties direction

Before this change, multicolor/color sync was hardcoded two-way. After this change it
follows `material_properties_sync_direction`. The migration default is
`filamentdb_to_spoolman` (mirroring the old `material_properties_source_of_truth=filamentdb`
default). This is a deliberate, documented behavior change: multicolor changes that
previously propagated from Spoolman automatically will be NOOP under the default one-way
config until the user opts into two-way.

### Conflict dedup added

Without a dedup check, a both-changed pair would re-queue a new conflict row every sync
cycle (because the snapshot is not advanced on conflict). A new `_has_open_conflict` helper
checks for an existing OPEN conflict with the same `(entity_type, field_name, spoolman_id,
fdb_spool_id)` tuple before queuing. If one exists, the new conflict is skipped.

### Migration preserves pre-deploy behavior

`_migrate_sync_config(db)` in `app/main.py` runs once at startup after `seed_defaults`.
It reads the old `weight_source_of_truth` and `material_properties_source_of_truth` keys
and maps them to one-way direction + manual policy (behavior-identical). The function is
idempotent — if the new keys already exist it skips them. Fresh installs get the same
defaults as today's.

## 2026-06-06 — Filament cost sync: spool-price-first, filament fallback; matprop SoT; snapshot merge

### Effective Spoolman cost resolved spool-first

`resolve_effective_cost(filament_price, spools)` in `backend/app/core/fields.py` returns the
price of the first spool (by id) with a non-null `price`; if no spool has a price, it falls
back to the filament-level `price`. This is the canonical cost value used throughout the
bridge — in the wizard import and in ongoing sync.

### Wizard import: FDB filament create payload includes cost

`_fdb_filament_payload_from_sm` in `backend/app/core/planner.py` now accepts an
`effective_cost` keyword argument. `_plan_spoolman_to_fdb` resolves the cost for each
`create` action using the active (non-archived) spools for that filament and passes it to
the payload builder. The resulting `cost` field appears in the FDB filament create payload
and is visible in the Phase-4 planned-writes preview.

### FDB→SM write-back targets the Spoolman FILAMENT price

Because FDB cost is filament-level, the FDB→SM write direction updates
`spoolman.update_filament(sm_fil_id, {"price": fdb_cost_now})` — the Spoolman **filament**
price. Per-spool Spoolman prices are the user's actual purchase prices and must never be
overwritten by a filament-level value.

### Cost follows material_properties_source_of_truth

`_sync_cost` in `backend/app/core/engine.py` iterates `filament_mappings` each cycle,
computes effective SM cost (spool-first) and FDB cost, then:
- Neither side has cost → skip
- First sight (both snapshots have no `_cost` key) → store baseline, no write
- One side changed and SoT favours that side → apply the write
- Both changed and disagree → queue a `cost` conflict (never auto-resolve)
- Both changed into agreement → refresh baseline

SoT semantics mirror `resolve_field_map` / `_apply_field_changes` exactly — no new behavior.

### Filament snapshots now merge keys (_mc_sig + _cost coexist)

The multicolor and cost passes both store filament-level snapshots. Previously `_sync_multicolor`'s
inner `_store()` called `_upsert_snapshot` directly with only `{"_mc_sig": ...}`, replacing
the entire row on each write. A new `_merge_snapshot` helper (reads existing data, updates
the one key, writes back) is used by **both** passes. This means `_mc_sig` and `_cost`
coexist in the shared filament snapshot row and neither pass clobbers the other's key.
Regression test: `test_cost_and_multicolor_snapshots_coexist`.

## 2026-06-05 — Tare excluded from variant-prop conflicts; conflict badges name specific fields

### Tare (`spool_weight`) excluded from `sm_prop_conflicts`

`sm_prop_conflicts` in `backend/app/core/matcher.py` no longer checks `spool_weight`.
Previously, two filaments that were identical in every material property but had different
empty-reel tare values (e.g. ELEGOO PLA Beige tare 160 g vs Black tare 154 g) would yield
a non-empty conflict list, which set `suggest_exclude=True` on the non-master member and
pushed it to the ungrouped/standalone section — preventing auto-grouping.

This was self-contradictory: the wizard already unifies tare per variant group (the banner
"All variants in this group will use the master's empty-reel tare" makes this explicit) and
tare is a physical/estimated reel weight, not a property that distinguishes a product line.
Removing `spool_weight` from the check means a tare-only difference no longer flags a member
for exclusion or standalone suggestion.

The fix propagates to all three call sites automatically (both `wizard.py` at ~375 and ~535,
and `planner.py` at ~188). The `CONFLICT_FIELD_TO_CANONICAL` map and `computeConflicts`
mirror function in `StepVariances.tsx` were updated in parallel. Regression tests added:
`test_sm_prop_conflicts_tare_only_diff_returns_empty`, `test_sm_prop_conflicts_real_diff_still_detected`,
and `test_wizard_variances_tare_only_diff_does_not_suggest_exclude`.

### Conflict badges name specific differing fields

The standalone badge in `StepVariances.tsx` previously read "suggested standalone (prop conflict)"
for any filament with `suggest_exclude=True`. It now reads:

> suggested standalone — {field labels} differ

where the field labels are derived from a `CONFLICT_FIELD_LABELS` map that translates raw SM
field names to friendly display names (e.g. `settings_extruder_temp` → "nozzle temp",
`material` → "material/type"). Labels are deduped and joined with ", ". Example:
"suggested standalone — diameter, nozzle temp differ". If `conflicts` is empty but
`suggest_exclude` is true (shouldn't occur post-fix, but as a fallback), it reads
"suggested standalone".

The same `CONFLICT_FIELD_LABELS` map is used in the in-group "Conflicts with master:" box
so field names read consistently across both locations.

## 2026-06-05 — Reconcile canonical-key contract + editable master temps

### Canonical-key contract between frontend and backend

`ReconciledField.field` in the frontend MUST use canonical keys matching
`_RECONCILE_FIELD_MAP` in `backend/app/api/wizard.py`. The frontend constant
`CONFLICT_FIELD_TO_CANONICAL` (in `StepVariances.tsx`) maps raw Spoolman field
names to their canonical equivalents:

| Raw SM / conflict field | Canonical key |
|---|---|
| `material` | `type` |
| `settings_extruder_temp` | `nozzle_temp` |
| `settings_bed_temp` | `bed_temp` |
| `density`, `diameter`, `spool_weight` | (same) |

The state map `reconcileByGroup[groupIdx]` is also keyed by canonical names.
Raw field names are used only for display labels. `material_type` is excluded
from the reconcile set entirely — it is derived/display-only and not in the
canonical map; its mismatch chip is still shown but no reconcile option is offered.

**Why this was broken:** the original code emitted raw SM names
(`settings_extruder_temp`, `material`) as `ReconciledField.field`. The backend
`_RECONCILE_FIELD_MAP` checks `if canonical_key not in _RECONCILE_FIELD_MAP: continue`,
so temp and type reconcile decisions were silently dropped. Only `density`, `diameter`,
and `spool_weight` happened to have the same raw and canonical names, so those worked.

A regression test `test_wizard_execute_reconcile_nozzle_temp_overlays_fdb_and_patches_spoolman`
was added to `backend/tests/test_api.py` to lock this contract.

### Editable master temps

On the master member row in `StepVariances.tsx` (SM direction, auto groups only),
the read-only temps chip is replaced with two compact number inputs (nozzle and bed),
styled within the same orange chip. Editing upserts `nozzle_temp` / `bed_temp`
canonical reconcile entries with `source: 'manual'` into `reconcileByGroup[groupIdx]`,
which then flow to the FDB parent payload (via `temperatures.nozzle` / `temperatures.bed`)
and the Spoolman write-back PATCH (`settings_extruder_temp` / `settings_bed_temp`) via
the existing `handleSave` → POST → execute path — no backend changes.

Clearing an input removes the override key from the map (no null persisted).
Non-master rows retain the read-only chip.

Possible follow-ups (not in scope): editable type/diameter/density on master row;
editable temps on standalone rows; live conflict-badge update when master temp is overridden.

## 2026-06-05 — Variances type/diameter/temps display

Every variant-group member row and standalone filament row in `StepVariances.tsx` now
always renders three property chips: **type** (blue, from `filData.material` — SM's native
`material` field), **diameter** (gray, `{N} mm` or `⌀ —` when null), and **temps**
(orange, `{nozzle}° / {bed}°`, shown only when at least one temp is non-null).

The old `material_type`-only chip (green, prefixed "FDB:") was the primary type indicator
but it's only populated for `link` decisions — null in fresh imports. The fix: primary type
= `material` (always present from SM); `material_type` is now a secondary amber mismatch
chip shown only when it differs from `material`. All three fields (`diameter`,
`settings_extruder_temp`, `settings_bed_temp`) were already populated by the
`GET /wizard/variances` backend endpoint via the SM filament list fetch — no backend change
was needed.

## 2026-06-05 — Conflicts page: client-side type filter

`classifyConflict` derives a `ConflictType` bucket purely from `field_name` and `spoolman_id`
fields already present on `ConflictResponse` — no API or schema changes. `new_spool` direction
is disambiguated by `spoolman_id != null` (Spoolman-only spool) vs null (FDB-only spool), per
the engine's existing behavior. The filter bar appears only when two or more types are present,
so a single-type list is never cluttered with an unnecessary UI element.

## 2026-06-05 — Upstream deletion detection → conflict queue

### Design

When a mapped record disappears from an upstream fetch, the bridge now queues a
`Conflict` row with `field_name = "__record_deleted__"` (sentinel constant
`DELETION_FIELD` in `app/models/conflict.py`) instead of logging a skip/error and
continuing. This keeps the "conflicts are never auto-resolved" hard rule and gives the
user an explicit UI action to take.

**Archived vs deleted (Spoolman side):** `sm_all_ids` (set of all spool ids returned
by Spoolman, including archived ones) is built each cycle. An id absent from
`sm_all_ids` is gone entirely → deletion conflict. An id present but not in the
active (non-archived) dict → skip as before. This preserves the existing archived-spool
skip behavior.

**Dedup:** `_queue_deletion_conflict` checks for an existing open conflict with the
same sentinel `field_name`, `spoolman_id`, and `filamentdb_spool_id` before inserting.
This prevents a new conflict row from accumulating every cycle until the user resolves.

**Value encoding:** the surviving side's value carries
`{"exists": true, "deleted_side": "<spoolman|filamentdb>"}`. The deleted side is
`null`. The frontend keys off `deleted_side` to render a human-readable explanation
instead of a raw value diff.

**Dashboard / Synced Records:** `build_mapping_rows` already flips a row to
`status="conflict"` when any open conflict references its spool ids. No changes to
`mappings.py` were needed — queueing the deletion conflict is sufficient.

### Resolution cleanup

When `resolve_conflict` or `bulk_resolve` marks a `DELETION_FIELD` conflict as
resolved, `_cleanup_orphaned_mapping` deletes the `SpoolMapping` row and both `Snapshot`
rows for that pair from bridge-local SQLite. This is bridge-local state only — no
upstream writes. The mapping disappears from Synced Records and the Dashboard count
corrects itself on the next page load.

**Upstream re-create is Phase 2.** If the user wants to restore the deleted upstream
record and re-link it, that is a separate future workflow. The conflict router never
writes to Spoolman or Filament DB (existing hard rule; see "resolve = record, apply
next cycle" philosophy above).

## 2026-06-04 — variant_line_keywords user setting + Standalone "Move to existing group"

### variant_line_keywords — user-configurable finish/line keyword lexicon

`matcher.py`'s `extract_finish_line` and `sm_variant_cluster_key` now accept an optional
`keywords: list[str]` parameter. When provided, each keyword is matched whole-word
case-insensitively (`\bkeyword\b`); the first match becomes the finish token. When `keywords`
is `None`, the original `_FINISH_PATTERNS` regex lexicon is used (backward-compatible fallback
for tests and any non-wizard caller).

**Resolution:** env var `VARIANT_LINE_KEYWORDS` (comma-separated) seeds the default with the
same tokens as `_FINISH_PATTERNS` plus `rapid`. At runtime, `get_config_value(db, "variant_line_keywords", settings.variant_line_keywords)` lets the UI override the env default without a restart. `wizard_variances` and `wizard_variants` both call `_resolve_variant_keywords(db)` and pass the result to every `sm_variant_cluster_key` / `extract_finish_line` call. The matcher functions remain pure (no DB import). `ConfigResponse` / `ConfigUpdateRequest` expose `variant_line_keywords`; `Settings.tsx` adds an editor text field.

### Standalone rows gain "Move to existing group"

The Standalone section in `StepVariances.tsx` previously only offered multi-select "Group as
variants" (new group only). Each standalone row now also shows a **"Move to…"** dropdown
(via `movingStandaloneId` state + `moveFromStandalone` / `standaloneTargetOptions` helpers)
listing all existing non-empty auto/extra groups plus "New group". After a move the row
disappears from Standalone and joins the target group; `handleSave` is driven by membership
state so no special handling is needed.

## 2026-06-04 — Wizard per-member actions + finish-line auto-split (Part A/B)

Extends the 2026-06-04 D1–D4 redesign. Source of truth for D1–D4 remains that entry;
this section records the Part A (per-member actions) and Part B (finish-line split) additions.

### Part A — Per-member labeled actions replace the checkbox

`StepVariances.tsx` grouped-filament rows now show three labeled buttons per member instead of
a bare always-checked disabled checkbox:

- **Move to…** — dropdown listing all other auto/extra groups and "New group"; removes from source,
  adds to target (with master promotion if the moving member was master).
- **Standalone** — removes from group; member appears in the standalone list with its own tare.
- **Ignore** — calls `POST /wizard/matches/{sm_filament_id}/skip`, which sets `action: "skip"` in
  `wizard_match_decisions`, then removes from the group. Uses `_included_sm_ids()` as the single gate,
  so the change flows to variances/weights/preview/execute for free. No second exclusion set.

The `Ignore` button is also present on standalone filament rows and extra-group (manually grouped) rows.
Master radio button is unchanged. Groups dissolved to 0 members are hidden (no empty card).

`ignoreErr` is surfaced as a red text line above the Save/Back row.

### Part B — Finish-line auto-split extends D1 grouping key to 3-tuple

**Q1 resolved.** `sm_variant_cluster_key` in `matcher.py` now returns a 3-tuple
`(normalize_vendor, normalize_name(material), finish)` where `finish` is the output of
`extract_finish_line(name, material)`.

`extract_finish_line` uses a word-boundary-aware regex lexicon (ordered most-specific first):
`glow-in-the-dark / GITD`, `carbon fiber / CF`, `rainbow / multicolor`, `high-speed / HS`,
`metallic`, `marble`, `wood`, `matte`, `satin`, `silk`. Returns `""` for standard/unrecognized.

Effect: `ELEGOO PLA Red` and `ELEGOO PLA Silk Red` now get different cluster keys (`""` vs `"silk"`),
so they land in separate variant groups — preventing Silk from inheriting PLA print settings via the
parent. D2's `suggest_exclude` signal survives as a second-line safeguard for finish tokens not in the
lexicon. The lexicon is a closed set; user-driven move/standalone actions are the escape hatch.

FDB parent map keying in `wizard_variances` updated to 3-tuple `(vendor_norm, material_norm, finish_norm)`
so existing Silk FDB parents match Silk SM groups (not standard PLA parents).

`VariancesGroupRow` gains `finish: str | None` (shown in the group header as a violet pill).
Frontend `VariancesGroupRow` interface updated to match.

## 2026-06-04 — Wizard variant-resolution redesign: D1 grouping key, D2 suggest-exclude, D3 FDB-parent attach, D4 empty-spool toggle

Implements `docs/wizard-redesign.md` decisions D1–D4 in full. Source of truth is that spec;
this entry records the settled contract. See the "Part A/B" entry above for the Q1 resolution
(finish-line split) and per-member action redesign that followed.

### D1 — Grouping key is `(vendor, material)` — drop base_name (initial pass)

`sm_variant_cluster_key` in `matcher.py` returned a 2-tuple `(normalize_vendor, normalize_name(material))`.
The old 3-tuple included `base_name = strip_color_and_words(name, color_hex)`, which caused filaments
whose name IS a color word (e.g. "Brown", "Beige") to produce different base_names and never cluster.

All callers updated to unpack 2-tuples; extended to 3-tuples by Part B above.
Group display `base_name` is now `normalize_name("{vendor} {material}")` — consistent across all paths.

**Q1 simplification (initial pass, since superseded):** finish/line tokens (PLA Matte / Silk / PLA-CF)
were NOT parsed out in this pass. Q1 is now resolved by the Part B finish-line split above.

### D2 — Per-member exclude, pre-flagged by `sm_prop_conflicts`

`VariancesFilament` gains `suggest_exclude: bool = False`. Set to `True` for non-master members where
`sm_prop_conflicts(master, member)` returns ≥1 mismatch (density, extruder_temp, bed_temp, etc.).
Conflicts are still surfaced, never auto-resolved. The flag is a *hint* only — the user remains in
control via the membership checkboxes in `StepVariances.tsx`.

Pre-suggested-excluded members start unchecked in the initial `groupMembership` state (frontend).

Standalones also gain checkbox select + "Group as variants" action: select 2+ standalone filaments
and click the button to create an editable extra group (pick master via radio). This is the only
path to manually group filaments that the auto-clustering didn't detect.

### D3 — Load FDB state; resolve each incoming color as Attach / Create

`wizard_variances` now also loads `filamentdb.get_filaments()` and builds a
`(vendor_norm, material_norm) → FilamentRef` map of existing FDB parent lines (filaments with
`hasVariants=True` or with children pointing to them via `parentId`).

`VariancesGroupRow` gains `existing_fdb_parent: FilamentRef | None`. When set, the frontend offers
a per-group choice: **Attach to existing FDB parent** (default) vs **Create new parent**.

`SMVariantDecision` gains `existing_fdb_parent_id: str | None = None`. Semantics:
- **None** → SM-keyed master-promote (unchanged behavior: master becomes the FDB parent).
- **set** → ALL members (including the "master") are created with `parentId = existing_fdb_parent_id`;
  no new parent is created. The existing FDB parent is **never modified or deleted** — only `parentId`
  is written on newly-created variants.

New helper `_build_attach_parent_for_sm(decisions) → {sm_id: existing_fdb_parent_id}` in `wizard.py`.
In `_execute_spoolman_to_fdb` Pass 1: attach-group masters get `parentId` injected into the create
payload; `master_map[master_sm_id]` is set to `existing_fdb_parent_id` (not the newly-created FDB id),
so Pass 2 variants correctly receive `parentId = existing_fdb_parent_id`.

### D4 — "Include empty / depleted spools" toggle

Config key `wizard_include_empty_spools` (bool, default `False`) persisted via `get/set_config_value`.
"Empty" is defined as `not archived AND remaining_weight == 0.0` — same predicate as `_compute_empty_active`.

Applied in three places:
1. `wizard_variances` `spool_ids_per_filament`: empty spools omitted from `spool_ids` when toggle=False.
2. `_plan_spoolman_to_fdb` Phase C: `include_empty_spools: bool = True` parameter; when False, skips
   spool plan items for zero-weight spools. The filament/color plan item is still created (toggle only
   controls the *inventory record*, not the color definition).
3. `wizard_preview` / `wizard_execute` both pass the toggle to the planner.

New `GET /wizard/direction` endpoint returns `{import_direction, include_empty_spools}`.
`POST /wizard/direction` extended with `include_empty_spools: bool | None` (optional, backward-compatible).

Frontend Step 2 (`Step2Direction.tsx`): "Include empty / depleted spools" checkbox, default unchecked.
`StepNPreview.tsx` `EmptyActiveEntry` panel: badge turns blue (informational) when toggle=False with copy
"skipped by setting"; amber when toggle=True ("will be imported").

## 2026-06-03 — CI workflows, registry, and main branch protection

### Registry / repo slug

GitHub remote is `crzykidd/filament-bridge`; container registry is
`ghcr.io/crzykidd/filament-bridge`. Image authentication uses `GITHUB_TOKEN` with
`packages: write` permission — no additional secrets needed.

### Migration check command

`alembic env.py` reads the DB path from `settings.data_dir` (env var `DATA_DIR`), NOT from
a `DATABASE_URL` env var. The two required env vars `FILAMENTDB_URL`/`SPOOLMAN_URL` must
also be set for `Settings()` to initialise, even though their values are irrelevant for
schema-only migration checks. Correct CI command:

```
FILAMENTDB_URL=http://localhost SPOOLMAN_URL=http://localhost DATA_DIR=/tmp/alembic-check \
  alembic upgrade head
```

### CI check names (used in branch protection)

Workflow `CI` → jobs named exactly as follows (branch protection contexts =
`CI / <job-name>`):

| Context | Trigger |
|---|---|
| `CI / Lint` | push + PR |
| `CI / Config validation` | push + PR |
| `CI / Migration check` | push + PR |
| `CI / Compose validation` | push + PR |
| `CI / Image build` | PR only |

`CI / Test` (pytest) is a bonus job — NOT a required check.

### main branch protection

Applied via `gh api` (see command below). Required: PR + all 5 checks green, no direct
pushes, no force-pushes. `required_approving_review_count: 0` (single-developer repo).
`strict: false` (branch need not be current with main before merge).

**Verify check names after first CI run.** GitHub registers check contexts only after
they've executed. If the names above don't match what appears in
Settings → Branches → main protection, update them there or re-run the command below.

```bash
gh api -X PUT /repos/crzykidd/filament-bridge/branches/main/protection \
  --input - << 'EOF'
{
  "required_status_checks": {
    "strict": false,
    "contexts": [
      "CI / Lint",
      "CI / Config validation",
      "CI / Migration check",
      "CI / Compose validation",
      "CI / Image build"
    ]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 0,
    "dismiss_stale_reviews": false
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF
```

## 2026-06-03 — Wizard: merged Variances step, downstream filtering, master-tare rule

Two coupled problems fixed together:

1. **Downstream steps now filter to the chosen-to-sync set.** An SM filament is *included*
   iff its `wizard_match_decisions` action is `link` or `create`. `skip` and no-decision are
   excluded everywhere: `wizard_weights`, `wizard_variants`, and the new `wizard_variances`
   endpoint. Helper `_included_sm_ids(db)` is the single definition; all three endpoints call
   it. Before this change, the Weights and Variants steps re-fetched and showed the entire
   Spoolman library, forcing users to deal with filaments they had already decided to skip.

2. **Weights + Variants merged into one "Variances" step.** Wizard order is now 6 steps:
   Connectivity → Direction → Matches → **Variances** → Preview → Execute.
   `Step4Weights.tsx` and `Step5Variants.tsx` are deleted; `StepVariances.tsx` replaces them.
   The FDB import direction reuses the old `GET /wizard/variants` and `GET /wizard/weights`
   endpoints directly from within `FDBVariancesStep`; no backend changes for that direction.

3. **Tare is per filament/group, not per spool.** Filament DB stores one `spoolWeight` per
   filament (not per spool). The new `GET /wizard/variances` endpoint returns one tare per
   SM filament (from the filament-level `spool_weight`; default 200 g). The UI shows one
   editable tare input per variant group (the master's) and one per standalone filament. On
   save, the frontend expands these to per-spool `WizardTareOverride[]` entries covering every
   spool of every filament in each group. The execute contract (`WizardExecuteRequest.
   tare_overrides`) is unchanged — tare overrides still ride in the request body.

4. **Master-tare-wins with a visible warning.** All variants in a group share the master's
   tare. A banner on the UI makes this explicit: "All variants in this group will use the
   master's empty-reel tare: N g." This is the only correct model given FDB's single-tare
   per-filament constraint.

5. **Editable variant membership; clusters are hints only.** The user can un-check a member
   to remove it from a group (it becomes standalone with its own tare), or click "+ Add
   member" to pull any other included-but-ungrouped SM filament into the group. The saved
   `SMVariantDecision[]` (in `wizard_sm_variant_decisions`) is authoritative; the API's
   suggested groupings are hints only. Groups reduced to master-only are treated as flat
   (no `SMVariantDecision` entry emitted).

6. **Conflicts recompute live.** `VariancesFilament` carries comparable props
   (material/density/spool_weight/temps). When the user changes the master radio button,
   the frontend recomputes conflicts via `computeConflicts()` — a pure function that
   mirrors `sm_prop_conflicts` from `backend/app/core/matcher.py` — without a round-trip.

7. **Step3Matches row separator fix.** Group-body `divide-gray-50` changed to
   `divide-gray-100` so member row dividers are visible on white backgrounds.

## 2026-06-01 — De-adopted the vexp-context-engine standard (sunset homelab-wide)

vexp is being removed across the homelab; the `vexp-context-engine` standard is deprecated and
rewritten as a removal guide at **v3.0.0**. filament-bridge was its first adopter (fully wired at
v2.1.0); all wiring is stripped here:

- Deleted the `.claude/hooks/vexp-guard.sh` PreToolUse guard hook.
- Removed the `mcp__vexp__*` entries from `permissions.allow` and the `hooks` block from
  `.claude/settings.json`. **The `sandbox` block (repo-sandbox-permissions, repo-wide) and the
  `Read/Edit/Write(**)` allows live in the same file and were preserved intact** — JSON re-validated.
- Removed the "Context search (operational rules)" section from `CLAUDE.md`.
- Dropped the vexp `.gitignore` block; untracked `.vexpignore`, `.vexp/.gitignore`,
  `.vexp/.gitattributes`; deleted the `.vexp/` runtime dir and the gitignored auto-generated
  `.claude/CLAUDE.md`.
- Flipped the `standards.md` vexp row to de-adopted/sunset (v3.0.0 guide) and dropped the vexp
  reference from the `repo-sandbox-permissions` row note.

**Not done from this repo:** host daemon teardown is the Ansible `devworkstation` role's opt-in
`--tags vexp_teardown`. A still-running daemon transiently recreated the (now-untracked) `.vexp/`
runtime dir during this change; it clears when the daemon is stopped by the teardown. No
`CHANGELOG.md` exists yet (pending first release), so this record stands in for the changelog note.

## 2026-06-01 — Match-review v2: one unified table, Group-By Status default

Replaced the four fixed status tables (v1) with a single unified table that has a toolbar for Group By, Sort By + direction, global search, Status filter, and per-column filter inputs (Name, Material). Collapsible groups with tri-state checkboxes and right-aligned aggregates.

1. **Group-By Status is the default**, reproducing the v1 four-section feel (Matched / Ambiguous / Unmatched-SM / Unmatched-FDB) while allowing the user to pivot to Material or Brand grouping. Status also appears as a column and filter.
2. **No backend changes.** All fields needed by the new columns (name, vendor, material, color, confidence, vendorDedup, candidates) were already present on `FilamentRef` / `MatchPairRow` / `AmbiguousRow`. Spool-count aggregates would require fetching spools in `wizard_matches`; omitted as optional per the prompt.
3. **All v1 decision logic preserved unchanged**: tri-state checkboxes, Rescan + decision pruning, `saved_decisions` rehydration, ambiguous candidate picker, `bulkSet` per-status action mapping. `unmatched_fdb` rows remain informational (no checkboxes) regardless of grouping.
4. **Status breakdown pills** appear in group headers when Group-By is Material or Brand, showing counts per status within that group. Amber ⚠ badge flags groups with unresolved ambiguous rows.

## 2026-05-31 — FDB location semantics: locationId (ObjectId reference), pre-creation required

Verified against the live FDB instance while implementing spool location seeding (SM→FDB wizard
execute path).

1. **FDB spools use `locationId`, not a bare `location` string.** `POST /api/filaments/:id/spools`
   with `"location": "name"` silently ignores the key. The correct field is `"locationId"` holding
   a 24-char MongoDB ObjectId referencing the `locations` collection. The bridge schema
   `FDBSpoolDetail.location` was wrong and has been corrected to `locationId`.

2. **Locations must be pre-created via `POST /api/locations`.** FDB does not auto-create a location
   from a name. The wizard seed fetches `GET /api/locations` once per run to build a `name→id`
   cache, then creates missing locations on-demand per spool. A `create_location` failure is
   per-record (that spool fails; the run continues) — consistent with the existing NFR-4
   per-record isolation pattern.

3. **Scope of this change.** Only the SM→FDB initial-seed path (wizard execute). Ongoing-sync
   location updates (engine diff) and the FDB→SM direction are out of scope — follow-up work.

## 2026-05-31 — Match-review redesign: grouped tables, checkboxes, rescan

FR-3/FR-4 match-review step rebuilt from a flat list into four independent grouped/sortable tables.

1. **Status is the top-level grouping — four tables stay separate.** Match status (Matched /
   Ambiguous / Unmatched-SM / Unmatched-FDB) dictates what action is even possible per row,
   so it's the outer split. Subgrouping (Material or Brand/vendor) happens *inside* each table
   via a single shared dimension control.

2. **Checkbox → action mapping (per table).**
   - Matched: checked = `link` (to the auto-matched FDB filament), unchecked = `skip`.
   - Unmatched-SM: checked = `create`, unchecked = `skip`. Both default to the "include" action.
   - Ambiguous: row checkbox only active once a candidate is chosen via the Link picker;
     toggles between the chosen `link` (preserving `filamentdb_id`) and `skip`. The `filamentdb_id`
     is preserved in the decision even when `action="skip"` so re-checking restores the link
     without re-picking.
   - Unmatched-FDB: informational only — groupable/sortable, no checkboxes.
   - Subgroup-header checkbox is tri-state (checked/unchecked/indeterminate); table-level checkbox
     covers all rows in the section.

3. **Rescan keeps choices.** `GET /wizard/matches` now accepts a `db` dependency and returns
   `saved_decisions: list[MatchDecision]` (echoing `wizard_match_decisions` from BridgeConfig).
   On first load the UI hydrates `decisions` state from `saved_decisions`. On rescan
   (`reload()`), existing choices are kept and pruned to the SM ids still present in the new
   response — keyed by `spoolman_filament_id`.

4. **`material` added to `FilamentRef`.** `_sm_ref` sets `material=sm.material` (Spoolman
   `SpoolmanFilament.material`); `_fdb_ref` sets `material=fdb.type` (FDB `FDBFilament.type`).
   Used for the Material subgroup dimension in the UI.

## 2026-05-31 — Wizard preview (FR-4 foundation): reconcile-flag keys + read-only UI step

`GET /api/wizard/preview` reuses the same `_plan_spoolman_to_fdb` planner as
`wizard_execute` (so preview ≡ execute), then derives four reconcile-flag lists from the
plan via pure helpers in `backend/app/api/wizard.py`. The non-obvious grouping keys:

1. **`name_collision`** (`_compute_name_collisions`): key is `normalize_name(payload.name)`
   over the *create* plan items. A group flags `vs_existing` when the normalized name is
   also a key in the existing-FDB map, and `intra_batch` when ≥2 incoming creates share the
   key. One entry per distinct normalized name (not per filament) — so the count is groups,
   while the backlog's "43" counted the colliding *filaments*.
2. **`empty_active`** (`_compute_empty_active`): straight over `sm_spools` —
   `not archived AND (remaining_weight or 0) == 0`. Independent of the plan.
3. **`default_tare`** (`_compute_default_tare`): create spool items where
   `tare_source == "default"` (planner substituted the 200 g default because no
   `spool_weight` was set); reports the planned gross and the default used.
4. **`variant_group`** (`_compute_variant_groups`): key is
   `(normalize_vendor(vendor), _strip_color(name, color_hex), normalize_name(material))`
   over create items, groups of ≥2. Fills FR-6's gap (which only groups *matched* records
   and returns nothing on an empty FDB) for fresh imports. No `parentId` is written — the
   proposed groups are surfaced for the future decision UI only.

**UI:** new read-only `frontend/src/pages/Wizard/StepNPreview.tsx`, wired into the stepper
*before* Execute. Shows the plan summary + flag counts and four collapsible flag sections,
with a non-blocking notice that flagged items need decisions in a later release. No mutating
controls.

**E2E (clean FDB, reseeded `spoolman-livedata.db`, 175 fil / 223 spools):** preview returned
`empty_active=63`, `default_tare=79` (exact backlog match), `name_collision=17` groups /
60 colliding filaments, `variant_group=1`; FDB stayed empty and Spoolman unchanged (no
cross-ref extras written) — confirming the read-only guarantee.

## 2026-05-30 — Dashboard dry-run: SyncPreviewEntry shape and skip coverage

Decisions made while implementing FR-14 per-category detail (created/updated/conflicts/skipped).

1. **Typed `SyncPreviewEntry` Pydantic model** (option b). The WIP wizard-preview changes in
   `schemas/api.py` are purely additive (new model classes at the bottom); `CycleResultResponse`
   was untouched, so adding `SyncPreviewEntry` + changing the one-line `preview` type was safe
   and additive. Frontend gets full TypeScript inference with no extra effort.

2. **Preview entry shape** — all 11 fields present on every entry, with `None` for N/A.
   Consistent shape avoids runtime `?.` chains in the frontend and makes the Pydantic model
   validator simple. `old`/`new` on weight conflicts hold SM `remaining_weight` and FDB
   `totalWeight` respectively (labeled in `reason`).

3. **`sm_skipped_fields` set in `_apply_field_changes`** — introduced to prevent the SM→FDB
   dry-run second-pass from emitting duplicate update entries for inherited-skipped fields.
   Local to the function, dry-run only. The live-sync path is unchanged.

4. **Skip entries for archived and first-baseline paths** were previously silent (incremented
   `result.skipped` but produced no preview entry). Now each emits a `skip` entry with a
   `reason`, so the "Skipped (n)" section in the UI is actually populated.

5. **Label degradation rule** — `_preview_label()` builds "VENDOR NAME COLOR (SM #id) / FDB name"
   when all data is present; degrades gracefully to just FDB name, just SM id, or "unknown" if
   parts are missing (e.g. archived spool where sm_spool object is None).

## 2026-05-30 — Multicolor filament mapping (Spoolman ↔ Filament DB)

Spoolman models multicolor (`multi_color_hexes` CSV + `multi_color_direction` =
`coaxial`/`longitudinal`; 29/175 of the live set). Filament DB has **no multicolor
support** — one `color` hex + a `colorName` string. Note: FDB's UI "Notes" field is
actually `settings.filament_notes` inside the **off-limits slicer-passthrough bag**, so we
never write there. Decisions:

1. **Spoolman is authoritative for color; the bridge's own DB is canonical.** FDB can't hold
   multicolor and has no structured extension field, so nothing is stored in FDB beyond a
   display projection. No data loss — Spoolman + the bridge snapshot retain the full set.
2. **FDB gets primary `color_hex` → `color`, plus a human projection in `colorName`** (a
   real top-level field, never `notes`/`settings`). Format is a config choice
   (`multicolor_colorname_format`): `name` (default — fuzzy nearest-named-color over a
   standard palette, e.g. `"Yellow/Green (coextruded)"`) or `hex`
   (`"cdde1b/68cc16 (coextruded)"`). Type vocabulary is friendly: `coaxial`→**coextruded**,
   `longitudinal`→**gradient**.
3. **`colorName` is a bridge-managed derived field** — recomputed from Spoolman data + the
   current format on each apply for multicolor filaments, so changing the format setting and
   re-running sync rewrites it (the differ won't see a Spoolman-side change). The fuzzy name
   match is approximate by design; switching to `hex` is the escape hatch.
4. **Protect multicolor on write-back.** New setting `protect_multicolor_color_in_spoolman`
   (default **true**): ongoing FDB→Spoolman sync never writes color fields for filaments
   Spoolman marks multicolor, regardless of the material-properties source-of-truth, so
   `multi_color_hexes`/`direction`/`color_hex` can't be flattened. Disabling it carries a UI
   loss-warning.
5. **Forward path:** an upstream feature request was filed for native FDB multicolor. If it
   lands, replace the `colorName` projection with a real field mapping and push correctly —
   no data-model rework, since Spoolman + the bridge already hold the truth.

## 2026-05-31 — Structured multicolor sync supersedes the colorName projection

Filament DB **v1.33.0** (closing [hyiger/filament-db#477](https://github.com/hyiger/filament-db/issues/477))
shipped native structured multicolor, so the "forward path" above has landed. The interim
`colorName`-text projection (decisions 2–4 of the 2026-05-30 entry) is **removed entirely**
— pre-first-release, so no migration. Replacement decisions:

1. **Structured field mapping, both directions.** FDB `color` (nullable) + `secondaryColors[]`
   + arrangement in `optTags` (tag **29 = coextruded**, **28 = gradient**, coextruded wins)
   ↔ Spoolman `color_hex` + `multi_color_hexes` + `multi_color_direction`. Helpers live in
   `core/color.py` (`sm_multicolor_to_fdb`, `fdb_multicolor_to_sm`). coaxial → FDB `color`=null
   & all hexes in `secondaryColors`; longitudinal → `color`=primary, rest secondary. optTag
   writes preserve unrelated tags.
2. **Bidirectional, mirroring the field-diff model.** Multicolor is a filament-level property,
   so `engine._sync_multicolor` runs over filament mappings with a system-agnostic
   `multicolor_signature` stored as filament-level snapshots. One-sided change → directional
   write; both sides changed & disagree → queued conflict (`field_name="multicolor"`), never
   auto-resolved. SoT is not consulted for one-sided changes (consistent with field sync).
   The generic `color` field-map sync is skipped for multicolor filaments (the structured path
   owns it), which replaces the old `protect_multicolor` setting.
3. **Version-gated.** FDB has no version endpoint; we read `GET /api/openapi` → `info.version`
   (`FilamentDBClient.get_version`, cached, refreshed per health probe). `core/version.py`
   gates on `>= 1.33.0` (`MULTICOLOR_MIN_FDB`). On older FDB, multicolor sync is skipped and
   `/api/health` (+ sync status) surface an "upgrade to 1.33.0" warning; single-color `color`
   sync is unaffected.
4. **Removed config** — `multicolor_colorname_format` and `protect_multicolor_color_in_spoolman`
   (defaults, schemas, API, and Settings UI controls) are gone.

## 2026-05-30 — Phase 5 sync fixes (PATCH, weight precision, material default, wizard gating)

Four concrete bugs exposed by the first live end-to-end run (223 Spoolman spools):

1. **`PATCH /api/v1/spool/{id}`, not `PUT`.** Spoolman v0.23.1 returns 405 on `PUT` for
   spool updates; `PATCH` returns 200. This affected both the wizard cross-ref write-back
   and the FR-10 ongoing weight sync (both go through `update_spool`). `CLAUDE.md`
   endpoint list corrected accordingly.

2. **Configurable weight precision (default 2 decimal places).** Without rounding,
   Spoolman's full-precision floats flowed straight through (e.g. `739.4936014320408`).
   `precision` is now a keyword arg on both `spoolman_to_fdb_gross` / `fdb_to_spoolman_net`
   (default 2), threaded from the `weight_precision_decimals` config key (range 0–4).
   Safe from sync churn: the maximum rounding delta at precision 2 is 0.005 g, far below
   the `sync_weight_threshold_grams` default of 2 g.

3. **Missing `material` defaults to `"Unknown"`.** Spoolman allows `material: null`;
   Filament DB requires the `type` field and returns 400 without it. When material is
   absent, the bridge substitutes `"Unknown"`, logs a warning naming the Spoolman filament
   id, and continues. Silent invention was rejected — the warning makes the substitution
   auditable.

4. **`wizard_completed` only flips on zero failures.** Previously the flag was set
   unconditionally after any non-fatal run, so a run with 211 failures still reported
   completion. Now `wizard_completed` is only set `true` when `failed == 0`. Users can
   re-run after fixing issues; idempotency already skips already-linked records so reruns
   are safe.

Architecture / approach decisions for filament-bridge, newest at top. One entry per
non-obvious call: a change of approach, a rejected alternative, or a workaround. Keep
entries short — the *why*, not a tutorial. Part of the
[handoff-prompt-workflow](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/handoff-prompt-workflow/README.md)
standard (see `standards.md`).

## 2026-05-30 — Make docker-compose deployable + SPA route fallback

Bringing the stack up locally surfaced four problems; all fixed.

1. **Upstream images live on GHCR, not Docker Hub.** `docker-compose.yml` referenced
   `hyiger/filament-db` and `donkie/spoolman` (both nonexistent on Docker Hub →
   `pull access denied`). Correct refs: `ghcr.io/hyiger/filament-db:latest`,
   `ghcr.io/donkie/spoolman:latest`.
2. **Spoolman listens on 8000 internally.** The compose mapped `7912:7912` but Spoolman
   binds 8000 by default, so nothing answered on 7912. Set `SPOOLMAN_PORT: "7912"` so the
   host mapping *and* the in-network `http://spoolman:7912` (used by the bridge service)
   both resolve. The whole project assumes Spoolman on 7912.
3. **Filament DB needs MongoDB.** It's a Next.js app that 500s on every API call without
   `MONGODB_URI`. Added a `mongo:7` service + `MONGODB_URI: mongodb://mongo:27017/filamentdb`,
   and dropped the meaningless `filamentdb-data:/data` volume (its state lives in Mongo).
4. **SPA route fallback.** Phase 4 served the build with `StaticFiles(html=True)`, which
   only serves `index.html` at the root — every client route (`/conflicts`, `/wizard`, …)
   404'd on hard refresh / direct load / shared link, since the app uses `BrowserRouter`.
   Replaced with: mount `/assets` for hashed bundles, plus a catch-all `GET /{full_path:path}`
   that returns the matching file if it exists else `index.html`. Guarded to still 404
   unknown `/api/*` paths (as JSON) rather than swallowing them into the SPA shell. Whole
   block stays behind `if _static_dir.is_dir()`, so pytest / `uvicorn --reload` are
   unaffected (no `/static` dir in dev).

**`docker-compose.dev.yml`** (tracked): same services with data bind-mounted under the
gitignored `./private_data/` instead of named volumes — lets you seed/inspect data from
the host. Safe to track because no real data is ever committed.

**Deep-link base caveat (known, not fixed):** the UI builds deep links from the URLs the
bridge reports (`systems[*].url`), which in compose are docker-internal names
(`http://filament-db:3000`). Browsers can't resolve those, so deep-link icons don't click
through in a localhost-only compose run. In a real LAN deployment the upstream URLs resolve
from both the bridge and the browser, so they work; for local poking, run the bridge in
host dev mode (uvicorn + `backend/.env` → `localhost:3000`/`7912`).

## 2026-05-29 — Phase 4 Web UI: SPA scaffold, static mount, deep-link bases, hooks

Key decisions taken while building the React SPA.

1. **`frontend/dist` → `static/` in the Docker image; mount guarded by `is_dir()`.**
   The Vite build writes to `frontend/dist`; the Dockerfile copies it to `/app/static/`
   in the runtime image. `main.py` resolves `Path(__file__).parent.parent.parent / "static"`
   and only calls `app.mount` when the directory exists — so `pytest` and local
   `uvicorn --reload` (no frontend build) pass without error. `html=True` on
   `StaticFiles` provides the SPA fallback for client-side routes.

2. **Deep-link bases come from `/api/health` `systems[*].url`, not env vars.**
   The backend already returns the configured `FILAMENTDB_URL` / `SPOOLMAN_URL` in the
   health response. `DeepLinkContext` fetches `/health` once on mount and provides the
   bases to all `DeepLinks` components. This means the UI never needs its own copy of the
   env vars and stays correct even if the backend is pointed at non-default URLs.

3. **Plain `fetch` + hooks, no react-query.**
   Two hooks — `useApi` (one-shot, re-runs on dep change) and `usePoll` (interval
   auto-refresh for the dashboard). Avoids a heavy dependency for a simple internal tool;
   adding react-query later is straightforward if the data requirements grow.

4. **Tare overrides are held in WizardShell state, not in a URL or context file.**
   The FR-5 weight-review step collects per-spool tare overrides and passes them into the
   `WizardShell` component's `tareOverrides` state. Step 6 submits them in the execute
   body. This matches the backend contract (the server does not persist tare overrides
   between calls) and keeps the wizard self-contained.

5. **Wizard step navigation is driven by the stepper index + React Router.**
   `WizardShell` owns the current step index and calls `navigate('/wizard/<path>')` on
   `next()`/`prev()`. Steps are plain route components with no shared session storage —
   each re-fetches its data from the API when mounted. This is correct for a wizard that
   is run once; it avoids stale cached state if the user navigates back and re-fetches.

## 2026-05-29 — Phase 3b wizard execute (FR-7): create order, idempotency, snapshot seed, fatal vs per-record

Decisions taken while building `POST /api/wizard/execute` — the initial bulk
write to both upstreams.

1. **Create order = filaments → variants → spools, in three passes.** Phase A
   resolves every source filament to a target filament id (link to an existing
   one, or `create_filament`). Phase B applies the FR-6 variant groupings
   (`update_filament` with `parentId`) as a *second pass* rather than setting
   `parentId` at create time: the variant decisions are keyed by FDB filament id,
   and a just-created filament has no id at decision time — so a variant decision
   can only reference a pre-existing (linked) filament. By the time Phase B runs,
   every referenced filament exists, so "parents before children" is satisfied
   for free. Phase C creates the `FilamentMapping`/`SpoolMapping` rows and seeds
   the spools. The parent id is resolved before spool seeding so the
   `filamentdb_parent_id` cross-ref and the `FilamentMapping.filamentdb_parent_id`
   column are written in one shot.

   **Superseded for the `spoolman` direction (2026-05-31, see below):** the
   FDB-keyed two-pass rationale only ever held because variant decisions were
   keyed by FDB filament id. That breaks in a greenfield FDB (no ids to key on),
   so the `_execute_spoolman_to_fdb` path now keys decisions by *Spoolman*
   filament id and injects `parentId` at create time (Pass 2), not via a
   post-hoc `update_filament`. The two-pass `update_filament(parentId)` approach
   survives only for the `filamentdb` direction (`_execute_fdb_to_spoolman`).

2. **Idempotency is keyed on the bridge's own mapping tables *and* the upstream
   cross-ref field.** Before creating, we skip if a `FilamentMapping`/`SpoolMapping`
   row exists (the normal re-run case) *or* if the Spoolman spool already carries a
   `filamentdb_spool_id` extra value (a prior run wrote upstream but its DB
   transaction rolled back — the commit is at the very end). This makes a re-run
   after a partial failure a no-op rather than a duplicator. Nothing upstream is
   ever deleted to "clean up" a partial run (CLAUDE.md hard rule); the re-run
   reconciles.

3. **Fatal vs per-record failure governs the `wizard_completed` flip.** A failure
   to *read* both systems is fatal — we write an error `SyncLog`, do **not** flip
   `wizard_completed`, and return `502 upstream_fetch_failed` (nothing was
   written). A single record's API error is isolated (NFR-4): it becomes a
   `failed` report entry + an `error` `SyncLog` and the run continues; the flag
   still flips, since the user can re-run to reconcile. There are no conflicts to
   queue here — the wizard is the user explicitly choosing the initial state
   (conflicts are an ongoing-sync concept, FR-13).

4. **Seed weights are SET on create, never logged as usage.** New target spools
   get their converted gross/net weight set directly on `create_spool`. Usage
   entries (`log_usage`) are reserved for ongoing decrements (FR-9); emitting them
   for the seed import would invent a fake consumption history.

5. **Snapshots are seeded post-write (best-effort).** Each freshly-linked pair
   gets both snapshot rows written using the engine's own
   `_sm_snapshot_dict`/`_fdb_snapshot_dict`/`_upsert_snapshot` helpers, so cycle 1
   of auto-sync diffs against a correct baseline instead of treating every record
   as first-seen. A snapshot-write error is swallowed (the engine baselines a
   first-seen pair anyway) so it can never fail the import.

6. **Tare overrides ride in the execute request body, not BridgeConfig.** Unlike
   match/variant decisions, the FR-5 per-spool tare overrides are *not* persisted
   in Phase 3 (there is no `POST /wizard/weights`). The UI collects them on the
   review screen and submits them with the execute call
   (`WizardExecuteRequest.tare_overrides`, keyed by whichever spool id the active
   direction uses). Absent an override, tare falls back to the spool's, then the
   filament's, `spool_weight`, then the 200 g default.

7. **Direction-model asymmetry (documented limitation).** The persisted
   `MatchDecision` is Spoolman-keyed (`link`/`create`/`skip` per Spoolman
   filament). It cleanly drives the `import_direction="spoolman"` path. For
   `import_direction="filamentdb"` the same link decisions still pair both ids,
   but FDB filaments with no link decision are created in Spoolman with no
   per-record skip granularity (the FR-4 "skip this unmatched record" choice for
   an FDB-only filament isn't representable in the Spoolman-keyed model). Accepted
   for now; revisit if the FDB-import direction needs per-record skips.

## 2026-05-29 — Phase 3 API: error envelope, conflict-resolve semantics, wizard state, backup format

Five decisions taken while building the bridge API layer (Phase 3):

1. **Error envelope.** Handled errors return `{"detail": {"code": <machine
   code>, "message": <human message>}}` via a single `api/errors.py:api_error()`
   helper. `code` is a stable string the UI branches on (e.g. `wizard_incomplete`,
   `manual_value_required`, `mapping_not_found`); `message` is for display.
   FastAPI's own validation (Pydantic `Literal`/`gt`) still returns its native
   422 shape — we don't wrap those.

2. **Conflict resolution = record now, apply on a later cycle.** `POST
   /conflicts/{id}/resolve` writes `resolution`/`resolved_value`/`resolved_at`
   on the row and drops it from the open queue, but performs **no upstream
   write** (honours the no-auto-resolve hard rule and keeps sync logic in
   `core/`). `resolved_value` is the chosen side's value (spoolman/filamentdb)
   or the supplied `manual` value. ⚠️ Engine gap: `core/engine` does not yet
   read resolved conflicts to push the chosen value upstream (and currently
   re-queues an unresolved weight conflict every cycle). Wiring the engine to
   consume resolutions is a Phase 2 follow-up — tracked, not done here.

3. **Wizard decision state lives in `BridgeConfig`, not a new table.** The
   wizard's direction (`import_direction`), match decisions
   (`wizard_match_decisions`), and variant groupings (`wizard_variant_decisions`)
   are persisted as JSON values in the existing key→JSON `BridgeConfig` store.
   Chosen over a dedicated `wizard_state` table to avoid an Alembic migration for
   transient setup data; Phase 3b reads these keys to execute (FR-7) and flips
   `wizard_completed`. The source-of-truth choices reuse the existing
   `*_source_of_truth` keys directly.

4. **Backup format.** `GET /backup/export` emits a versioned envelope
   (`schema_version = 1`) containing **bridge state only** — config, filament
   mappings, spool mappings, and *open* conflicts — never a copy of upstream
   data (CLAUDE.md). `POST /backup/import` is idempotent: mappings upsert by
   their unique business key (`spoolman_filament_id` / `spoolman_spool_id`)
   preserving ids so spool→filament FKs survive a clean restore; conflicts insert
   only when no equivalent open conflict exists (natural key: entity_type +
   field_name + the two ids). A mismatched `schema_version` is a 400.

5. **Mapping status enum (the `/mappings` + dashboard contract).** Precedence:
   `conflict` (an open Conflict references the spool) > `unlinked` (spool mapping
   has no parent filament mapping) > `pending` (a side has no snapshot yet) >
   `in_sync` (both snapshots present, no open conflict). Per-side weights and the
   name/vendor/color display fields come from the last **snapshots** (the
   Spoolman-side snapshot carries the filament detail; the FDB spool snapshot is
   trimmed), so the endpoint needs no live upstream fetch.

Test-harness note: the in-memory SQLite fixtures use `StaticPool` (one shared
connection) because FastAPI's `TestClient` runs sync handlers in a worker thread,
which would otherwise see its own empty `:memory:` database. `tests/conftest.py`
also `setdefault`s the required env vars so `cd backend && pytest` is
self-contained.

## 2026-05-29 — Async-job / sync-DB bridging approach (Option A — inline)

`run_sync_cycle` is a single `async def` that `await`s client I/O and calls
synchronous SQLAlchemy code inline — no thread, no second sync httpx client.
SQLite latency is microseconds; the only real bottleneck is the HTTP calls to
Spoolman and Filament DB. The brief loop stall is harmless for a single-container
homelab service. Rejected Option B (offload DB to `asyncio.to_thread` with a sync
httpx client) because it would split stack traces across the event loop and a worker
thread, surface errors a step removed from their cause, and require a parallel sync
`httpx.Client` purely to make the thread viable. Only revisit if a much larger
inventory (≫ 1000 spools) makes a cycle long enough to visibly stall the event loop.

## 2026-05-29 — Spoolman extra-field conflict-key definition (Phase 2)

The conflict `field_name` for a weight disagreement is `"weight"` (not
`"remaining_weight"` or `"totalWeight"`) so the resolution UI can display a
single unified weight conflict rather than two system-specific column names.
Field-mapping conflicts use the FDB dotted path (e.g. `"temperatures.nozzle"`)
as the key, which is the canonical name in the bridge's field-map config.

## 2026-05-28 — Canonical build-phase numbering (closes the skipped Phase 2)

The handoff prompts grew a numbering gap: Phase 0 (backend foundation) and Phase 1
(SQLite persistence) shipped, but the prompts then forward-referenced "Phase 3 (sync
engine)" and "Phase 4 (wizard API)" — there was never a Phase 2. The Phase 0 prompt only
mentioned Phase 2 in passing ("clients ... Phase 2 leans on this"). To keep the sequence
contiguous, the remaining work is renumbered to close the gap. This table is the single
source of truth for build-phase numbers; product-facing phases in `README.md` (guided
sync → dry run → auto-sync) and the migration-guide phases are separate schemes and are
unaffected.

| Build phase | Scope | Status |
|---|---|---|
| Phase 0 | Backend foundation — FastAPI skeleton, health (FR-1), upstream clients | ✅ done |
| Phase 1 | SQLite persistence — models, Alembic, config seed | ✅ done |
| Phase 2 | Continuous sync engine — snapshot/diff/match/apply/conflict/log (FR-8…FR-14) | next |
| Phase 3 | Bridge API layer — wizard read/decision endpoints (FR-1…FR-6) + sync/conflict/mappings/config/backup/log routers | planned |
| Phase 3b | Wizard execute (FR-7) — the initial-sync write to both upstreams; carved out for risk/isolation | planned |
| Phase 4 | Frontend SPA + `/static` mount (FR-15…FR-19) | planned |

The forward-references in the two completed prompts under `prompts/done/` were corrected
to match (sync engine 3→2, wizard 4→3, SPA 5→4).

## 2026-05-28 — Synchronous SQLAlchemy (not async) for the persistence layer

Used `create_engine` / `Session` rather than `create_async_engine` / `AsyncSession`.
SQLite latency is microseconds — the only real bottleneck is the HTTP calls to Spoolman
and Filament DB. Async SQLAlchemy + Alembic autogenerate also requires a sync
compatibility shim that adds complexity for zero practical gain. FastAPI runs sync
`Depends` handlers in a threadpool automatically, so sync DB sessions in route handlers
are safe without any extra wrapper.

## 2026-05-28 — Deep-link routes (corrects PRD NFR-7 / CLAUDE.md)

Verified against the live crzynet instances. The spec's guessed patterns were wrong:
- Filament DB filament: `{FILAMENTDB_URL}/filaments/{id}` — **plural**, not `/filament/{id}`.
- Spoolman spool: `{SPOOLMAN_URL}/spool/show/{id}` and filament `/filament/show/{id}` —
  **no hash routing** (newer Spoolman dropped `/#/`).
- Filament DB has **no standalone spool page** — spools render under the filament page.
  So bridge spool rows link to the parent filament page, not a per-spool URL.

## 2026-05-28 — Filament DB variant inheritance: read detail, strip computed fields

`GET /api/filaments/:id` resolves parent→variant inheritance server-side: the variant
response merges inherited values and names which ones in `_inherited[]` (plus `_parent`,
and `_variants[]` on the parent). The trimmed list view (`GET /api/filaments`) is for
enumeration only. Two rules for the bridge: (1) writing a material prop onto a variant
whose field is in `_inherited[]` overrides inheritance — check `_inherited[]` and
skip/flag instead of blindly writing; (2) strip computed/Mongoose fields before any PUT
(`_inherited`, `_parent`, `_variants`, `hasVariants`, `inherits`, `settings`, `__v`,
`instanceId`, `createdAt`, `updatedAt`, `_deletedAt`). Note `inherits` (a PrusaSlicer
preset name) is unrelated to the `parentId` variant tree — do not conflate.

## 2026-05-28 — Spoolman extra fields: create on startup, JSON-decode values

`GET /api/v1/field/spool` returns `[]` on the live instance — none of the bridge's
cross-ref fields exist. The bridge creates `filamentdb_id`, `filamentdb_parent_id`,
`filamentdb_spool_id` via `POST /api/v1/field/{entity_type}/{key}` on startup (chosen
over requiring manual UI setup — keeps deployment env-var-only). Spoolman stores text
extra-field values JSON-double-quoted (`"\"https://...\""`), so the bridge must
`json.loads()` them on read and `json.dumps()` on write, never use raw.

## 2026-05-28 — Sync engine defaults for the three design open questions

Defaults chosen now, revisitable later: (OQ#1) sync a weight change only when the delta
≥ a configurable threshold (default ~2g) to avoid rounding churn between net/gross
models. (OQ#6) full-snapshot diff each cycle — `GET /api/v1/spool?limit=1000` returns
all 223 spools fast enough; add incremental fetch only if a larger inventory demands it.
Note: `limit=1000` includes archived (active+archived both returned 223), so filter
`archived == false` client-side for the active set. (OQ#7) accept the aggregate weight
delta when multiple printers decrement one spool between cycles; per-printer attribution
is out of scope — documented, not silently dropped.

## 2026-05-28 — Docker base images: node:22-alpine (build) + python:3.12-slim-bookworm (runtime)

Multi-stage Dockerfile uses `node:22-alpine` for the React build stage (throw-away, never
ships) and `python:3.12-slim-bookworm` for the final runtime stage. Slim was chosen over
distroless/Chainguard because the service is still under active development — no shell
means no `exec`-based debugging, which is painful for a homelab sync tool. Revisit
distroless (`gcr.io/distroless/python3-debian12`) once the app is stable.

## 2026-05-31 — Unified dry-run: shared planner, auto-decisions, orphan bucket

**Shared planner location:** `_plan_spoolman_to_fdb`, `_SyncPlan`, `_FilamentPlanItem`,
`_SpoolPlanItem`, and `_fdb_filament_payload_from_sm` were extracted from
`backend/app/api/wizard.py` into `backend/app/core/planner.py`. Both `wizard_execute`
(FR-7) and `plan_dry_run` (FR-14) import from there — the same planner code means
preview ≡ execute by construction.

**Matcher → decisions mapping for the dry-run:**
`match_filaments(unlinked_sm, unlinked_fdb)` is called in `core/dryrun.py::plan_dry_run`
and its results are converted to `decisions_by_sm` before the planner runs:
- `matched` (1:1 confidence) → `{action: "link", filamentdb_id: <fdb.id>}` → planner
  emits `update` (filament_link) preview entries.
- `unmatched_spoolman` → `{action: "create"}` → planner emits `create` entries.
- `ambiguous` (multiple FDB candidates) → NOT auto-picked; emitted directly as
  `conflict` with `candidates: [<fdb_ids>]`. The planner never sees ambiguous SM
  filaments (they're excluded from `decisions_by_sm`).

**Cross-ref orphan bucket:** SM spools that already carry the `filamentdb_spool_id`
extra field but have no `SpoolMapping` row (the "167" from the live dataset) are now
bucketed as `update` with `reason: "re-link from existing cross-ref"`. The engine's
previous silent `continue` at the xref guard is preserved for live sync — only the
dry-run re-classifies them. Confirmed with user 2026-05-31.

**False-conflict removal:** `run_sync_cycle(dry_run=True)` buckets SM spools with no
`FilamentMapping` as `conflict(new_spool)` — this is correct for steady-state but wrong
for the initial-state dry-run. `plan_dry_run` filters those entries out (criterion:
`action==conflict, entity_type==spool, field==new_spool, fdb_filament_id==None`) before
adding the planner's reclassified entries.

## 2026-05-28 — Canonical version file is `backend/app/__init__.py`

For the `release-prep-and-cut` standard, the bare version lives in
`backend/app/__init__.py` (`__version__ = "X.Y.Z"`). Chosen over `pyproject.toml`
(the backend uses `requirements.txt`, not pyproject) and a root `VERSION` file (the
FastAPI app would have to parse it at runtime, whereas `__version__` is a native
import that also feeds the in-app version display). The file doesn't exist yet — it's
created when the backend lands.

## 2026-05-31 — Spoolman→FDB variant grouping: SM-keyed master-promote

The initial-sync wizard can now collapse a set of flat Spoolman filaments
(e.g. "ELEGOO PLA Red/Blue/…") into one FDB parent + variants *before* the
write, for the `import_direction="spoolman"` greenfield flow.

**Master = parent (a real filament, not a synthesized one).** Each SM filament
still maps 1:1 to an FDB filament; grouping only orders master-before-variants
and stamps `parentId` on the non-masters. The master is a normal filament with
its own color and spools. The user picks the master (radio) and prunes members
(checkbox); a group reduced to master-only dissolves to flat creates.

**SM-keyed persistence — new `wizard_sm_variant_decisions` key.** Decisions are
keyed by Spoolman filament id (`{master_spoolman_filament_id,
variant_spoolman_filament_ids[]}`), not FDB id, because a greenfield FDB has no
ids to key on. The legacy FDB-keyed `wizard_variant_decisions` +
`VariantDecision` + `_execute_fdb_to_spoolman` path is untouched; the two keys
coexist, one per direction. This corrects the earlier Phase-B rationale (above),
which documented the FDB-keyed two-pass `update_filament(parentId)` as
intentional — it was a workaround for FDB-keyed decisions and does not apply to
the spoolman direction, which injects `parentId` at create time.

**Clustering strips a color-word lexicon, not just the hex.** `_strip_color`
only removed a hex code, which under-clustered real names like "ELEGOO PLA Red".
Clustering now keys on `(normalize_vendor, normalize_name(material), base_name)`
where `base_name` strips both the hex and a known color-word lexicon
(red/blue/black/white/grey/green/…). Clusters are **hints only** — the GUI is
authoritative. Suggested master heuristic: most spools, tie-break shortest name.
Singletons (cluster of 1) are excluded.

**Shared properties are flagged, never auto-resolved.** `sm_prop_conflicts`
compares material/density/spool_weight/extruder_temp/bed_temp between master and
each member; mismatches surface as inline warnings in the preview
(`variant_plan`). The bridge never auto-picks a value (CLAUDE.md hard rule). A
group whose master has a `skip` match-decision is rejected at save; a variant
whose master failed to resolve at execute time emits a `failed` report entry
(no orphan `parentId`).

**Un-grouping after a successful run is out of scope.** The wizard builds the
tree before the first write only; reorganizing an already-synced parent/variant
tree is a separate, later concern.

## 2026-06-05 — Variances detail enrichment, per-field reconciliation, execute write-back, pre-flight summary

### Phase 1: Variances enriched display fields

`VariancesFilament` gained three new fields: `material_type` (the FDB `type` field from
the matched filament — only populated for `link` decisions, `None` for `create`), `diameter`
(SM filament diameter), and `color_hex` (SM filament color, for the color swatch). These
are populated in `wizard_variances` by building a `sm_to_fdb_type` map from `wizard_match_decisions`
and using the link's FDB filament's `type`. The `diameter` conflict check was also added to
`sm_prop_conflicts` in `matcher.py` (missing it was a bug) and the diameter field was added
to `_fdb_filament_payload_from_sm` in `planner.py` (another pre-existing omission).

### Phase 2: Per-group reconcile decisions

New schemas `ReconciledField` / `VariancesGroupReconcile` / `SMVariancesDecisionsRequest`
extend the existing `POST /wizard/variants/sm` endpoint to accept an optional `reconcile`
list (backwards-compatible — defaults to empty). Reconcile decisions are persisted under the
new `wizard_variances_reconcile` BridgeConfig key. An absent/empty `reconcile` payload leaves
any previously stored decisions untouched (non-destructive update).

### Phase 3: Execute write-back

`_execute_spoolman_to_fdb` gained:
- **Pass 2.5** (between variant creates and spool seeding): for each SM filament whose group
  has reconcile decisions, `_compute_sm_reconcile_patch` diffs canonical vs current SM values
  and calls `spoolman.update_filament`. Empty patch = no call. Errors are non-fatal (log and
  continue, per NFR-4). This pass runs only when `_reconcile_by_master` is non-empty.
- **FDB create overlay**: for master/ungrouped `create` items, `_overlay_reconcile_on_fdb_payload`
  is applied before `filamentdb.create_filament`. Nested keys (`temperatures.nozzle`) are handled
  via dot-notation splitting. Variants inherit from the FDB parent and are never overlaid separately.

**Canonical field map** (`_RECONCILE_FIELD_MAP`):
| canonical key | FDB payload key | Spoolman field |
|---|---|---|
| `type` | `type` | `material` |
| `density` | `density` | `density` |
| `diameter` | `diameter` | `diameter` |
| `nozzle_temp` | `temperatures.nozzle` | `settings_extruder_temp` |
| `bed_temp` | `temperatures.bed` | `settings_bed_temp` |
| `spool_weight` | `spoolWeight` | `spool_weight` |

Color fields are never written via the reconcile path. FDB `settings{}` is never touched.

### Phase 4: Pre-flight planned-writes summary

`_compute_planned_writes(plan, sm_filaments, reconcile_by_master)` is a pure helper that
produces `list[PlannedWrite]` covering: FDB filament creates (with reconcile overlay), FDB
spool creates, and Spoolman write-back PATCHes. It calls the exact same sub-functions as
execute, so `preview ≡ execute` by construction. `WizardPreviewResponse` gained `planned_writes`.
The frontend `StepNPreview.tsx` shows the section only for SM direction when the list is
non-empty, with All / Filament DB / Spoolman filter chips.

## 2026-06-06 — OpenPrintTag finish-tag model adopted; `filamentdb_material_tags` Spoolman extra field

### FDB finish model: base type + numeric tag IDs in optTags

Filament DB (≥ 1.33.0) models material finishes as numeric OpenPrintTag IDs in the
`optTags` array rather than as part of the material name string. For example, "PLA Silk"
in Spoolman maps to FDB `type="PLA"` + `optTags=[17]` (silk tag ID). This is the same
`optTags` field used by the multicolor path, but finishes use different IDs.

### New config-overridable keyword↔ID seed map

`DEFAULT_MATERIAL_TAG_IDS` in `backend/app/core/material_tags.py` seeds the full mapping:
`silk=17, matte=16, glitter=23, sparkle=23, glow=24, carbon=31, cf=31, glass=34, wood=41,
metal=46, metallic=46, translucent=19, transparent=20, high-speed=71, hs=71, rapid=71,
recycled=60`. Override or extend via the `MATERIAL_TAG_IDS` env var as
`keyword=id,keyword=id,...` pairs; an override replaces the entire seed (no merge).

`MANAGED_FINISH_IDS = frozenset({16,17,19,20,23,24,31,34,41,46,60,71})` defines the IDs
the bridge owns. IDs outside this set (including arrangement tags 28/29) pass through
`apply_finish_tags` untouched.

### New Spoolman filament-level extra field: `filamentdb_material_tags`

`ensure_extra_fields()` now also registers a filament-level extra field
(key `filamentdb_material_tags`, overridable via `SPOOLMAN_FIELD_FILAMENTDB_MATERIAL_TAGS`).
This stores the finish-tag IDs structurally as a JSON list of ints (e.g. `[17]`), allowing
round-trip sync without re-parsing text names each cycle.

Resolution order in `_sm_finish_ids_from_filament`: read the extra field first (structural,
trusted if set); fall back to `finish_ids_from_text(name, material)` for Spoolman filaments
that have not yet had the extra field populated.

### Flap-safety: finish-stripped type comparison in the differ

`differ.py` strips finish keywords from the Spoolman `material` value before comparing it
with the FDB `type` field. This prevents "PLA Silk" (SM) ↔ "PLA" (FDB) from appearing as
a perpetual type mismatch and flip-flopping each cycle. `strip_finish_words("PLA Silk")`
returns `"PLA"`. The generic field-mapping diff is unchanged; only the
`material` → `type` pair gets the stripped comparison.

### Arrangement tags (28/29) never touched by finish-tag code

`apply_finish_tags` and `_fdb_finish_ids` both respect `ARRANGEMENT_TAGS = {28, 29}`:
arrangement tags pass through untouched. Finish-tag code never reads or writes them.
The multicolor path retains exclusive ownership of tags 28/29.

### `_finish_sig` coexists with `_mc_sig` and `_cost` via `_merge_snapshot`

Ongoing sync stores the finish-tag state as `_finish_sig` (sorted comma-joined IDs string)
in the shared filament snapshot row. Like `_mc_sig` and `_cost`, it uses `_merge_snapshot`
(reads existing dict, updates one key, writes back), so all three keys coexist and no pass
clobbers another.

### Version gate: Filament DB ≥ 1.33.0 required (same as multicolor)

`_sync_finish_tags` is gated on `finish_tags_supported` (reuses `multicolor_supported`),
since `optTags` shipped in FDB 1.33.0. On older FDB versions the pass is a no-op.

### Wizard import: Pass 2.6 writes finish-tag extra field back to Spoolman

During SM→FDB import, `_fdb_filament_payload_from_sm` writes the parsed finish IDs as the
sentinel key `_sm_finish_ids` in the payload dict. After FDB filament creation (passes 1 and
2), a new **Pass 2.6** iterates the collected `_finish_ids_by_sm` dict and PATCHes each SM
filament's `extra.filamentdb_material_tags` so the extra field is populated from first import.

## 2026-06-07 — Settings `opentag_vendor_aliases` maps Spoolman vendor names to OpenTag brand names

The OpenTag matcher brand pre-filter uses `normalize_vendor(brandName)` to build a brand-keyed
candidate index. When a Spoolman vendor name differs from the OpenTag brand name (e.g. "Prusa"
in Spoolman vs "Prusament" in OpenTag), `normalize_vendor` treats them as different brands —
the SM filament's brand key never finds any OpenTag candidates, so the filament always
no-matches.

**Fix:** `Settings` (runtime config) gains `opentag_vendor_aliases: str` — a CSV of
`spoolman_vendor=opentag_brand` pairs (e.g. `prusa=prusament, polyterra=polymaker`). Both
sides are normalised via `normalize_vendor` at parse time. Default empty (no aliases).

**`resolve_opentag_brand(sm_vendor_name, aliases)`** in `backend/app/core/opentag_match.py`:
`key = normalize_vendor(sm_vendor_name); return aliases.get(key, key)`.
Returns the mapped OpenTag brand when a key is found, otherwise the normalized SM vendor name
unchanged.

**Applied in two places in `backend/app/api/opentag.py`:**
1. Brand pre-filter: `sm_brand_key = resolve_opentag_brand(sm_fil.vendor.name, vendor_aliases)`
   so the correct brand bucket (e.g. "prusament") is looked up.
2. `score_candidate` vendor component: `sm_vendor = resolve_opentag_brand(sm_vendor_name, aliases)`
   so the resolved brand is compared to `opt_brand` — "prusa" now equals "prusament" for scoring.

The aliases are loaded from BridgeConfig on every matches request (with env-default fallback and
a try/except so existing tests without a real DB are unaffected). The Settings UI ("Manufacturer
mappings (Spoolman → OpenTag)") writes the CSV to `opentag_vendor_aliases` in BridgeConfig.

---

## 2026-06-10 — Weight model: net = totalWeight − tare (no usageHistory subtraction); refresh both snapshots after a weight push

**Context.** Production hit a runaway, compounding weight-decrement loop: a single ~58 g print
drove a mapped spool to 0 g over several sync cycles, with the per-cycle decrement *doubling*
(58 → 116 → 232 …) and the value ping-ponging SM↔FDB each cycle.

**Root cause (two bugs).**
1. **Usage double-count.** `fdb_to_spoolman_net` computed `totalWeight − tare − sum(usageHistory)`.
   Verified against the live Filament DB API: `POST /api/filaments/:id/spools/:sid/usage` of 10 g
   reduces the spool's `totalWeight` by 10 **and** appends a 10 g `usageHistory` entry. So
   `totalWeight` already reflects usage; subtracting `usageHistory` again double-counts it.
2. **Stale snapshot feedback loop.** After a weight push the engine refreshed only the *source*
   side's snapshot (SM→FDB updated only the SM snapshot; FDB→SM only the FDB snapshot). The
   other side's just-changed value then looked like a fresh change next cycle and got pushed
   back — an infinite ping-pong, which bug #1 turned into a compounding decrement.

**Decision.**
- `fdb_to_spoolman_net(total, tare)` → `max(total − tare, 0)`; the `usage_grams_sum` parameter
  was removed so the double-count is impossible. (Only the ongoing FDB→SM weight path ever
  passed it; the wizard/planner/new-spool import paths already used `total − tare`, which is why
  the *initial* import was always correct.)
- After **either** weight-push direction the engine now refreshes **both** snapshots to the
  post-write agreed state: SM `remaining_weight` = the value written/current, and FDB
  `totalWeight` = `old_total − delta` (usage path) or the gross we set (increase path). Next
  cycle sees no change on either side → converges.
- The FDB→SM path no longer fetches the filament detail (it was only for the usage sum).

CLAUDE.md "Weight model translation" was corrected to match. Regression tests:
`test_engine.py::test_weight_two_way_print_converges_no_loop` and `…_fdb_change_converges_no_loop`
(multi-cycle convergence, no compounding); `test_weight.py::test_does_not_subtract_usage`.

## 2026-06-18 — BackupSafetyDialog made unconditionally friendly; debug clears moved to DebugConfirmDialog

**Context.** The original `BackupSafetyDialog` was styled like a warning gate — amber "Beta
feature" subtitle, red Proceed button, acknowledgement checkbox, Proceed disabled until a backup
succeeded or the box was checked. This was appropriate for test-only debug clears but heavy-handed
for normal product actions (wizard execute, OpenTag apply, enable auto-sync).

**Decision.**

`BackupSafetyDialog` is now unconditionally friendly:
- Title changed to "Back up first? (optional)"; subtitle drops the "Beta feature" framing.
- Acknowledgement checkbox removed; `canProceed` is always true.
- Proceed button recolored indigo (was red), relabeled "Continue — {actionLabel}".
- Backup buttons (Spoolman + Filament DB + mongodump note) retained as optional convenience.
- Call sites 1–3 (Wizard Execute, OpenTag Apply, Enable auto-sync ×2) unchanged.

The two Settings **Danger-Zone** debug clears (Clear Spoolman cross-refs, Clear Spoolman OpenPrintTag
ids) now use a new dedicated **`DebugConfirmDialog`** component
(`frontend/src/components/DebugConfirmDialog.tsx`) which preserves the strict gate:
- Red header ("Debug action — confirm"), irreversibility warning.
- Same optional backup buttons (via shared `BackupButtons` sub-component).
- Acknowledgement checkbox required before Confirm fires.
- Confirm button red, disabled until acknowledged.

**Shared sub-component.** The backup-buttons block (Spoolman + FDB backup buttons + mongodump note
with loading/ok/error states) is extracted into an exported `BackupButtons` component in
`BackupSafetyDialog.tsx`. `DebugConfirmDialog` imports and renders it — no UI duplication.

Settings call sites #4 and #5 (`Settings.tsx:608-619` pre-change) are repointed to
`DebugConfirmDialog`. The `window.confirm` reset-bridge path and the full-reset inline modal in
`Settings.tsx` are untouched.

## 2026-06-22 — Changelog archiving is summarize-on-archive (release-prep-and-cut v1.1.0)

**Context.** The `release-prep-and-cut` standard (v1.0.0) archived a closed minor series by
moving its full detail out of the active `CHANGELOG.md` and leaving only an index link. That
loses the at-a-glance history — a reader of the active changelog sees only the current series.
Archiving was deliberately **deferred** at the 0.4.0 and 0.5.0 releases pending this rule change,
so the active `CHANGELOG.md` currently still holds the full `0.3.x`, `0.4.x`, and `0.5.x` series.

**Decision.** Adopt **summarize-on-archive** (standard bumped to v1.1.0):

- **Trigger** — archiving fires only on a **minor (`0.x.0`) or major (`x.0.0`)** bump; patch
  bumps never archive.
- **What it produces** — for each closed minor series, the **full detail** moves to a per-minor
  archive file (`docs/CHANGELOG-<minor>.x.md`), and the active `CHANGELOG.md` keeps a **summary
  block** per archived version: a `## [<version>] — <date> (summary)` heading with **one bullet
  per major feature/fix** (small/trivial entries dropped) plus a deep link to the full archived
  section. Net: active file = `[Unreleased]` + current minor in full + older minors summarized.
- **Backlog scope** — a triggering bump archives **every closed minor series** still in the
  active file, not just the immediately-prior one. So the next minor (0.6.0) will archive
  `0.3.x` + `0.4.x` + `0.5.x` in one pass. (Chosen over "only the prior minor" because it
  self-heals the deferred backlog and keeps the rule simple. Open to revisit if the maintainer
  prefers archiving only the immediately-prior series.)

**Where.** Source standard `homelab-configs/standards/release-prep-and-cut` (README + `release-prep.md`
template, v1.0.0 → v1.1.0, tag `release-prep-and-cut/v1.1.0`); re-adopted here via `standards.md`
re-pin + `.claude/commands/release-prep.md` Step 3 (+ Step 0c wording).

## 2026-06-23 — Mobile updates & labels (phase 1 backend foundation)

**Context.** Filament DB prints spool labels only through its full app on a Brother-specific
device. We want the bridge to (later) print labels via LabelForge and make each label carry a
**QR code** that opens a phone-friendly page to read a scale weight and change a spool's location,
writing back to Filament DB (Spoolman follows via normal sync). This entry records the phase-1
backend decisions; the full user-facing docs land in a later phase.

**Decisions (implemented):**

- **QR identity = Filament DB filament id + spool id.** The printed QR encodes
  `https://{bridge_public_url}/r/{fdbFilamentId}/{fdbSpoolId}`. The bridge resolves the spool via
  its `SpoolMapping` (by `filamentdb_spool_id`). Spoolman is *not* the QR target — keeping the QR
  on the durable FDB ids means the same physical label survives re-imports/re-mapping.

- **`/r/...` redirect = indirection point.** `GET /r/{fil}/{spool}` returns a **302**
  (`RedirectResponse`, `status_code=302`) to a target chosen at runtime by `mobile_redirect_target`:
  `bridge` → the SPA scan page `/scan/{fil}/{spool}` (default); `filamentdb` →
  `{FILAMENTDB_URL}/filaments/{fil}`. The indirection lets the destination change later (e.g. to a
  future FDB mobile page) **without reprinting labels**. The route is registered **before** the SPA
  catch-all in `main.py` (it's outside `/api`, so otherwise `index.html` would swallow it).

- **Auth mirrors the app — no special public router.** The mobile router is included with the same
  `_auth_dep` as every other protected router; the `/r/` redirect carries the same dependency. There
  is no token-in-QR and no frontend auth exception: with auth off the flow is open; with auth on the
  whole site (scan page included) sits behind the session. Accepted per the plan.

- **Master feature gate `mobile_labels_enabled` (default OFF).** A single setting gates the whole
  feature. Every mobile/label endpoint and the `/r/` redirect depend on `_require_labels_enabled`,
  which returns **403** when off — copied directly from `api/debug.py:_require_debug_mode`. The flag
  is also surfaced in the public `GET /api/version` so the SPA can hide the nav item.

- **Weight save mode = setting + per-request override.** `mobile_weight_default_mode`
  (`direct_correction` default | `usage`); a PATCH may override it for one save. **The scale input is
  GROSS.** Tare = the FDB filament's `spoolWeight` (default `core/weight.py:DEFAULT_TARE_GRAMS`), so
  `net = gross − tare`. `direct_correction` true-ups both sides absolutely; `usage` logs an FDB usage
  entry on a **decrease** (preserving the audit trail; FDB reduces `totalWeight` itself) and falls
  back to the absolute path on an **increase** (a refill is never a negative usage). After any weight
  *or* location write, **both** snapshots are refreshed (anti-ping-pong), so the next auto-sync cycle
  sees no fresh change.

- **Shared helper extractions (reuse, don't duplicate):**
  - **`core/weight_ops.py`** — the absolute-write + dual-snapshot-refresh core was extracted out of
    `core/conflict_apply.py:_apply_weight` into `apply_absolute_weight(...)` (plus `apply_usage_weight(...)`
    for usage mode). `_apply_weight` now calls the shared helper; behaviour is byte-for-byte identical
    (same SM/FDB writes, snapshot merges, and `old_value="diverged"` sync-log entry) so the GitHub #21
    resolve/converge tests stay green.
  - **`core/locations.py`** — `ensure_fdb_location(filamentdb, name, cache=None)` (found-or-create of an
    FDB location id) was extracted from the wizard's inline spool-seeding block; the wizard now calls it
    (Spoolman stores location as a free-text string, FDB needs a `locationId`).
  - **`core/mobile.py`** — `resolve_spool_mapping` + `assemble_spool_detail` live-fetch both upstream
    records (fresher than the snapshot-based mapping rows) and build the page payload.

- **All config keys added now (including `labelforge_*`)** so config is touched once: `mobile_labels_enabled`,
  `bridge_public_url`, `mobile_redirect_target`, `mobile_weight_default_mode`, `labelforge_url`,
  `labelforge_token` (secret), `labelforge_template`, `labelforge_fields` (CSV), `labelforge_label_media`.
  They follow the `backup_*` pattern: env start-up fallback in `app/config.py`, BridgeConfig `_DEFAULTS`,
  and `ConfigResponse`/`ConfigUpdateRequest`/`_config_response`. Frontend, LabelForge printing, and the
  user-facing docs roll-up are deferred to later phases.

## 2026-06-23 — Mobile updates & labels (phase 2 frontend mobile flow)

**Context.** Phase 1 shipped the backend (`/api/mobile/*`, `/r/...` redirect, config keys, the
`mobile_labels_enabled` flag on `/api/version`). Phase 2 builds the UI: the bare QR scan page, the
in-nav page, the shared update card, and a minimal Settings section so the feature is testable.
LabelForge print buttons and the full LabelForge Settings fields stay Phase 3.

**Decisions (implemented):**

- **Nav gate reads `/api/version`, not `/api/config`.** The "Mobile updates" nav item is rendered
  only when `mobile_labels_enabled` is true. `Layout` already had the version payload in scope (the
  `VersionBadge` fetches it), so `Layout` does its own `getVersionInfo()` call and conditionally
  appends `{ to: '/mobile-updates', label: 'Mobile updates' }` to a local `navItems` derived from
  the static `NAV_ITEMS`. Using `/api/version` (public, already loaded app-wide) rather than
  `/api/config` keeps the gate cheap and matches where the backend chose to expose the flag. When the
  flag is off the page is also unreachable in practice (its API calls 403); a user who navigates to
  `/mobile-updates` directly sees the inline 403 message rather than a crash.

- **Scan route is a SIBLING outside `<Layout/>`; the in-nav page is inside it.** `/scan/:filId/:spoolId`
  → `ScanTarget` renders the shared card in a full-screen frame modeled on `Login.tsx`
  (`min-h-screen flex items-start justify-center`, `max-w-md`) with no side nav — it's the single-purpose
  QR target. `/mobile-updates` → `MobileUpdates` lives inside the Layout wrapper with the normal `p-8`
  shell. **No auth exception** for either — both sit behind the existing global gate in `App.tsx`, per
  the plan decision.

- **One shared `MobileSpoolUpdate` component, two entry points.** It takes `{ filId, spoolId }`,
  fetches the detail via `useApi`, and is rendered by both `ScanTarget` (bare) and `MobileUpdates`
  (after a search-and-select). The weight input is labelled as the **gross/scale** reading
  (`inputMode="decimal"`) with a live `gross − tare` net preview; the weight-mode toggle defaults to
  `detail.weight_default_mode` and is overridable; location is an `<input list>` datalist from
  `/api/mobile/locations`. Save sends **one** PATCH and only includes `gross_grams` when a valid weight
  was entered and `location` when it actually changed (`weight_mode` is always sent). Errors/success are
  inline banners (red text / emerald box) — matching `Conflicts.tsx`; there is no toast system.

- **In-nav search reuses the `SyncedRecords` filter over `getMappings()`.** Only `kind="spool"` rows
  with both FDB ids are selectable (the mobile flow is per-spool); the search matches name/vendor/color
  and the Spoolman spool id. No new search endpoint.

- **Minimal Settings section, clear Phase-3 seam.** A "Mobile updates" card exposes the enable toggle,
  QR redirect target, and default weight mode only. It folds into the existing single-Save config flow
  (added to `isDirty` + `handleSave`), so one Save covers it. The `labelforge_*` keys exist on the
  backend and in `ConfigResponse` but are deliberately **not** surfaced in the UI yet — that, plus the
  Print buttons, is Phase 3.

**Caveat (documented, not blocking):** QR *rendering* in LabelForge exists only on its `dev` branch
(`421caee`+, not v0.1.3). The HTTP API is identical across main/dev, so the bridge codes against the
stable API; printing a QR requires the user to run a LabelForge build with that work.

## 2026-06-23 — Mobile updates & labels (phase 3 — LabelForge label printing)

**Context.** Phases 1 (backend) + 2 (frontend mobile flow) shipped. Phase 3 wires up label printing:
a LabelForge service client, a print endpoint, the Print-label buttons, and the LabelForge connection
fields in Settings. The `labelforge_*` config keys + the `mobile_labels_enabled` gate already existed
from Phase 1; this phase only *uses* and *surfaces* them. Phase 4 (user-facing docs/PRD roll-up) is
separate.

**Decisions (implemented):**

- **Per-request LabelForge client; structured `LabelForgeError` (never a bare 500).**
  `services/labelforge.py:LabelForgeClient` is a plain async context manager (built from the
  runtime-editable `labelforge_url` + `labelforge_token`, sending `Authorization: Bearer …`). Because
  the config is runtime-editable and print volume is low, it is constructed per request rather than
  cached on `app.state` (unlike the always-on Spoolman/FDB clients). Every HTTP 4xx/5xx and network
  failure is caught and re-raised as a `LabelForgeError` carrying the upstream status code + the
  (string **or** structured-dict) `detail` — mirroring `api/backup.py`'s proxy-error style. The API
  layer maps it: a 409 `media_mismatch` → 409 `media_mismatch` (so the UI can offer an override
  retry), other 4xx pass through, everything else → 502. Never a bare 500.

- **The bridge owns a fixed field *catalog*; the CSV chooses which to send.** `api/labels.py` computes
  the six fields it can supply — `brand` (vendor), `color` (name), `color_hex`, `number` (= Spoolman
  spool id), `material`, `qr_url` — from the *same* `core/mobile.assemble_spool_detail` the mobile page
  uses (one resolve path, live-fetched). It then sends **only** the names listed in `labelforge_fields`
  (trim/split); an unknown/uncomputable name is **skipped with a warning**, never a hard failure — the
  template author controls the label, so a typo shouldn't block a print. `labelforge_url` +
  `labelforge_template` unset → a clear **400 `labelforge_not_configured`** (not a confusing upstream
  error). The named template itself is **user-created in LabelForge**; the bridge only fills values.

- **`qr_url` = `bridge_public_url` if set, else request-derived.** The QR payload is the absolute
  redirect `{base}/r/{fil}/{spool}` — the same indirection the redirect endpoint serves. `base` prefers
  the configured `bridge_public_url` (trailing slash stripped); when blank it is derived from the
  request, honoring `X-Forwarded-Proto`/`X-Forwarded-Host` so it's correct behind a reverse proxy.

- **One shared `PrintLabelButton`, two placements.** A `block` variant sits below Save on
  `MobileSpoolUpdate`; a `compact` variant is a row action on `SyncedRecords` (spool rows only, shown
  only when `mobile_labels_enabled` — read from `/api/version`, matching the nav gate). Success shows
  "Printed — job #N"; a 409 `media_mismatch` surfaces the detail **plus** a "Print anyway" button that
  retries with `override=true`. Inline banners, no toast — matching `Conflicts.tsx`.

- **Settings section renamed "Mobile updates" → "Mobile & Labels".** It gains the LabelForge fields:
  `bridge_public_url`, `labelforge_url`, `labelforge_token` (password input with show/hide, mirroring
  `api_token`), `labelforge_template`, `labelforge_fields` (CSV), `labelforge_label_media`, and a
  **Test printer** button (`GET /api/labels/printer-status`). All fold into the existing single
  `isDirty`/`handleSave` config flow and are greyed when the feature toggle is off.

**Caveat (unchanged from Phase 1, restated):** the QR *element* renders only on LabelForge `dev`
(>v0.1.3). The bridge codes against the stable API and prints the QR text into `qr_url` regardless; a
scannable QR simply needs the user to deploy a LabelForge build with that work. The text fields print
on any LabelForge version.

### Standalone Tare Editor (FR-23 / #26)

Tare (FDB `spoolWeight` ↔ SM `spool_weight`) is a **filament-level** field already synced
bidirectionally by the engine's material-scalar pass (`_sync_material_scalars`, category
`material_properties`, baseline key `_mp_spool_weight`). The Tare Editor is therefore a thin
UI + endpoint over the *existing* write path, not new sync logic.

**Write model — both sides, not "pick a side".** A tare edit is a deliberate, authoritative
user choice, so `core/tare.py:apply_tare` writes **both** systems directly and refreshes
**both** `_mp_spool_weight` snapshots in one step (the same anti-ping-pong pattern as the
engine's `_store` closure and `apply_cross_system_conflict`). It deliberately does NOT route
through `resolve_sync_action` / the configured `material_properties_sync_direction` — that axis
governs passive drift, not an explicit edit. Bulk apply commits **per row** so a later row's
failure can't roll back earlier successes (they share one session).

**Every mapped filament is editable; the list is grouped by variant family (revised
2026-06-25).** The original #26 design made variants read-only (edit the parent/standalone
only), reasoning that a per-variant override would diverge from the master. In practice a
library organised into variant clusters (generic-container or promoted-colour parents) then had
**no editable rows at all** — every mapped filament is a variant, the synthetic parents are
skipped, so the editor showed no checkboxes and nothing could be set. So variants are now
editable: `apply_tare` writes the chosen tare to **both** sides of that variant (an explicit
override) and refreshes both `_mp_spool_weight` snapshots, which keeps the engine from
re-detecting it as drift or flagging `master_divergence` (both sides agree). To keep the UI
legible, rows are **grouped by variant family**: `build_tare_rows` adds `group_key`
(`parentId` for a variant, else the filament's own id, so a master and its variants share one
key) and `group_name`, and the frontend renders a per-family header with a select-all checkbox.
Setting one value across a whole line is therefore select-family → set → Save.

**Listing uses list projections, not N detail fetches.** `build_tare_rows` reads SM
`get_filaments()` + FDB `get_filaments()` once each and resolves a variant's effective tare
client-side from its parent's stored value (the list view doesn't resolve inheritance). The
authoritative write only targets standalone/master rows, where the list-view value is the real
stored value, so this shortcut is safe.

Endpoints: `GET /api/tare` (list) and `POST /api/tare/bulk` (gated on upstream compatibility,
like the sync trigger / wizard execute, since it writes upstream). Frontend: `TareEditor.tsx`
nav page.
