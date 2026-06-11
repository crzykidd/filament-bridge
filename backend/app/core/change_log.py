"""Durable changes.log file sink for upstream mutations.

Appends one human-readable line per real upstream mutation (create / update /
delete / usage) to ``{DATA_DIR}/changes.log`` so users can audit what the bridge
wrote to Spoolman or Filament DB independent of the SQLite DB and the UI.

Design goals:
- Write failures NEVER break sync — all I/O is wrapped in try/except.
- Size-based rotation: roll to ``.1`` / ``.2`` past ~10 MB; keep 3 files.
- Clock seam: callers may inject a ``now`` callable for deterministic tests.
- Enabled / path are read from the app Settings at call time so runtime changes
  (via env vars) take effect without a restart.

Format (one line per change):
    <ISO-UTC>  <ACTION>  <system>  <entity_type> <id>[ "<label>"]  [<field>: <old> → <new>]   (<cycle>)
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# Maximum file size before rotation (bytes).  10 MiB by default.
_ROTATION_BYTES: int = 10 * 1024 * 1024
# Number of rotated backup files to keep (changes.log.1 … changes.log.N).
_ROTATION_COUNT: int = 3

# Actions that represent real upstream mutations and should be logged.
_MUTATION_ACTIONS: frozenset[str] = frozenset({"create", "update", "delete", "usage"})

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _render(value: Any) -> str:
    """Render a value compactly for the changes.log line.

    JSON-encoded strings are unwrapped; None becomes '—'; everything else
    uses its str() representation.
    """
    if value is None:
        return "—"
    if isinstance(value, str):
        # Attempt to unwrap a JSON-encoded scalar (e.g. Spoolman extra values).
        try:
            decoded = json.loads(value)
            if isinstance(decoded, (str, int, float, bool)):
                return str(decoded)
        except (json.JSONDecodeError, TypeError):
            pass
        return value
    if isinstance(value, (list, dict)):
        # Compact JSON for complex values — keep it on one line.
        return json.dumps(value, separators=(",", ":"))
    return str(value)


def _system_from_direction(direction: str) -> str:
    """Map a sync direction to the target upstream system name."""
    if direction == "spoolman_to_filamentdb":
        return "filamentdb"
    if direction == "filamentdb_to_spoolman":
        return "spoolman"
    # Wizard / conflict-apply use "wizard" or "conflict_apply" directions.
    return direction


def format_change_line(
    *,
    now: datetime.datetime,
    action: str,
    direction: str,
    entity_type: str,
    spoolman_id: int | None = None,
    fdb_filament_id: str | None = None,
    fdb_spool_id: str | None = None,
    field_name: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    cycle_id: str | None = None,
) -> str:
    """Build the single log line for one upstream mutation.

    Format:
        <ISO-UTC>  <ACTION>  <system>  <entity_type> <id>  [<field>: <old> → <new>]   (<cycle>)
    """
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    action_upper = action.upper()
    system = _system_from_direction(direction)

    # --- Build entity identifier ---
    if entity_type == "spool":
        if system == "spoolman" or direction in ("filamentdb_to_spoolman", "conflict_apply"):
            entity_id = f"spool #{spoolman_id}" if spoolman_id is not None else f"spool {fdb_spool_id}"
        else:
            # filamentdb side
            entity_id = f"spool {fdb_spool_id}" if fdb_spool_id else f"spool #{spoolman_id}"
    elif entity_type == "filament":
        if system == "spoolman" or direction in ("filamentdb_to_spoolman",):
            entity_id = f"filament #{spoolman_id}" if spoolman_id is not None else f"filament {fdb_filament_id}"
        else:
            entity_id = f"filament {fdb_filament_id}" if fdb_filament_id else f"filament #{spoolman_id}"
    else:
        # Generic fallback — show whatever ids are available.
        parts = []
        if spoolman_id is not None:
            parts.append(f"sm#{spoolman_id}")
        if fdb_filament_id:
            parts.append(f"fdb:{fdb_filament_id}")
        if fdb_spool_id:
            parts.append(f"spool:{fdb_spool_id}")
        entity_id = " ".join(parts) if parts else "unknown"

    # --- Build field change suffix ---
    field_part = ""
    if field_name:
        if action == "update":
            field_part = f"  {field_name}: {_render(old_value)} → {_render(new_value)}"
        elif action in ("create", "usage"):
            if new_value is not None:
                field_part = f"  {field_name}: {_render(new_value)}"

    # --- Cycle correlation ---
    cycle_part = f"  ({cycle_id})" if cycle_id else ""

    return f"{ts}  {action_upper}  {system}  {entity_type} {entity_id}{field_part}{cycle_part}"


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


def _rotate_if_needed(path: str) -> None:
    """Roll path → path.1 → path.2 … path.N if path exceeds _ROTATION_BYTES.

    Silently ignores errors — rotation failure should never break the caller.
    """
    try:
        if not os.path.exists(path):
            return
        if os.path.getsize(path) < _ROTATION_BYTES:
            return
        # Shift existing backups down (oldest first to avoid clobbering).
        for i in range(_ROTATION_COUNT - 1, 0, -1):
            src = f"{path}.{i}"
            dst = f"{path}.{i + 1}"
            if os.path.exists(src):
                os.replace(src, dst)
        # Rotate current → .1
        os.replace(path, f"{path}.1")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("changes.log: rotation failed: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record_change(
    *,
    action: str,
    direction: str,
    entity_type: str,
    spoolman_id: int | None = None,
    fdb_filament_id: str | None = None,
    fdb_spool_id: str | None = None,
    field_name: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    cycle_id: str | None = None,
    # Seams for testing.
    _now: Callable[[], datetime.datetime] | None = None,
    _path: str | None = None,
    _enabled: bool | None = None,
) -> None:
    """Append one line to changes.log for a real upstream mutation.

    Silently no-ops when:
    - The action is not in ``_MUTATION_ACTIONS`` (skip / info / conflict / error
      / dry-run actions are excluded).
    - ``CHANGES_LOG_ENABLED`` is ``false``.

    All file I/O errors are swallowed — a write failure must never propagate
    into the sync path.

    Parameters
    ----------
    action:
        Sync action string, e.g. ``"update"``, ``"create"``, ``"usage"``.
    direction:
        Sync direction, e.g. ``"spoolman_to_filamentdb"``.
    entity_type:
        ``"spool"`` or ``"filament"``.
    spoolman_id, fdb_filament_id, fdb_spool_id:
        At least one should be set so the entity is identifiable.
    field_name, old_value, new_value:
        Field-level detail for update lines.
    cycle_id:
        Sync cycle correlation id.
    _now:
        Callable returning the current UTC datetime (default: ``datetime.datetime.now(utc)``).
        Injected by tests for determinism.
    _path:
        Override the log file path (used by tests).
    _enabled:
        Override the enabled flag (used by tests).
    """
    # Filter: only log real mutations.
    if action not in _MUTATION_ACTIONS:
        return

    # Determine enabled state.
    if _enabled is None:
        try:
            from app.config import settings as _settings
            enabled_str = os.environ.get(
                "CHANGES_LOG_ENABLED",
                getattr(_settings, "changes_log_enabled", "true"),
            )
            _enabled = str(enabled_str).lower() not in ("0", "false", "no", "off")
        except Exception:
            _enabled = True

    if not _enabled:
        return

    # Determine file path.
    if _path is None:
        try:
            from app.config import settings as _settings
            data_dir = getattr(_settings, "data_dir", "/data")
            _path = os.environ.get(
                "CHANGES_LOG_PATH",
                os.path.join(data_dir, "changes.log"),
            )
        except Exception:
            _path = "/data/changes.log"

    # Build the timestamp.
    if _now is None:
        now_dt = datetime.datetime.now(datetime.timezone.utc)
    else:
        now_dt = _now()

    try:
        line = format_change_line(
            now=now_dt,
            action=action,
            direction=direction,
            entity_type=entity_type,
            spoolman_id=spoolman_id,
            fdb_filament_id=fdb_filament_id,
            fdb_spool_id=fdb_spool_id,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            cycle_id=cycle_id,
        )
    except Exception as exc:
        logger.warning("changes.log: format_change_line failed: %s", exc)
        return

    try:
        _rotate_if_needed(_path)
        with open(_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as exc:
        # Write failures must NEVER propagate into the sync path.
        logger.warning("changes.log: write to %s failed: %s", _path, exc)
