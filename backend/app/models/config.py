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
