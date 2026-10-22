"""Apply pending migrations to one tenant selected by tenant ID.

Usage:
    uv run python -m migrations.run_tenant_migrations
    uv run python -m migrations.run_tenant_migrations --tenant mzbs_staging_school
    uv run python -m migrations.run_tenant_migrations --tenant mzbs_staging_school --dry-run
"""

from __future__ import annotations

import argparse
import sys

from control_plane_client.tenant_lookup import (
    lookup_tenant_connection_for_migration,
)
from migrations.run_all_tenants import discover_migrations, run_for_tenant
from migrations.run_log_service import write_migration_run_log


def main(
    tenant: str | None = None,
    dry_run: bool = False,
    only: str | None = None,
) -> int:
    try:
        tenant_id = tenant or input("Tenant ID: ").strip()
    except EOFError:
        print("Error: interactive input was unavailable.", file=sys.stderr)
        return 1
    if not tenant_id:
        print("Error: tenant ID must not be empty.", file=sys.stderr)
        return 1

    migrations = discover_migrations()
    if only:
        migrations = [module for module in migrations if module.MIGRATION_ID == only]
        if not migrations:
            print(f"No migration found with MIGRATION_ID == '{only}'.", file=sys.stderr)
            return 1

    mode = "DRY RUN" if dry_run else "LIVE RUN"
    print(f"[{mode}] {len(migrations)} migration(s) for tenant '{tenant_id}'")

    try:
        connection_string = lookup_tenant_connection_for_migration(tenant_id)
    except Exception as exc:
        print(
            f"[{tenant_id}] FAILED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    result = run_for_tenant(
        tenant_id,
        connection_string,
        migrations,
        dry_run=dry_run,
    )

    if result["failed"]:
        print(f"[{tenant_id}] FAILED: {result['failed']}", file=sys.stderr)
        if not dry_run:
            for migration_id in result["applied"]:
                write_migration_run_log(tenant_id, migration_id, "applied")
            remaining = [
                module.MIGRATION_ID
                for module in migrations
                if module.MIGRATION_ID not in result["applied"]
                and module.MIGRATION_ID not in result["skipped"]
            ]
            if remaining:
                write_migration_run_log(
                    tenant_id,
                    remaining[0],
                    "failed",
                    error_detail=result["failed"],
                )
        return 1

    if dry_run:
        print(
            f"[{tenant_id}] pending={result['pending']} "
            f"already_applied={len(result['skipped'])}"
        )
    else:
        print(
            f"[{tenant_id}] applied={result['applied']} "
            f"skipped={len(result['skipped'])}"
        )
        for migration_id in result["applied"]:
            write_migration_run_log(tenant_id, migration_id, "applied")

    print("Done.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Apply pending migrations to one tenant database."
    )
    parser.add_argument(
        "--tenant",
        help="Tenant ID; prompted for if omitted.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show pending migrations without applying them.",
    )
    parser.add_argument(
        "--only",
        help="Restrict the run to one migration ID.",
    )
    args = parser.parse_args()
    raise SystemExit(main(tenant=args.tenant, dry_run=args.dry_run, only=args.only))
