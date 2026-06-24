# Changelog — 0.4.x (archived)

Full release notes for the **0.4.x** series. The main
[CHANGELOG.md](../CHANGELOG.md) carries a short summary of each version with a
link back here; this file preserves the complete Keep-a-Changelog detail.

## [0.4.0] — 2026-06-21

### Added

- **Sync Log shows the record name** — the log had only ids; each row now carries a human-readable
  "Record" column (e.g. `Amolen PLA Basic-High Speed Cream Yellow`) resolved from the
  filament/spool mapping, with a best-effort live-Spoolman fallback so even not-yet-mapped records
  (e.g. `new_filament` conflicts) are named. Makes triaging "why didn't X import" far easier.
- **Variances step shows the OpenPrintTag (OPT) badge** — each filament in the variant-grouping
  step now displays an "OPT" pill when it's tagged in OpenPrintTag, so when you pick the master
  for a cluster you can choose the OPT-backed one (which carries the standardized settings) rather
  than a variant that isn't in OpenPrintTag.

### Fixed

- **In-app release notes now render as Markdown** instead of preformatted text, fixing the
  odd wrapping caused by CHANGELOG hard-wrap lines and 2-space list-continuation indents
  showing literally in the update-available and post-upgrade modals.

- **Bulk Import Wizard (generic-container mode): adding variants under an existing master no
  longer skips the whole cluster** — when the colorless container name (e.g. `ELEGOO PLA
  (Master)`) already existed in Filament DB, the preview reported it as a name collision
  ("This container name already exists — rename it or skip"), so the cluster was skipped and
  nothing imported — even though the execute step *reuses* an existing container by
  find-or-attach. The preview now recognizes an existing null-parent container as a reuse
  target rather than a collision, so the new variants attach to the master you already have.
  A genuine clash (the name taken only by a non-container/variant record, or two clusters in
  the batch generating the same name) is still flagged.
