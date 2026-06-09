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

    # Sync
    sync_interval_seconds: int = 120

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

    # CSV of "keyword=base_color" pairs for color-name normalization in the
    # OpenTag matcher.  Maps color words (including marketing names like
    # "galaxy", "jet", "cool") to canonical base colors so "Jet Black" and
    # "Galaxy Black" both reduce to "black" for base-color matching.
    # Default empty — uses the seed defaults from core/opentag_match.py.
    opentag_color_keywords: str = ""

    # OpenTag extra fields on Spoolman filament entity
    spoolman_field_openprinttag_slug: str = "openprinttag_slug"
    spoolman_field_openprinttag_uuid: str = "openprinttag_uuid"

    # Local OpenTag cache staleness threshold (hours)
    opentag_cache_max_age_hours: int = 24

    # Notifications
    discord_webhook_url: str | None = None

    # Operational
    log_level: str = "info"
    data_dir: str = "/data"

    @field_validator("filamentdb_url", "spoolman_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def parsed_opentag_color_keywords(self) -> dict[str, str]:
        """Return the effective color-words map (keyword → base color).

        When ``opentag_color_keywords`` is empty, returns ``DEFAULT_COLOR_KEYWORDS``
        from ``core.opentag_match``.  When non-empty, the CSV overrides are MERGED
        on top of the seed defaults so users can add entries without losing the seeds.
        """
        from app.core.opentag_match import DEFAULT_COLOR_KEYWORDS, parse_color_keywords_config
        if not self.opentag_color_keywords.strip():
            return dict(DEFAULT_COLOR_KEYWORDS)
        merged = dict(DEFAULT_COLOR_KEYWORDS)
        merged.update(parse_color_keywords_config(self.opentag_color_keywords))
        return merged

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
