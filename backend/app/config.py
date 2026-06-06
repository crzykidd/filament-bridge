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
