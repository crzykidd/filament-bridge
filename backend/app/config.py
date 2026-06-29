import sys

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Required — app refuses to start without these
    filamentdb_url: str
    spoolman_url: str

    # Optional Bearer token for Filament DB's API-key auth (FDB >= 1.39.0, set
    # via FDB's own FILAMENTDB_API_KEY). Empty = no auth header (default; FDB's
    # API is unauthenticated unless that key is configured). When set, the bridge
    # sends `Authorization: Bearer <key>` on every Filament DB request.
    filamentdb_api_key: str = ""

    # Sync
    sync_interval_seconds: int = 120

    # Scheduled nightly backups (issue #5). Env vars are the start-up fallback;
    # the same keys are runtime-editable via BridgeConfig (DB value wins when set),
    # same precedence as sync_interval_seconds. The job writes the bridge's own
    # state export and the FDB snapshot into {data_dir}/backups/ and prunes old
    # files. Spoolman's server-side backup is deliberately NOT scheduled (the
    # bridge cannot prune Spoolman's own volume).
    backup_schedule_enabled: bool = True
    backup_bridge_state_enabled: bool = True
    backup_filamentdb_enabled: bool = True
    backup_retention_days: int = 7
    backup_hour_utc: int = 3

    # Spoolman extra field keys for cross-reference IDs
    spoolman_field_filamentdb_id: str = "filamentdb_id"
    spoolman_field_filamentdb_parent_id: str = "filamentdb_parent_id"
    spoolman_field_filamentdb_spool_id: str = "filamentdb_spool_id"
    # Spoolman FILAMENT-level extra field storing finish tag IDs (JSON list of ints)
    spoolman_field_filamentdb_material_tags: str = "filamentdb_material_tags"

    # Config-overridable keyword→OpenPrintTag-ID map for finish detection.
    # Format: "keyword=id,keyword2=id2" (same as field_mappings).
    # Empty string = use the seed defaults from core/material_tags.py.
    material_tag_ids: str = ""

    # Filament DB spool field that stores the Spoolman spool ID
    filamentdb_spoolman_id_field: str = "label"

    # Field mapping overrides (raw strings; parsed by properties below)
    # Format: "fdb_field=sm_field,fdb_field2=sm_field2"
    field_mappings: str = ""
    # Comma-separated field names to exclude from auto-match
    field_mapping_excludes: str = ""

    # Configurable marker appended to generic-container parent names.
    # Default "(Master)" keeps the container name visually distinct from its color children.
    # Empty string = no marker (containers get no suffix).
    container_parent_marker: str = "(Master)"

    # Comma-separated finish/line keywords for SM variant clustering.
    # Filaments whose names contain different keywords are placed in separate groups.
    variant_line_keywords: str = (
        "silk,matte,satin,carbon,cf,glow,wood,marble,metal,metallic,"
        "high-speed,hs,dual,tri,rainbow,multicolor,rapid"
    )

    # CSV of "spoolman_vendor=opentag_brand" pairs for OpenTag matching.
    # Maps Spoolman vendor names to OpenTag brand names so the brand pre-filter
    # works when the two systems use different names (e.g. "prusa=prusament").
    # Default empty — no aliases applied.
    opentag_vendor_aliases: str = ""

    # OpenTag extra fields on Spoolman filament entity
    spoolman_field_openprinttag_slug: str = "openprinttag_slug"
    spoolman_field_openprinttag_uuid: str = "openprinttag_uuid"
    # When set to "1", suppresses this filament from the "updates available" banner.
    # Stored on the Spoolman filament so it travels with the record.
    spoolman_field_openprinttag_ignore: str = "openprinttag_ignore"

    # OpenPrintTag material-setting extra fields on the Spoolman filament entity.
    # These hold standardized OPT material settings that Spoolman has no native field
    # for but Filament DB CAN store as first-class fields.  Populated from OpenPrintTag
    # via the cleanup-tool Apply flow, then synced to FDB by the material-properties
    # sync pass (same direction/conflict policy as the other material fields).
    # Registered as TYPED (integer/float) Spoolman extra fields by ensure_extra_fields.
    spoolman_field_openprinttag_nozzle_temp_min: str = "openprinttag_nozzle_temp_min"
    spoolman_field_openprinttag_nozzle_temp_max: str = "openprinttag_nozzle_temp_max"
    spoolman_field_openprinttag_drying_temp: str = "openprinttag_drying_temp"
    spoolman_field_openprinttag_drying_time: str = "openprinttag_drying_time"
    spoolman_field_openprinttag_hardness_shore_a: str = "openprinttag_hardness_shore_a"
    spoolman_field_openprinttag_hardness_shore_d: str = "openprinttag_hardness_shore_d"
    spoolman_field_openprinttag_transmission_distance: str = "openprinttag_transmission_distance"
    spoolman_field_openprinttag_bed_temp_min: str = "openprinttag_bed_temp_min"
    spoolman_field_openprinttag_bed_temp_max: str = "openprinttag_bed_temp_max"
    spoolman_field_openprinttag_chamber_temp_min: str = "openprinttag_chamber_temp_min"
    spoolman_field_openprinttag_chamber_temp_max: str = "openprinttag_chamber_temp_max"
    spoolman_field_openprinttag_chamber_temp: str = "openprinttag_chamber_temp"
    spoolman_field_openprinttag_preheat_temp: str = "openprinttag_preheat_temp"
    spoolman_field_openprinttag_nozzle_diameter_min: str = "openprinttag_nozzle_diameter_min"
    spoolman_field_openprinttag_cure_wavelength: str = "openprinttag_cure_wavelength"

    # Local OpenTag cache staleness threshold (hours)
    opentag_cache_max_age_hours: int = 24

    # Debug: write a startup state dump of both upstream systems at boot.
    # Env-level flag (not a runtime BridgeConfig setting) so it can gate
    # boot-time behavior without touching the DB.  Never enable in production.
    debug_startup_dump: bool = False

    # Changes log — append every upstream mutation to {data_dir}/changes.log.
    # CHANGES_LOG_ENABLED: set to "false" / "0" / "no" to disable.
    # CHANGES_LOG_PATH: override the file path (default: {data_dir}/changes.log).
    changes_log_enabled: bool = True
    changes_log_path: str = ""  # empty = use {data_dir}/changes.log

    # Mobile updates & labels (issue: mobile/labels phase 1). Env vars are the
    # start-up fallback; the same keys are runtime-editable via BridgeConfig (DB
    # value wins when set, same precedence as sync_interval_seconds). The whole
    # feature is gated by mobile_labels_enabled (default OFF) — when off, every
    # mobile/label/redirect endpoint refuses with 403 (mirrors debug_mode).
    mobile_labels_enabled: bool = False
    # Auth lifetime + gating for the mobile scan flow (the /r/ redirect, /api/mobile/*,
    # /api/labels/*, and the SPA /scan/:filId/:spoolId route). Integer days, default 30:
    #   0    → the scan flow is PUBLIC (bypasses the app password); the rest of the app
    #          stays password-protected.
    #   >= 1 → the scan flow requires the normal app login, AND the fb_session login
    #          cookie's lifetime is set to this many days.
    # Default 30 = no behavior change from before this setting existed. Independent of
    # mobile_labels_enabled (the 403 feature gate still applies regardless of this value).
    mobile_session_days: int = 30
    # External base URL baked into the printed QR (e.g. https://bridge.example.com).
    # Empty = derive from the incoming request when building absolute URLs later.
    bridge_public_url: str = ""
    # Where GET /r/{fil}/{spool} redirects: "bridge" → the SPA scan page;
    # "filamentdb" → the FDB filament page.
    mobile_redirect_target: str = "bridge"
    # Default weight-save mode for the mobile update page (overridable per request):
    # "direct_correction" (absolute true-up) | "usage" (log an FDB usage on a decrease).
    mobile_weight_default_mode: str = "direct_correction"
    # LabelForge integration (Phase 3 printing; config added now so config is touched once).
    labelforge_url: str = ""
    labelforge_token: str = ""  # secret — never returned in plaintext logs
    labelforge_template: str = ""
    labelforge_fields: str = ""  # CSV of label variable names, e.g. "brand,color,number,qr_url"
    labelforge_label_media: str = ""  # optional media/size hint passed to LabelForge

    # Notifications
    discord_webhook_url: str | None = None

    # Auth
    # When true (default), all /api/* routes except the public set require a
    # valid fb_session cookie or an enabled API token. Set to false to open the
    # app fully (e.g. for locked-out recovery: disable, change password, re-enable).
    auth_enabled: bool = True

    # Operational
    log_level: str = "info"
    data_dir: str = "/data"

    @field_validator("filamentdb_url", "spoolman_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def parsed_opentag_vendor_aliases(self) -> dict[str, str]:
        """Return normalized {sm_vendor: opentag_brand} alias dict.

        Parses ``opentag_vendor_aliases`` (CSV of ``sm=opentag`` pairs) using
        ``normalize_vendor`` on both sides so casing/whitespace are handled
        consistently.  Blank entries and entries missing ``=`` are silently
        ignored.  Duplicates: last one wins.
        """
        from app.core.matcher import normalize_vendor
        result: dict[str, str] = {}
        for pair in self.opentag_vendor_aliases.split(","):
            pair = pair.strip()
            if "=" not in pair:
                continue
            sm_raw, opentag_raw = pair.split("=", 1)
            sm_key = normalize_vendor(sm_raw.strip())
            opentag_val = normalize_vendor(opentag_raw.strip())
            if sm_key and opentag_val:
                result[sm_key] = opentag_val
        return result

    @property
    def parsed_variant_line_keywords(self) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for kw in self.variant_line_keywords.split(","):
            kw = kw.strip().lower()
            if kw and kw not in seen:
                seen.add(kw)
                result.append(kw)
        return result

    @property
    def parsed_field_mappings(self) -> dict[str, str]:
        if not self.field_mappings:
            return {}
        result: dict[str, str] = {}
        for pair in self.field_mappings.split(","):
            pair = pair.strip()
            if "=" in pair:
                fdb_field, sm_field = pair.split("=", 1)
                result[fdb_field.strip()] = sm_field.strip()
        return result

    @property
    def parsed_field_mapping_excludes(self) -> set[str]:
        if not self.field_mapping_excludes:
            return set()
        return {f.strip() for f in self.field_mapping_excludes.split(",") if f.strip()}

    @property
    def parsed_material_tag_ids(self) -> dict[str, int]:
        """Return the effective keyword→OpenPrintTag-ID map.

        If ``material_tag_ids`` is empty, returns the seed defaults from
        ``core.material_tags.DEFAULT_MATERIAL_TAG_IDS``.
        Otherwise parses the CSV override and returns that map exclusively.
        """
        from app.core.material_tags import DEFAULT_MATERIAL_TAG_IDS, parse_material_tag_ids_config
        if not self.material_tag_ids.strip():
            return dict(DEFAULT_MATERIAL_TAG_IDS)
        return parse_material_tag_ids_config(self.material_tag_ids)


try:
    settings = Settings()
except Exception as exc:
    sys.stderr.write(f"Configuration error: {exc}\n")
    sys.stderr.write("Ensure FILAMENTDB_URL and SPOOLMAN_URL are set.\n")
    raise SystemExit(1) from exc
