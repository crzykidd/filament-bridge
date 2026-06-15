"""Consistent error envelope for the bridge API.

Every handled error returns ``{"detail": {"code": <machine code>, "message":
<human message>}}`` — FastAPI wraps the ``detail`` payload. ``code`` is a stable
string the UI can branch on; ``message`` is for display.
"""

from fastapi import HTTPException


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})
