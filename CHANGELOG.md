# Changelog

All notable changes to **filament-bridge** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The bare
version lives in `backend/app/__init__.py`; the `v` prefix is added only on the git tag and
GitHub release.

## [Unreleased]

### Added

- Guided initial-sync wizard: connectivity check, import-direction + source-of-truth
  selection, fuzzy filament matching with review, weight/tare review, variant grouping,
  read-only dry-run preview, and execute.
- Match review v2 — a unified group-by / sort / per-column-filter table with bulk select,
  a Rescan action, and decision rehydration across visits.
- Spoolman ↔ Filament DB sync engine: snapshot / diff / apply on a configurable interval,
  with a manual conflict queue (conflicts are never auto-resolved).
- Net ↔ gross weight-model translation; Spoolman weight decrements are logged as Filament DB
  usage entries to preserve the usage-history audit trail.
- Parent/variant grouping when importing flat Spoolman filaments into Filament DB
  (Spoolman-keyed master-promote, `parentId` set at create time).
- Structured bidirectional multicolor sync, version-gated to Filament DB ≥ 1.33.0.
- Spool `location` carried from Spoolman into Filament DB on the initial seed
  (via `locationId`).
- Web UI: dashboard, synced records, conflict queue, and sync-log viewer, each with deep
  links into both upstream systems.

[Unreleased]: https://keepachangelog.com/en/1.1.0/
