"""
Read-only mirrored copy of tenant lookup logic, for use inside mzbs.

Per MULTI_TENANT_PLAN.md Decision #16: mzbs and mzbs-control-panel both
connect DIRECTLY to the same control-plane Postgres database. This copy
NEVER writes to that database — mzbs-control-panel (a separate repo) owns
all writes (tenant CRUD, status changes, subscriptions, feature flags).

This is what Phase 3's db.py -> get_session() calls to resolve a
tenant_id into a connection string at login time.

Add these two new env vars to mzbs's .env (same values as
mzbs-control-panel's .env — Decision #18):
    CONTROL_PLANE_DATABASE_URL
    CONTROL_PLANE_ENCRYPTION_KEY
"""

import threading
from datetime import datetime, timedelta
from urllib.parse import urlparse, urlunparse

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from starlette.config import Config

from utils.logging import logger

# ---------------------------------------------------------------------------
# Deliberately raw SQL, not a SQLModel `table=True` class: mzbs already runs
# SQLModel.metadata.create_all(engine) against its OWN school database
# (db.py -> create_db_and_tables()). Any table=True model defined anywhere
# in the mzbs codebase registers on that same global metadata by default —
# so a `class Tenant(SQLModel, table=True): __tablename__ = "tenants"` here
# would cause mzbs to try creating a `tenants` table inside every SCHOOL's
# database too. Raw SQL avoids that entirely; this module never touches
# SQLModel.metadata.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Own engine, own crypto — deliberately separate from mzbs's school-DB engine
# and from mzbs-control-panel's engine. Same target database as the latter.
# ---------------------------------------------------------------------------

try:
    _config = Config(".env")
except FileNotFoundError:
    _config = Config()

_CONTROL_PLANE_DATABASE_URL = _config("CONTROL_PLANE_DATABASE_URL", cast=str)
_CONTROL_PLANE_ENCRYPTION_KEY = _config("CONTROL_PLANE_ENCRYPTION_KEY", cast=str)

if not _CONTROL_PLANE_DATABASE_URL:
    raise ValueError("CONTROL_PLANE_DATABASE_URL is required in mzbs's environment")
if not _CONTROL_PLANE_ENCRYPTION_KEY:
    raise ValueError("CONTROL_PLANE_ENCRYPTION_KEY is required in mzbs's environment")

_fernet = Fernet(_CONTROL_PLANE_ENCRYPTION_KEY.encode())


def _normalize_database_url(raw_url: str) -> str:
    if not raw_url or raw_url == "None" or raw_url.startswith("postgresql+"):
        return raw_url
    parsed = urlparse(raw_url)
    if parsed.scheme in {"postgresql", "postgres"}:
        try:
            import psycopg2  # noqa: F401
            return urlunparse(parsed._replace(scheme="postgresql+psycopg2"))
        except Exception:
            try:
                import psycopg  # noqa: F401
                return urlunparse(parsed._replace(scheme="postgresql+psycopg"))
            except Exception:
                return raw_url
    return raw_url


_engine = create_engine(
    _normalize_database_url(_CONTROL_PLANE_DATABASE_URL),
    connect_args={"connect_timeout": 10},
    pool_size=5,
    max_overflow=5,
    pool_recycle=300,
    pool_pre_ping=True,
)

# ---------------------------------------------------------------------------
# Cached lookup — mirrors mzbs-control-panel's control_plane/tenant_lookup.py
# ---------------------------------------------------------------------------

_tenant_cache: dict[str, tuple[str, str, datetime]] = {}
_cache_lock = threading.Lock()
_CACHE_TTL = timedelta(minutes=5)


def lookup_tenant_connection(tenant_id: str) -> str:
    """Resolve tenant_id -> decrypted connection string. Read-only.
    Fails closed: unknown tenant -> 404. Suspended/expired/provisioning -> 403.
    """
    return _lookup_tenant_connection(tenant_id, allow_provisioning=False)


def lookup_tenant_connection_for_migration(tenant_id: str) -> str:
    """Resolve a tenant database for migrations, including provisioning tenants."""
    return _lookup_tenant_connection(tenant_id, allow_provisioning=True)


def _lookup_tenant_connection(tenant_id: str, allow_provisioning: bool) -> str:
    with _cache_lock:
        cached = _tenant_cache.get(tenant_id)
        if cached:
            conn_str, status, cached_at = cached
            if datetime.utcnow() - cached_at < _CACHE_TTL:
                _check_status(tenant_id, status, allow_provisioning)
                return conn_str
            _tenant_cache.pop(tenant_id, None)

    with _engine.connect() as conn:
        row = conn.execute(
            text("SELECT db_connection_secret, status FROM tenants WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        ).first()

    if not row:
        raise HTTPException(status_code=404, detail="Unknown school")

    encrypted_secret, status = row[0], row[1]
    try:
        conn_str = _fernet.decrypt(encrypted_secret.encode()).decode()
    except InvalidToken as e:
        raise RuntimeError(
            f"Could not decrypt the connection secret for tenant '{tenant_id}'. "
            "Check that CONTROL_PLANE_ENCRYPTION_KEY matches the key used to "
            "encrypt the stored secret, and verify the tenant record."
        ) from e

    with _cache_lock:
        _tenant_cache[tenant_id] = (conn_str, status, datetime.utcnow())

    _check_status(tenant_id, status, allow_provisioning)
    return conn_str


def _check_status(
    tenant_id: str,
    status: str,
    allow_provisioning: bool = False,
) -> None:
    allowed_statuses = {"active", "trial"}
    if allow_provisioning:
        allowed_statuses.add("provisioning")
    if status.lower() not in allowed_statuses:
        logger.warning(f"Blocked login attempt for tenant '{tenant_id}' with status '{status}'")
        raise HTTPException(status_code=403, detail="School account is not active")


def evict_idle_cache_entries(max_idle_minutes: int = 30) -> None:
    """Optional periodic cleanup — the TTL above already re-checks status on
    every access past 5 minutes, so this just bounds memory growth at scale."""
    cutoff = datetime.utcnow() - timedelta(minutes=max_idle_minutes)
    with _cache_lock:
        stale = [tid for tid, (_, _, cached_at) in _tenant_cache.items() if cached_at < cutoff]
        for tid in stale:
            _tenant_cache.pop(tid, None)


# ---------------------------------------------------------------------------
# Branding lookup — public metadata only (school_name, logo_url, status).
# Deliberately NEVER touches db_connection_secret, so this is safe to expose
# via an unauthenticated route (needed pre-login, on the landing/login pages).
# ---------------------------------------------------------------------------

_branding_cache: dict[str, tuple[dict, datetime]] = {}
_branding_cache_lock = threading.Lock()


def get_tenant_branding(tenant_id: str) -> dict:
    with _branding_cache_lock:
        cached = _branding_cache.get(tenant_id)
        if cached:
            branding, cached_at = cached
            if datetime.utcnow() - cached_at < _CACHE_TTL:
                return branding
            _branding_cache.pop(tenant_id, None)

    with _engine.connect() as conn:
        row = conn.execute(
            text("SELECT school_name, logo_url, status FROM tenants WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        ).first()

    if not row:
        raise HTTPException(status_code=404, detail="Unknown school")

    branding = {
        "school_name": row[0],
        "logo_url": row[1],
        "status": row[2],
    }

    with _branding_cache_lock:
        _branding_cache[tenant_id] = (branding, datetime.utcnow())

    return branding


def invalidate_branding_cache(tenant_id: str) -> None:
    with _branding_cache_lock:
        _branding_cache.pop(tenant_id, None)