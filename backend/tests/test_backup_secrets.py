"""Security tests for backup export/import secret-key boundary (H1 + H2).

Verifies that:
  (a) GET /backup/export never emits SECRET_CONFIG_KEYS entries, even when they
      are present in the DB.
  (b) POST /backup/import with a payload that includes secret keys leaves the
      target DB values untouched (import is a no-op for those keys).
  (c) A normal non-secret config key still round-trips through export → import.
  (d) The nightly on-disk backup (build_state_export) is also sanitised, since
      it delegates to export_backup internally.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import backup as backup_api
from app.api.config import SECRET_CONFIG_KEYS, get_config_value, set_config_value
from app.core.backup_job import build_state_export
from app.db import Base, get_db
from app.models.config import seed_defaults
from app.schemas.api import BACKUP_SCHEMA_VERSION


def _fresh_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    seed_defaults(session)
    set_config_value(session, "variant_parent_mode", "promote_color")
    session.commit()
    return session


def _client(db) -> TestClient:
    app = FastAPI()
    app.include_router(backup_api.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


# ---------------------------------------------------------------------------
# H1 — export must not emit any SECRET_CONFIG_KEYS
# ---------------------------------------------------------------------------


def test_export_omits_auth_secret(db):
    """auth_secret stored in DB must not appear in GET /backup/export output."""
    set_config_value(db, "auth_secret", "supersecret-signing-key")
    db.commit()

    resp = _client(db).get("/api/backup/export")
    assert resp.status_code == 200
    body = resp.json()
    assert "auth_secret" not in body["config"], (
        "auth_secret must never be exported (session-forgery risk)"
    )


def test_export_omits_admin_password_hash(db):
    """admin_password_hash stored in DB must not appear in GET /backup/export output."""
    set_config_value(db, "admin_password_hash", "$2b$12$fakehash")
    db.commit()

    resp = _client(db).get("/api/backup/export")
    assert resp.status_code == 200
    body = resp.json()
    assert "admin_password_hash" not in body["config"], (
        "admin_password_hash must never be exported (account-takeover risk)"
    )


def test_export_omits_api_token(db):
    """api_token stored in DB must not appear in GET /backup/export output."""
    set_config_value(db, "api_token", "tok-abc123")
    db.commit()

    resp = _client(db).get("/api/backup/export")
    assert resp.status_code == 200
    body = resp.json()
    assert "api_token" not in body["config"]


def test_export_omits_labelforge_token(db):
    """labelforge_token stored in DB must not appear in GET /backup/export output."""
    set_config_value(db, "labelforge_token", "lf-secret")
    db.commit()

    resp = _client(db).get("/api/backup/export")
    assert resp.status_code == 200
    body = resp.json()
    assert "labelforge_token" not in body["config"]


def test_export_omits_all_secret_config_keys(db):
    """All SECRET_CONFIG_KEYS must be absent from the export, regardless of DB state."""
    # Write every secret key with a recognisable value.
    for key in SECRET_CONFIG_KEYS:
        set_config_value(db, key, f"value-for-{key}")
    db.commit()

    resp = _client(db).get("/api/backup/export")
    assert resp.status_code == 200
    config_keys = set(resp.json()["config"].keys())
    leaked = SECRET_CONFIG_KEYS & config_keys
    assert not leaked, f"Backup export leaked secret keys: {leaked}"


def test_export_non_secret_key_is_present(db):
    """A regular (non-secret) config key must still appear in the export."""
    set_config_value(db, "sync_interval_seconds", 300)
    db.commit()

    resp = _client(db).get("/api/backup/export")
    assert resp.status_code == 200
    assert "sync_interval_seconds" in resp.json()["config"]


# ---------------------------------------------------------------------------
# H2 — import must not overwrite SECRET_CONFIG_KEYS on the target instance
# ---------------------------------------------------------------------------


def _minimal_export(config: dict) -> dict:
    """Build a minimal valid backup payload with the given config dict."""
    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "exported_at": "2026-07-02T00:00:00Z",
        "config": config,
        "filament_mappings": [],
        "spool_mappings": [],
        "open_conflicts": [],
    }


def test_import_does_not_overwrite_auth_secret(db):
    """Importing a backup that contains auth_secret must leave the DB value unchanged."""
    original_secret = "original-cookie-key"
    set_config_value(db, "auth_secret", original_secret)
    db.commit()

    payload = _minimal_export({"auth_secret": "attacker-controlled-key"})
    resp = _client(db).post("/api/backup/import", json=payload)
    assert resp.status_code == 200

    # The DB value must be unchanged.
    assert get_config_value(db, "auth_secret") == original_secret


def test_import_does_not_overwrite_admin_password_hash(db):
    """Importing a backup that contains admin_password_hash must not change the target hash."""
    original_hash = "$2b$12$original"
    set_config_value(db, "admin_password_hash", original_hash)
    db.commit()

    payload = _minimal_export({"admin_password_hash": "$2b$12$attacker"})
    resp = _client(db).post("/api/backup/import", json=payload)
    assert resp.status_code == 200

    assert get_config_value(db, "admin_password_hash") == original_hash


def test_import_does_not_overwrite_api_token(db):
    """Importing a backup that contains api_token must leave the target token unchanged."""
    set_config_value(db, "api_token", "real-token")
    db.commit()

    payload = _minimal_export({"api_token": "stolen-token"})
    resp = _client(db).post("/api/backup/import", json=payload)
    assert resp.status_code == 200

    assert get_config_value(db, "api_token") == "real-token"


def test_import_does_not_overwrite_labelforge_token(db):
    """Importing a backup that contains labelforge_token must leave the target token unchanged."""
    set_config_value(db, "labelforge_token", "real-lf-token")
    db.commit()

    payload = _minimal_export({"labelforge_token": "attacker-lf-token"})
    resp = _client(db).post("/api/backup/import", json=payload)
    assert resp.status_code == 200

    assert get_config_value(db, "labelforge_token") == "real-lf-token"


def test_import_secret_keys_not_counted(db):
    """Secret keys in the payload must not be reflected in the import response's config count."""
    payload = _minimal_export({
        "auth_secret": "leaked",
        "admin_password_hash": "leaked",
        "sync_interval_seconds": 180,  # one non-secret key
    })
    resp = _client(db).post("/api/backup/import", json=payload)
    assert resp.status_code == 200
    # Only the one non-secret key should be counted.
    assert resp.json()["config"] == 1


# ---------------------------------------------------------------------------
# Round-trip: non-secret key still works
# ---------------------------------------------------------------------------


def test_non_secret_config_roundtrips(db):
    """A non-secret config key (sync_interval_seconds) must survive export → import."""
    set_config_value(db, "sync_interval_seconds", 600)
    db.commit()

    export = _client(db).get("/api/backup/export").json()
    assert export["config"].get("sync_interval_seconds") == 600

    fresh = _fresh_db()
    resp = _client(fresh).post("/api/backup/import", json=export)
    assert resp.status_code == 200
    assert resp.json()["config"] >= 1  # at least this key applied

    assert get_config_value(fresh, "sync_interval_seconds") == 600
    fresh.close()


# ---------------------------------------------------------------------------
# Nightly backup path (build_state_export) is also sanitised
# ---------------------------------------------------------------------------


def test_build_state_export_omits_secret_keys(db):
    """The on-disk nightly backup helper must also exclude SECRET_CONFIG_KEYS."""
    for key in SECRET_CONFIG_KEYS:
        set_config_value(db, key, f"nightly-secret-{key}")
    db.commit()

    payload = build_state_export(db)
    config_keys = set(payload.get("config", {}).keys())
    leaked = SECRET_CONFIG_KEYS & config_keys
    assert not leaked, f"build_state_export leaked secret keys: {leaked}"
