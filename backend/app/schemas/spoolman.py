"""Pydantic response models for the Spoolman REST API.

Models are lenient (extra="allow") so that API evolution doesn't break parsing.
Extra-field *values* from Spoolman are JSON-double-quoted; use decode_extra_value()
and encode_extra_value() when reading/writing them.
"""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def decode_extra_value(raw: str | None) -> Any:
    """Decode a Spoolman extra-field value (text fields are JSON-double-quoted)."""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def encode_extra_value(value: Any) -> str:
    """Encode a value for writing to a Spoolman extra field."""
    return json.dumps(value)


class SpoolmanVendor(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    name: str
    registered: str | None = None
    comment: str | None = None
    external_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class SpoolmanFilament(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    registered: str | None = None
    name: str
    vendor: SpoolmanVendor | None = None
    material: str | None = None
    price: float | None = None
    density: float | None = None
    diameter: float | None = None
    weight: float | None = None
    spool_weight: float | None = None
    article_number: str | None = None
    comment: str | None = None
    settings_extruder_temp: int | None = None
    settings_bed_temp: int | None = None
    color_hex: str | None = None
    multi_color_hexes: str | None = None
    multi_color_direction: str | None = None
    external_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class SpoolmanSpool(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    registered: str | None = None
    first_used: str | None = None
    last_used: str | None = None
    filament: SpoolmanFilament
    price: float | None = None
    initial_weight: float | None = None
    spool_weight: float | None = None
    remaining_weight: float | None = None
    remaining_length: float | None = None
    used_weight: float | None = None
    used_length: float | None = None
    location: str | None = None
    lot_nr: str | None = None
    comment: str | None = None
    archived: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


class SpoolmanFieldDef(BaseModel):
    """Extra-field definition returned by GET /api/v1/field/{entity_type}."""

    model_config = ConfigDict(extra="allow")

    key: str
    name: str
    field_type: str
    entity_type: str
    order: int = 0
    # JSON-encoded default (e.g. `"\"\""` for empty string)
    default_value: str | None = None


class SpoolmanInfo(BaseModel):
    """Version/info response from GET /api/v1/info."""

    model_config = ConfigDict(extra="allow")

    version: str | None = None
