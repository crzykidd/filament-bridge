"""Async HTTP client for the LabelForge label-printing REST API (phase 3).

LabelForge (``~/projects/labelforge``) is a self-hosted FastAPI app that drives a
Brother QL label printer.  The bridge supplies the ``fields`` values for a
USER-created template (``{placeholder}`` text + an optional ``{qr_url}`` QR
element) and triggers a print.

Stable API surface coded against here (identical across LabelForge main/dev):
  * ``POST /api/print/{name}`` — body ``{"fields": {...}, "label_media": null}``;
    ``?override=true`` forces a print despite a media mismatch.  Returns
    ``{job_id, status, template, label_media, overflow, preview_url}``.  Errors:
    400 (missing/invalid field), 404 (template not found), 409 (media mismatch
    or printer error — ``detail`` is a structured dict).
  * ``GET /api/printer/status`` — ``{ready, model, loaded_media, errors, source}``.

Auth: a single shared Bearer token (``labelforge_token``) sent on every call.

Errors never bubble up as a bare 500.  HTTP 4xx/5xx and network failures raise a
:class:`LabelForgeError` carrying the upstream status code and the (possibly
structured) ``detail`` so the API layer can surface a clear message — mirroring
the proxy-error style of ``app/api/backup.py``.

The client is built per request (config is runtime-editable and volume is low),
so it is a plain async context manager opened around each call.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class LabelForgeError(Exception):
    """A LabelForge call failed.

    Carries the upstream HTTP ``status_code`` (None for a network error) and the
    LabelForge ``detail`` payload, which may be a plain string (e.g. a 400 missing
    field) or a structured dict (e.g. a 409 ``{"error": "media_mismatch", ...}``).
    ``message`` is a human-readable summary the API layer can return directly.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        detail: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = detail

    @property
    def is_media_mismatch(self) -> bool:
        """True when this is a 409 media-mismatch the caller can retry with override."""
        return (
            self.status_code == 409
            and isinstance(self.detail, dict)
            and self.detail.get("error") == "media_mismatch"
        )


def _extract_detail(resp: httpx.Response) -> Any:
    """Return the ``detail`` from a LabelForge error body, or the raw text."""
    try:
        body = resp.json()
    except Exception:
        return resp.text[:300]
    if isinstance(body, dict) and "detail" in body:
        return body["detail"]
    return body


def _detail_message(detail: Any, fallback: str) -> str:
    """Render a LabelForge ``detail`` (str or structured dict) as a message string."""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        msg = detail.get("message")
        if msg:
            return str(msg)
    return fallback


class LabelForgeClient:
    """Thin async client for one LabelForge instance.

    Usage::

        async with LabelForgeClient(url, token) as client:
            result = await client.print_template("spool", {"brand": "Prusa"})
    """

    def __init__(self, base_url: str, token: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token or ""
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "LabelForgeClient":
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else None
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(15.0),
            headers=headers,
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "LabelForgeClient not started — use as async context manager"
            )
        return self._client

    async def print_template(
        self,
        name: str,
        fields: dict[str, str],
        label_media: str | None = None,
        override: bool = False,
    ) -> dict:
        """POST /api/print/{name} — print a template, returning the job result.

        ``fields`` maps template placeholders → string values.  ``label_media`` is
        an optional per-print media override (None = the template's stored media).
        ``override=True`` forces the print despite a printer media mismatch.

        Raises :class:`LabelForgeError` on any HTTP 4xx/5xx or network failure,
        surfacing LabelForge's ``detail`` (string or structured dict).
        """
        params = {"override": "true"} if override else None
        payload: dict[str, Any] = {"fields": fields, "label_media": label_media}
        try:
            resp = await self._http.post(
                f"/api/print/{name}", json=payload, params=params
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = _extract_detail(exc.response)
            status = exc.response.status_code
            raise LabelForgeError(
                _detail_message(detail, f"LabelForge returned HTTP {status}."),
                status_code=status,
                detail=detail,
            ) from exc
        except httpx.RequestError as exc:
            raise LabelForgeError(
                f"Could not reach LabelForge: {exc}", status_code=None
            ) from exc
        try:
            return resp.json()
        except Exception:  # noqa: BLE001 - defensive: empty/non-JSON success body
            return {}

    async def printer_status(self) -> dict:
        """GET /api/printer/status — current printer readiness + loaded media.

        Raises :class:`LabelForgeError` on any HTTP error or network failure.
        LabelForge returns 503 with ``{"error": "status_unavailable", ...}`` when
        the printer can't be reached; that surfaces as a LabelForgeError too.
        """
        try:
            resp = await self._http.get("/api/printer/status")
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = _extract_detail(exc.response)
            status = exc.response.status_code
            raise LabelForgeError(
                _detail_message(detail, f"LabelForge returned HTTP {status}."),
                status_code=status,
                detail=detail,
            ) from exc
        except httpx.RequestError as exc:
            raise LabelForgeError(
                f"Could not reach LabelForge: {exc}", status_code=None
            ) from exc
        try:
            return resp.json()
        except Exception:  # noqa: BLE001
            return {}
