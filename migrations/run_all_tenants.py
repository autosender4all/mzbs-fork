"""
migrations/run_all_tenants.py

Phase 4, Day 3-5: fan the migration set out across every ACTIVE tenant,
tracking per-tenant/per-migration results in the control-plane
`migration_run_log` table, with dry-run and --only support.

Usage (run from the backend repo root, with `uv`):

    # Always do this first before a real run:
    uv run python -m migrations.run_all_tenants --dry-run

    # Real run, all pending migrations, all active tenants:
    uv run python -m migrations.run_all_tenants

    # Real run, but only one specific migration (for risky/multi-phase changes,
    # e.g. the 3-step enum migration pattern: ADD VALUE -> UPDATE -> recreate type):
    uv run python -m migrations.run_all_tenants --only 0007_add_admissions_module

    # Real run, but scoped to a single tenant (handy for re-running a failure,
    # or for onboarding a brand-new school that needs the full history):
    uv run python -m migrations.run_all_tenants --tenant mzbs_staging_school
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from types import ModuleType

from sqlalchemy import create_engine
from sqlmodel import Session

from db import get_control_plane_session, list_tenants
from control_plane_client.tenant_lookup import lookup_tenant_connection
from migrations.runner_core import (
    apply_migration,
    ensure_migrations_table,
    get_applied_migrations,
)
from migrations.run_log_service import write_migration_run_log

MIGRATIONS_DIR = Path(__file__).parent


def discover_migrations() -> list[ModuleType]:
    """Import every migrations/NNNN_*.py file in filename (== migration ID) order.

    Sorting by filename works because migration files are numeric-prefixed
    (0001_..., 0002_...), so lexicographic sort == chronological order.
    """
    files = sorted(MIGRATIONS_DIR.glob("[0-9]*.py"))
    modules = []
    for f in files:
        module = importlib.import_module(f"migrations.{f.stem}")
        if not hasattr(module, "MIGRATION_ID") or not hasattr(module, "upgrade"):
            raise RuntimeError(
                f"{f.name} is missing MIGRATION_ID or upgrade() — "
                "every file under migrations/ must define both."
            )
        modules.append(module)
    return modules


def run_for_tenant(
    tenant_id: str,
    conn_str: str,
    all_migrations: list[ModuleType],
    dry_run: bool = False,
) -> dict:
    """Apply pending migrations to a single tenant DB. Never raises —
    failures are captured in the returned dict so one tenant's problem
    doesn't kill the loop for the other 49 schools.
    """
    result: dict = {
        "tenant_id": tenant_id,
        "applied": [],
        "skipped": [],
        "pending": [],  # only populated in dry-run mode
        "failed": None,
    }
    engine = None
    try:
        engine = create_engine(conn_str)
        with Session(engine) as session:
            ensure_migrations_table(session)
            applied = get_applied_migrations(session)

            for module in all_migrations:
                if module.MIGRATION_ID in applied:
                    result["skipped"].append(module.MIGRATION_ID)
                    continue

                if dry_run:
                    result["pending"].append(module.MIGRATION_ID)
                    continue

                apply_migration(session, module)
                result["applied"].append(module.MIGRATION_ID)

    except Exception as e:  # noqa: BLE001 — intentionally broad, see docstring
        result["failed"] = f"{type(e).__name__}: {e}"
    finally:
        if engine is not None:
            engine.dispose()

    return result


def main(dry_run: bool = False, only: str | None = None, tenant: str | None = None) -> int:
    all_migrations = discover_migrations()

    if only:
        all_migrations = [m for m in all_migrations if m.MIGRATION_ID == only]
        if not all_migrations:
            print(f"No migration found with MIGRATION_ID == '{only}'. Aborting.")
            return 1

    with get_control_plane_session() as cp_session:
        tenants = list_tenants(cp_session)

    active_tenants = [t for t in tenants if t.status.lower() == "active"]
    if tenant:
        active_tenants = [t for t in active_tenants if t.tenant_id == tenant]
        if not active_tenants:
            print(f"No ACTIVE tenant found with tenant_id == '{tenant}'. Aborting.")
            return 1

    if not active_tenants:
        print("No active tenants found. Nothing to do.")
        return 0

    mode = "DRY RUN" if dry_run else "LIVE RUN"
    print(f"[{mode}] {len(all_migrations)} migration(s) x {len(active_tenants)} tenant(s)")
    print("-" * 60)

    any_failed = False

    for t in active_tenants:
        try:
            conn_str = lookup_tenant_connection(t.tenant_id)
        except Exception as e:  # noqa: BLE001 — isolate failures to this tenant
            result = {
                "tenant_id": t.tenant_id,
                "applied": [],
                "skipped": [],
                "pending": [],
                "failed": f"{type(e).__name__}: {e}",
                "lookup_failed": True,
            }
        else:
            result = run_for_tenant(t.tenant_id, conn_str, all_migrations, dry_run=dry_run)

        if dry_run:
            if result["failed"]:
                print(f"[{result['tenant_id']}] FAILED: {result['failed']}")
            else:
                print(
                    f"[{result['tenant_id']}] "
                    f"pending={result['pending']} already_applied={len(result['skipped'])}"
                )
        else:
            print(
                f"[{result['tenant_id']}] "
                f"applied={result['applied']} skipped={len(result['skipped'])} "
                f"failed={result['failed']}"
            )
            # Log every migration outcome for this tenant to the control plane,
            # per Phase 4 Day 5. Skip logging entirely in dry-run mode — nothing
            # actually happened, so there's nothing worth an audit row for.
            for mid in result["applied"]:
                write_migration_run_log(t.tenant_id, mid, "applied")
            if result["failed"] and not result.get("lookup_failed"):
                # We don't know exactly which specific migration_id was mid-flight
                # when the exception hit, so log it against the run as a whole
                # under the first not-yet-applied migration in this batch.
                remaining = [
                    m.MIGRATION_ID
                    for m in all_migrations
                    if m.MIGRATION_ID not in result["applied"]
                    and m.MIGRATION_ID not in result["skipped"]
                ]
                failing_id = remaining[0] if remaining else "unknown"
                write_migration_run_log(
                    t.tenant_id, failing_id, "failed", error_detail=result["failed"]
                )

        if result["failed"] and not dry_run:
            print(f"    !! ERROR for {result['tenant_id']}: {result['failed']}")
        if result["failed"]:
            any_failed = True

    print("-" * 60)
    if any_failed:
        if dry_run:
            print("Dry run incomplete: resolve the tenant errors above before treating it as a complete check.")
        else:
            print(
                "One or more tenants FAILED. Check migration_run_log before re-running. "
                "Do not re-run blindly."
            )
        return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fan out pending migrations across all tenants.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be applied per tenant; apply nothing.",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="Restrict to a single MIGRATION_ID (for risky/multi-phase migrations).",
    )
    parser.add_argument(
        "--tenant",
        type=str,
        default=None,
        help="Restrict to a single tenant_id (e.g. for retrying a failed run).",
    )
    args = parser.parse_args()
    sys.exit(main(dry_run=args.dry_run, only=args.only, tenant=args.tenant))



# To dry run this file
# cd F:\2_PROJECTS\A_MMS\mzbs
# .venv\Scripts\python.exe -m migrations.run_all_tenants --dry-run

# To run this file for a specific migration
# cd F:\2_PROJECTS\A_MMS\mzbs
#for checking all migration to all tenants
#.venv\Scripts\python.exe -m migrations.run_all_tenants

#for running a specific migration to all tenants
# .venv\Scripts\python.exe -m migrations.run_all_tenants --only 0007_add_admissions_module  