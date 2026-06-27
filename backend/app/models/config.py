from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base

_DEFAULTS = {
    "weight_source_of_truth": '"spoolman"',
    "material_properties_source_of_truth": '"filamentdb"',
    "auto_sync_enabled": "false",
    "sync_weight_threshold_grams": "2.0",
    "weight_precision_decimals": "2",
    "wizard_completed": "false",
    # New two-axis sync direction + conflict policy keys.
    # Values here are migration-safe defaults: both categories start one-way
    # (mirrors old SoT defaults) with manual conflict policy.
    "weight_sync_direction": '"spoolman_to_filamentdb"',
    "weight_conflict_policy": '"manual"',
    "material_properties_sync_direction": '"filamentdb_to_spoolman"',
    "material_properties_conflict_policy": '"manual"',
    # Archive/retire lifecycle sync for already-mapped spool pairs.
    # two_way mirrors a one-sided archive/retire flip to the other system; a genuine
    # both-sides-diverge flip queues a manual cross_system conflict. newest_wins is
    # NOT applicable (booleans aren't timestamp-eligible) and is rejected at the API.
    "archive_sync_direction": '"two_way"',
    "archive_conflict_policy": '"manual"',
    # Location sync for already-mapped spool pairs. Compares by NAME (Spoolman stores a
    # free-text location string; Filament DB stores a locationId resolved to its name).
    # two_way mirrors a one-sided location change to the other system; a genuine both-sides
    # change queues a manual cross_system conflict. newest_wins is NOT applicable (a location
    # name has no comparable timestamp) and is rejected at the API.
    "location_sync_direction": '"two_way"',
    "location_sync_conflict_policy": '"manual"',
    # New spool creation direction: two_way = bidirectional (= today's behavior).
    "new_spool_sync_direction": '"two_way"',
    # New-record handling policies (ongoing sync, not wizard).
    # manual_review (default) → queue an actionable conflict so the user decides.
    # auto_import → create the record automatically in the target system.
    # Default manual_review for both fresh AND existing installs (migration backfills).
    "new_filament_policy": '"manual_review"',
    "new_spool_policy": '"manual_review"',
    # Spoolman vendor → OpenTag brand aliases for the OpenTag cleanup matcher.
    # Seeded with common defaults for NEW installs only (on_conflict_do_nothing
    # never overwrites an existing install's value — empty or customised).
    "opentag_vendor_aliases": '"prusa=prusament, polyterra=polymaker"',
    # Runtime-configurable sync interval (seconds). 0 = use env-default.
    "sync_interval_seconds": "0",
    # Sync-log retention in days. 0 = keep forever.
    "sync_log_retention_days": "30",
    # When true, the wizard import skips creating FDB spool records for spools
    # whose remaining net weight is 0 (empty/depleted). The filament definition
    # is still imported; only the empty spool inventory record is excluded.
    "never_import_empties": "false",
    # Debug mode: when true, exposes the /api/debug/* reset endpoints for clean
    # re-testing (clear Spoolman FDB xrefs; reset bridge local state).
    # Off by default; never enable in production.
    "debug_mode": "false",
    # Variant parent mode for the Bulk Import Wizard (Spoolman → FDB direction).
    # "unset"            — user has not chosen; wizard is gated until a choice is made.
    # "promote_color"    — existing behaviour: one color becomes the FDB parent.
    # "generic_container"— a colorless bridge-owned container is created for every
    #                       cluster (even single-color); all colors are children.
    # Default "unset" so both fresh installs and existing installs require an explicit
    # choice — there is no silent fallback.
    "variant_parent_mode": '"unset"',
    # Marker appended to generic-container parent names so the container never collides
    # with its own color children (e.g. "ELEGOO PLA (Master)").
    # Empty string = no marker. Default "(Master)".
    "container_parent_marker": '"(Master)"',
    # Per-cluster container-name overrides: dict[cluster_key_str, str | null]
    # Each entry is either an override name string, or null to skip that cluster.
    # Populated from the Preview page's editable rename/skip UI.
    "wizard_container_name_overrides": "{}",
    # Auth: persisted server secret for signing fb_session cookies (itsdangerous).
    # Auto-generated on first startup; survives restarts so existing sessions remain valid.
    # Never expose in API responses or logs.
    "auth_secret": "null",
    # bcrypt hash of the admin password. "null" = password not yet set (setup required).
    "admin_password_hash": "null",
    # Single API token value. Stored so Settings UI can display it.
    # "null" = no token generated yet.
    "api_token": "null",
    # When true, requests may authenticate via Authorization: Bearer <token> or X-API-Key.
    "api_token_enabled": "false",
    # Scheduled nightly backups (issue #5). Env vars are the start-up fallback;
    # these DB values win when set (same precedence as sync_interval_seconds).
    # Master enable + two independent sub-toggles (bridge-state export, FDB
    # snapshot), all ON by default so the feature runs once deployed. Spoolman's
    # server-side backup is intentionally excluded (no prune control). Files land
    # in {data_dir}/backups/ and are pruned to backup_retention_days. The job runs
    # nightly at backup_hour_utc:00 UTC.
    "backup_schedule_enabled": "true",
    "backup_bridge_state_enabled": "true",
    "backup_filamentdb_enabled": "true",
    "backup_retention_days": "7",
    "backup_hour_utc": "3",
    # Mobile updates & labels (phase 1). Master toggle defaults OFF — the feature
    # is fully gated (403 on every mobile/label endpoint and the /r/ redirect, nav
    # item hidden) until the user configures the connection settings and flips it on.
    "mobile_labels_enabled": "false",
    # Mobile scan-flow auth + session lifetime (days). Default 30 = unchanged behavior.
    #   0    → the scan flow (/r/, /api/mobile/*, /api/labels/*, SPA /scan/...) is PUBLIC
    #          (bypasses the app password); the rest of the app stays protected.
    #   >= 1 → the scan flow requires the normal app login, and the fb_session cookie
    #          lives this many days. Independent of mobile_labels_enabled (the 403 gate
    #          still applies).
    "mobile_session_days": "30",
    # External base URL baked into the printed QR. Empty = derive from request.
    "bridge_public_url": '""',
    # Redirect target for GET /r/{fil}/{spool}: "bridge" (the SPA scan page) | "filamentdb".
    "mobile_redirect_target": '"bridge"',
    # Default weight-save mode: "direct_correction" (absolute) | "usage" (FDB usage on decrease).
    "mobile_weight_default_mode": '"direct_correction"',
    # LabelForge connection settings (Phase 3 printing; added now so config is touched once).
    "labelforge_url": '""',
    "labelforge_token": '""',
    "labelforge_template": '""',
    "labelforge_fields": '""',
    "labelforge_label_media": '""',
    # Last scheduled-backup run summary (issue #20). Written by _backup_job in main.py;
    # never user-editable. Null until the first nightly run completes (or fails).
    # Shape: {"at": <UTC iso>, "ok": bool, "bridge_state": <path|null>,
    #         "filamentdb": <path|null>, "pruned": [...names]} on success,
    # or {"at": <UTC iso>, "ok": false, "error": <str>} on failure.
    "backup_last_run": "null",
    # Last wizard execute run summary (issue #14). Written by wizard_execute in api/wizard.py;
    # never user-editable. Null until the first execute run completes (even partial).
    # Shape: {"cycle_id", "at": <UTC iso>, "direction", "created", "updated", "skipped",
    #         "failed", "completed": bool, "records": [WizardExecuteRecord dicts]}.
    # Records are ordered: failures first, then succeeded. Persisted on every execute
    # that reaches the gate (fatal 502/422/409 short-circuits before persisting).
    "wizard_last_run": "null",
}


class BridgeConfig(Base):
    __tablename__ = "bridge_config"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # JSON-encoded
    updated_at: Mapped[object] = mapped_column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )


def seed_defaults(db) -> None:
    from sqlalchemy.dialects.sqlite import insert

    for key, value in _DEFAULTS.items():
        stmt = insert(BridgeConfig).values(key=key, value=value).on_conflict_do_nothing()
        db.execute(stmt)
    db.commit()
