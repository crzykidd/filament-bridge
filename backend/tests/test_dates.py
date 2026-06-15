"""Tests for Spoolman→Filament DB date provenance helpers (app.core.dates)."""

from types import SimpleNamespace

from app.core.dates import spool_provenance_dates, to_date_only


def test_to_date_only_truncates_datetime():
    assert to_date_only("2024-01-15T10:30:00") == "2024-01-15"


def test_to_date_only_handles_trailing_z():
    assert to_date_only("2024-01-15T10:30:00Z") == "2024-01-15"


def test_to_date_only_handles_offset():
    assert to_date_only("2024-01-15T10:30:00+02:00") == "2024-01-15"


def test_to_date_only_passes_date_only_through():
    assert to_date_only("2024-01-15") == "2024-01-15"


def test_to_date_only_none_and_empty():
    assert to_date_only(None) is None
    assert to_date_only("") is None


def test_to_date_only_unparseable_falls_back_to_first_10():
    # Not ISO-parseable but date-like prefix → first 10 chars.
    assert to_date_only("2024/01/15 weird") == "2024/01/15"


def test_provenance_maps_registered_and_first_used():
    spool = SimpleNamespace(
        registered="2023-11-02T09:00:00Z",
        first_used="2024-03-20T12:00:00",
    )
    assert spool_provenance_dates(spool) == {
        "purchaseDate": "2023-11-02",
        "openedDate": "2024-03-20",
    }


def test_provenance_omits_missing_fields():
    spool = SimpleNamespace(registered="2023-11-02T09:00:00Z", first_used=None)
    assert spool_provenance_dates(spool) == {"purchaseDate": "2023-11-02"}


def test_provenance_empty_when_no_dates():
    spool = SimpleNamespace(registered=None, first_used=None)
    assert spool_provenance_dates(spool) == {}
