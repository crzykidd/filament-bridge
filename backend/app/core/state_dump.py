"""Debug startup state dump — writes a human-readable snapshot of both upstream systems.

Gated by the ``DEBUG_STARTUP_DUMP`` env var (default ``false``).  When enabled,
the dump is written at startup as a background asyncio task so it never delays
the lifespan from completing.  Files land in ``{DATA_DIR}/state-dumps/`` and the
newest 10 are kept automatically.

Public API
----------
format_state_dump(sm_filaments, sm_spools, fdb_filaments, versions, now) -> str
    Pure formatter — takes already-fetched data, returns the complete dump text.
    Clock is injected so the output is unit-testable.

write_startup_dump(spoolman, filamentdb, data_dir, settings) -> None
    Async orchestrator: fetches data from both clients, calls format_state_dump,
    writes the file once (no partial writes), then prunes old dumps.

prune_dumps(dump_dir: Path, keep: int = 10) -> None
    Keeps the ``keep`` newest ``startup-state-*.txt`` files, deletes the rest.
    Non-matching files in the directory are ignored.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.schemas.filamentdb import FDBFilament
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, decode_extra_value

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.filamentdb import FilamentDBClient
    from app.services.spoolman import SpoolmanClient

logger = logging.getLogger(__name__)

# Glob pattern that identifies dump files (used by prune_dumps).
_DUMP_GLOB = "startup-state-*.txt"
_DUMP_PREFIX = "startup-state-"
_DUMP_SUFFIX = ".txt"

# Upstream-fetch retry budget.  When the whole compose stack starts together the
# bridge usually boots before Spoolman / Filament DB accept connections
# (depends_on orders container start, not readiness), so a one-shot fetch at
# boot would almost always fail.  12 attempts × 10 s ≈ 2 minutes of cover.
_FETCH_ATTEMPTS = 12
_FETCH_RETRY_DELAY_SECONDS = 10.0


# ---------------------------------------------------------------------------
# Pure formatter (unit-testable, clock injected)
# ---------------------------------------------------------------------------


def _sm_filament_line(f: SpoolmanFilament, settings: Any) -> str:
    """Render one Spoolman filament as a compact, diff-friendly line."""
    vendor = f.vendor.name if f.vendor else "—"
    color = f.color_hex or "—"
    name = f'"{f.name}"'

    parts = [
        f"filament #{f.id}",
        vendor,
        f.material or "—",
        name,
        f"color={color}",
        f"density={f.density}",
        f"dia={f.diameter}",
        f"spool_weight={f.spool_weight}",
        f"weight={f.weight}",
        f"price={f.price}",
    ]

    # Only emit bridge-relevant extra fields (skip empties).
    bridge_extra_keys = {
        settings.spoolman_field_filamentdb_id,
        settings.spoolman_field_filamentdb_parent_id,
        settings.spoolman_field_filamentdb_material_tags,
        settings.spoolman_field_openprinttag_slug,
        settings.spoolman_field_openprinttag_uuid,
    }
    extras: list[str] = []
    for key in sorted(f.extra.keys()):
        if key not in bridge_extra_keys:
            continue
        val = decode_extra_value(f.extra[key])
        if val is None or val == "" or val == []:
            continue
        # Truncate long IDs for readability.
        val_str = str(val)
        if len(val_str) > 20:
            val_str = val_str[:20] + "…"
        extras.append(f"{key}={val_str}")
    if extras:
        parts.append("extra: " + " ".join(extras))

    return " | ".join(parts)


def _sm_spool_line(s: SpoolmanSpool, settings: Any) -> str:
    """Render one Spoolman spool as a compact, diff-friendly line."""
    fil = s.filament
    fil_label = f'#{fil.id} "{fil.name}"'
    color = fil.color_hex or "—"

    parts = [
        f"spool #{s.id}",
        f"filament {fil_label} color={color}",
        f"remaining={s.remaining_weight}",
        f"used={s.used_weight}",
        f"location={s.location or '—'}",
        f"lot={s.lot_nr or '—'}",
        f"archived={s.archived}",
    ]

    # Only emit bridge-relevant cross-ref extras.
    bridge_extra_keys = {
        settings.spoolman_field_filamentdb_id,
        settings.spoolman_field_filamentdb_parent_id,
        settings.spoolman_field_filamentdb_spool_id,
    }
    extras: list[str] = []
    for key in sorted(s.extra.keys()):
        if key not in bridge_extra_keys:
            continue
        val = decode_extra_value(s.extra[key])
        if val is None or val == "" or val == []:
            continue
        val_str = str(val)
        if len(val_str) > 24:
            val_str = val_str[:24] + "…"
        extras.append(f"{key}={val_str}")
    if extras:
        parts.append("extra: " + " ".join(extras))

    return " | ".join(parts)


def _fdb_filament_line(f: FDBFilament) -> str:
    """Render one Filament DB filament as a compact, diff-friendly line."""
    parts = [
        f"filament {f.id}",
        f'"{f.name}"',
        f"vendor={f.vendor or '—'}",
        f"type={f.type or '—'}",
        f"color=#{f.color or '—'}",
        f"density={f.density}",
        f"spoolWeight={f.spoolWeight}",
        f"netFilamentWeight={f.netFilamentWeight}",
        f"cost={f.cost}",
    ]
    if f.parentId:
        parts.append(f"parentId={f.parentId}")
    if f.optTags:
        parts.append(f"optTags={f.optTags!r}")
    return " | ".join(parts)


def _fdb_spool_line(spool: Any, filament: FDBFilament) -> str:
    """Render one Filament DB spool subdocument as a compact, diff-friendly line."""
    parts = [
        f"spool {spool.id}",
        f'filament {filament.id} "{filament.name}"',
        f"totalWeight={spool.totalWeight}",
        f"label={spool.label or '—'}",
        f"retired={spool.retired}",
    ]
    return " | ".join(parts)


def format_state_dump(
    sm_filaments: list[SpoolmanFilament],
    sm_spools: list[SpoolmanSpool],
    fdb_filaments: list[FDBFilament],
    versions: dict[str, str | None],
    now: datetime.datetime,
    settings: Any,
) -> str:
    """Build and return the full dump text.

    Parameters
    ----------
    sm_filaments:
        All Spoolman filaments (sorted by id inside this function).
    sm_spools:
        All Spoolman spools (sorted by id inside this function).
    fdb_filaments:
        All Filament DB filaments from the list view (sorted by id).
    versions:
        Dict with keys ``"bridge"``, ``"spoolman"``, ``"filamentdb"`` (any may be None).
    now:
        UTC datetime injected for testability (used in the header).
    settings:
        The bridge Settings object (for extra-field key names).
    """
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    bridge_v = versions.get("bridge") or "unknown"
    sm_v = versions.get("spoolman") or "unknown"
    fdb_v = versions.get("filamentdb") or "unknown"

    lines: list[str] = [
        "# filament-bridge startup state dump",
        f"# written: {ts}   bridge: {bridge_v}   spoolman: {sm_v}   filamentdb: {fdb_v}",
        "# retention: newest 10 dumps kept in this directory",
        "",
    ]

    # -- Spoolman filaments --
    sm_fils_sorted = sorted(sm_filaments, key=lambda f: f.id)
    lines.append(f"== SPOOLMAN FILAMENTS ({len(sm_fils_sorted)}) ==")
    for f in sm_fils_sorted:
        lines.append(_sm_filament_line(f, settings))
    lines.append("")

    # -- Spoolman spools --
    sm_spools_sorted = sorted(sm_spools, key=lambda s: s.id)
    lines.append(f"== SPOOLMAN SPOOLS ({len(sm_spools_sorted)}) ==")
    for s in sm_spools_sorted:
        lines.append(_sm_spool_line(s, settings))
    lines.append("")

    # -- Filament DB filaments --
    fdb_fils_sorted = sorted(fdb_filaments, key=lambda f: f.id)
    lines.append(f"== FILAMENT DB FILAMENTS ({len(fdb_fils_sorted)}) ==")
    for f in fdb_fils_sorted:
        lines.append(_fdb_filament_line(f))
    lines.append("")

    # -- Filament DB spools (flattened from embedded subdocuments) --
    fdb_spools: list[tuple[Any, FDBFilament]] = []
    for f in fdb_fils_sorted:
        for sp in f.spools:
            fdb_spools.append((sp, f))
    # Sort by spool id (string sort — MongoDB ObjectId; lexicographic is chronological)
    fdb_spools.sort(key=lambda pair: pair[0].id)
    lines.append(f"== FILAMENT DB SPOOLS ({len(fdb_spools)}) ==")
    for sp, fil in fdb_spools:
        lines.append(_fdb_spool_line(sp, fil))
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Retention (prune old dumps)
# ---------------------------------------------------------------------------


def prune_dumps(dump_dir: Path, keep: int = 10) -> None:
    """Keep the newest *keep* dump files; delete anything older.

    Only files matching ``startup-state-*.txt`` are touched.
    Non-matching files in the directory are left alone.
    Silently ignores errors deleting individual files.
    """
    candidates = sorted(dump_dir.glob(_DUMP_GLOB))
    # Files are named with ISO basic timestamp → lexicographic = chronological.
    to_delete = candidates[: max(0, len(candidates) - keep)]
    for path in to_delete:
        try:
            path.unlink()
            logger.debug("state_dump: pruned old dump %s", path.name)
        except OSError as exc:
            logger.warning("state_dump: could not delete old dump %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Async orchestrator
# ---------------------------------------------------------------------------


async def write_startup_dump(
    spoolman: "SpoolmanClient",
    filamentdb: "FilamentDBClient",
    data_dir: str,
    settings: "Settings",
) -> None:
    """Fetch state from both upstreams and write a startup dump file.

    Designed to run as a background asyncio task.  Any exception is caught,
    logged as a warning, and swallowed — the dump must never break startup.
    Builds the complete text in memory before writing (no partial writes).

    The data fetch retries (``_FETCH_ATTEMPTS`` × ``_FETCH_RETRY_DELAY_SECONDS``)
    because at boot the upstreams are usually still starting alongside the bridge.
    """
    try:
        import asyncio

        from app import __version__

        # Fetch the record data concurrently, retrying while the upstreams warm up.
        for attempt in range(1, _FETCH_ATTEMPTS + 1):
            try:
                sm_filaments, sm_spools, fdb_filaments = await asyncio.gather(
                    spoolman.get_filaments(),
                    spoolman.get_spools(),
                    filamentdb.get_filaments(),
                )
                break
            except Exception as exc:
                if attempt == _FETCH_ATTEMPTS:
                    raise
                logger.info(
                    "state_dump: upstream fetch failed (attempt %d/%d): %s — retrying in %.0fs",
                    attempt, _FETCH_ATTEMPTS, exc, _FETCH_RETRY_DELAY_SECONDS,
                )
                await asyncio.sleep(_FETCH_RETRY_DELAY_SECONDS)

        # Versions are fetched after the data succeeds.  Force a fresh FDB version
        # read: get_version() caches its first result for the client's lifetime, and
        # that first read may have happened (and failed) while FDB was still booting.
        filamentdb._version_fetched = False
        sm_version, fdb_version = await asyncio.gather(
            _get_sm_version(spoolman),
            filamentdb.get_version(),
        )

        now = datetime.datetime.now(datetime.timezone.utc)
        versions = {
            "bridge": __version__,
            "spoolman": sm_version,
            "filamentdb": fdb_version,
        }
        text = format_state_dump(sm_filaments, sm_spools, fdb_filaments, versions, now, settings)

        # Write to {DATA_DIR}/state-dumps/startup-state-<ts>.txt
        dump_dir = Path(data_dir) / "state-dumps"
        dump_dir.mkdir(parents=True, exist_ok=True)
        ts = now.strftime("%Y%m%dT%H%M%SZ")
        out_path = dump_dir / f"{_DUMP_PREFIX}{ts}{_DUMP_SUFFIX}"
        out_path.write_text(text, encoding="utf-8")
        logger.info("state_dump: wrote %s (%d bytes)", out_path, len(text.encode("utf-8")))

        prune_dumps(dump_dir, keep=10)

    except Exception as exc:  # noqa: BLE001
        logger.warning("state_dump: failed to write startup dump: %s", exc, exc_info=True)


async def _get_sm_version(spoolman: "SpoolmanClient") -> str | None:
    """Fetch Spoolman version from /api/v1/info; returns None on any error."""
    try:
        from app.schemas.spoolman import SpoolmanInfo

        resp = await spoolman._http.get("/api/v1/info")
        resp.raise_for_status()
        return SpoolmanInfo.model_validate(resp.json()).version
    except Exception:
        return None
