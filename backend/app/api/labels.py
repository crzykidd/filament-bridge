"""POST /api/labels/print + GET /api/labels/printer-status — LabelForge printing (phase 3).

Prints a spool label through a connected LabelForge instance.  The named template
is USER-created in LabelForge with ``{placeholder}`` text and (optionally) a
``{qr_url}`` QR element; the bridge only supplies the ``fields`` *values*.

The whole feature is gated by ``mobile_labels_enabled`` (default OFF) — every
route here depends on ``_require_labels_enabled`` (shared with ``api/mobile.py``)
and returns 403 when the flag is off.  Auth mirrors the rest of the app (the
router is included with the normal ``_auth_dep`` in ``main.py``).

Field catalog the bridge can compute (only the keys named in the
``labelforge_fields`` CSV are actually sent):
  * ``brand``      — Spoolman vendor name
  * ``color``      — color name
  * ``color_hex``  — color hex
  * ``number``     — Spoolman spool id (the human-facing label number)
  * ``material``   — material/type
  * ``qr_url``     — absolute ``{base}/r/{fil}/{spool}`` redirect URL, where
                     ``base`` = ``bridge_public_url`` if set, else derived from the
                     request.  Scanning it opens the mobile update page.

CAVEAT: QR *rendering* in LabelForge only exists on its ``dev`` branch (>v0.1.3).
The HTTP API is identical, so the bridge codes against the stable surface; a QR
label simply needs a LabelForge build with that work deployed.  See
``docs/decisions.md``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.config import (
    labelforge_fields,
    labelforge_label_media,
    labelforge_template,
    labelforge_token,
    labelforge_url,
)
from app.api.config import bridge_public_url as _bridge_public_url
from app.api.errors import api_error
from app.api.mobile import _require_labels_enabled
from app.core.mobile import assemble_spool_detail
from app.db import get_db
from app.schemas.api import LabelPrintRequest
from app.services.labelforge import LabelForgeClient, LabelForgeError

logger = logging.getLogger(__name__)

router = APIRouter()


def _resolve_base_url(db: Session, request: Request) -> str:
    """Return the external base URL for the QR (no trailing slash).

    Prefers the configured ``bridge_public_url``; otherwise derives it from the
    request (honoring X-Forwarded-Proto/Host when present behind a proxy).
    """
    configured = _bridge_public_url(db).strip()
    if configured:
        return configured.rstrip("/")

    # Derive from the request — respect reverse-proxy forwarding headers.
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if host:
        return f"{proto}://{host}".rstrip("/")
    return str(request.base_url).rstrip("/")


def _build_field_catalog(detail, qr_url: str) -> dict[str, str]:
    """Return the full catalog of label fields the bridge can supply (all stringified)."""
    return {
        "brand": str(detail.brand) if detail.brand is not None else "",
        "color": str(detail.color_name) if detail.color_name is not None else "",
        "color_hex": str(detail.color_hex) if detail.color_hex is not None else "",
        "number": str(detail.number),
        "material": str(detail.material) if detail.material is not None else "",
        "qr_url": qr_url,
    }


def _select_fields(csv: str, catalog: dict[str, str]) -> dict[str, str]:
    """Pick only the catalog fields named in the CSV; skip + warn on unknown names."""
    selected: dict[str, str] = {}
    for raw in csv.split(","):
        name = raw.strip()
        if not name:
            continue
        if name in catalog:
            selected[name] = catalog[name]
        else:
            logger.warning(
                "labels/print: configured field %r is not a known bridge field — skipping",
                name,
            )
    return selected


@router.post(
    "/labels/print",
    dependencies=[Depends(_require_labels_enabled)],
)
async def print_label(
    payload: LabelPrintRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Print a label for the spool identified by FDB filament + spool ids.

    Resolves the spool, builds the bridge field catalog, sends ONLY the fields
    named in the ``labelforge_fields`` CSV, and triggers a LabelForge print.
    Returns the LabelForge job result.  Errors surface a clear message (a 409
    media mismatch is returned so the UI can offer an "override" retry).
    """
    url = labelforge_url(db).strip()
    template = labelforge_template(db).strip()
    if not url or not template:
        raise api_error(
            400,
            "labelforge_not_configured",
            "LabelForge is not configured — set the LabelForge URL and template "
            "name in Settings → Mobile & Labels.",
        )

    detail = await assemble_spool_detail(
        db,
        request.app.state.spoolman,
        request.app.state.filamentdb,
        fdb_fil_id=payload.fil,
        fdb_spool_id=payload.spool,
    )
    if detail is None:
        raise api_error(
            404,
            "spool_not_mapped",
            f"No bridge mapping found for Filament DB spool {payload.spool}.",
        )

    base = _resolve_base_url(db, request)
    qr_url = f"{base}/r/{payload.fil}/{payload.spool}"
    catalog = _build_field_catalog(detail, qr_url)

    csv = labelforge_fields(db)
    selected = _select_fields(csv, catalog)

    media = labelforge_label_media(db).strip() or None

    try:
        async with LabelForgeClient(url, labelforge_token(db)) as client:
            result = await client.print_template(
                template, selected, media, override=payload.override
            )
    except LabelForgeError as exc:
        # 409 media mismatch → surface as 409 so the UI can offer an override retry.
        if exc.is_media_mismatch:
            raise api_error(409, "media_mismatch", exc.message) from exc
        # Map other upstream 4xx through; everything else → 502 (never a bare 500).
        status = exc.status_code if exc.status_code and 400 <= exc.status_code < 500 else 502
        raise api_error(status, "labelforge_error", exc.message) from exc

    return result


@router.get(
    "/labels/printer-status",
    dependencies=[Depends(_require_labels_enabled)],
)
async def get_printer_status(db: Session = Depends(get_db)) -> dict:
    """Proxy LabelForge's printer status for a pre-print check / Settings test.

    Returns ``{ready, model, loaded_media, errors, source}``.  A clear 400 when
    LabelForge isn't configured; a 502 (never a bare 500) on any upstream error.
    """
    url = labelforge_url(db).strip()
    if not url:
        raise api_error(
            400,
            "labelforge_not_configured",
            "LabelForge is not configured — set the LabelForge URL in "
            "Settings → Mobile & Labels.",
        )

    try:
        async with LabelForgeClient(url, labelforge_token(db)) as client:
            return await client.printer_status()
    except LabelForgeError as exc:
        status = exc.status_code if exc.status_code and 400 <= exc.status_code < 500 else 502
        raise api_error(status, "labelforge_error", exc.message) from exc
