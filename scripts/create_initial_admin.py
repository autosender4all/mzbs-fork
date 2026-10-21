#!/usr/bin/env python3
"""Initialize a fresh tenant database and create its first active administrator.

Examples:
    uv run python scripts/create_initial_admin.py
    uv run python scripts/create_initial_admin.py --env-file .env.newtenant
    uv run python scripts/create_initial_admin.py --database-url <database-url>

This creates tables from the current SQLModel metadata, applies the
migration-defined database objects and initial permission/theme data that
aren't fully represented by the models, and records the historical migration
baseline. It only runs against an empty PostgreSQL database.
"""

import argparse
import io
import getpass
import importlib
import os
import pkgutil
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import dotenv_values
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import configure_mappers
from sqlmodel import SQLModel, Session, create_engine, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BOOTSTRAP_MIGRATION_IDS = (
    "0001_add_role_permissions_tables",
    "0002_add_appearance_settings",
    "0003_fix_appearance_default_palette",
    "0004_add_debit_module_permissions",
    "0005_add_debit_tables",
    "0006_add_staff_profile_attendance_permissions",
    "0007_extend_staff_attendance_and_shift_timing",
    "0008_add_teacher_name_id_to_user",
    "0009_add_marking_audit_to_staffattendance",
    "0010_fix_staff_attendance_multi_shift_constraint",
    "0011_add_soft_delete_to_teachernames",
    "0012_add_remarks_to_fees",
    "0013_add_staff_shift_timing_versions",
    "0014_add_attendance_holiday_policy",
    "0015_add_user_active_and_teacher_delete_metadata",
    "0016_add_remarks_to_salary_payments",
)

INITIAL_DATA_MIGRATIONS = (
    "0001_add_role_permissions_tables",
    "0002_add_appearance_settings",
    "0004_add_debit_module_permissions",
    "0006_add_staff_profile_attendance_permissions",
)


class SetupError(Exception):
    """An expected, safe-to-display setup failure."""


def _default_env_file() -> Path:
    return PROJECT_ROOT / ".env"


def _configure_environment(
    env_file: Path,
    explicit_database_url: str | None,
    env_file_was_explicit: bool,
) -> str:
    if env_file.is_file():
        values = dotenv_values(env_file)
    elif env_file_was_explicit:
        raise SetupError(f"Environment file not found: {env_file}")
    else:
        values = {}

    for key, value in values.items():
        if value is not None:
            os.environ.setdefault(key, value)

    file_database_url = values.get("DATABASE_URL")
    database_url = explicit_database_url or (
        file_database_url
        if env_file_was_explicit and file_database_url
        else os.environ.get("DATABASE_URL") or file_database_url
    )
    if not database_url or not database_url.strip() or database_url.strip() == "None":
        raise SetupError(
            "DATABASE_URL is not configured. Set it in the selected environment "
            "file, in the process environment, or pass --database-url."
        )

    database_url = database_url.strip()
    # Make the selected URL visible to the application's Starlette Config
    # objects, which otherwise read only the default root .env file.
    os.environ["DATABASE_URL"] = database_url
    return database_url


def _load_application_components() -> tuple[Any, Any, Any, Any, Any]:
    try:
        import schemas

        for module in pkgutil.iter_modules(schemas.__path__):
            importlib.import_module(f"schemas.{module.name}")

        from db import _normalize_database_url
        from user.services import get_password_hash
        from user.user_models import User, UserCreate, UserRole

        configure_mappers()
    except Exception as exc:
        raise SetupError(
            "Could not register the application's SQLModel schema and user "
            "components. Check the application dependencies and configuration."
        ) from exc

    return User, UserCreate, UserRole, get_password_hash, _normalize_database_url


def _make_engine(database_url: str, normalize_database_url: Any) -> Any:
    try:
        normalized_url = normalize_database_url(database_url)
        engine = create_engine(
            normalized_url,
            echo=False,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 10},
        )
        if engine.dialect.name != "postgresql":
            engine.dispose()
            raise SetupError(
                "Tenant initialization requires PostgreSQL because its schema "
                "includes PostgreSQL-specific constraints and indexes."
            )
        return engine
    except SetupError:
        raise
    except Exception as exc:
        raise SetupError(
            "Could not initialize a database connection using the configured URL."
        ) from exc


def _ensure_database_is_empty(connection: Any) -> None:
    try:
        connection.exec_driver_sql("SELECT 1")
        existing_relations = connection.execute(
            text(
                """
                SELECT n.nspname, c.relname
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
                  AND n.nspname NOT LIKE 'pg_toast%'
                  AND n.nspname NOT LIKE 'pg_temp_%'
                  AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
                LIMIT 1
                """
            )
        ).first()
        if existing_relations is not None:
            raise SetupError(
                "The selected PostgreSQL database already contains schema "
                "objects. Refusing to initialize a non-empty database."
            )
    except SetupError:
        raise
    except Exception as exc:
        raise SetupError(
            "Could not connect to PostgreSQL or verify that the database is empty."
        ) from exc


def _target_description(database_url: str) -> str:
    parsed = urlparse(database_url)
    host = parsed.hostname or "local"
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    database = parsed.path.lstrip("/") or "<default database>"
    return f"{host}/{database}"


def _create_migration_schema_objects(connection: Any) -> None:
    """Add PostgreSQL objects from migrations that SQLModel doesn't express."""
    statements = (
        'CREATE UNIQUE INDEX ux_user_teacher_name_id ON "user" (teacher_name_id) '
        "WHERE teacher_name_id IS NOT NULL",
        'CREATE INDEX ix_user_is_active ON "user" (is_active)',
        "CREATE INDEX ix_teachernames_is_deleted ON teachernames (is_deleted)",
        "CREATE INDEX ix_teachernames_deleted_at ON teachernames (deleted_at)",
        "CREATE INDEX ix_teachernames_deleted_by ON teachernames (deleted_by)",
        "CREATE INDEX ix_staff_shift_timing_version_shift_date "
        "ON staff_shift_timing_version (attendance_time_id, effective_from DESC)",
        "ALTER TABLE staffattendance ADD CONSTRAINT "
        "ck_staffattendance_schedule_required "
        "CHECK (schedule_id IS NOT NULL OR schedule_is_legacy = TRUE)",
        "ALTER TABLE staff_shift_timing_version ADD CONSTRAINT "
        "ck_staff_shift_timing_start_before_end CHECK (start_time < end_time)",
        "ALTER TABLE attendance_weekly_holiday ADD CONSTRAINT "
        "ck_attendance_weekly_holiday_weekday CHECK (weekday >= 0 AND weekday <= 6)",
        "ALTER TABLE attendance_date_exception ADD CONSTRAINT "
        "ck_attendance_date_exception_kind "
        "CHECK (kind IN ('HOLIDAY', 'WORKING_DAY'))",
    )
    for statement in statements:
        connection.exec_driver_sql(statement)


def _verify_migration_baseline() -> tuple[str, ...]:
    migration_files = sorted((PROJECT_ROOT / "migrations").glob("[0-9]*.py"))
    migration_ids = tuple(path.stem for path in migration_files)
    if migration_ids != BOOTSTRAP_MIGRATION_IDS:
        raise SetupError(
            "The migration history has changed since this bootstrap baseline "
            "was reviewed. Update the initializer's baseline before using it."
        )
    for migration_id in migration_ids:
        module = importlib.import_module(f"migrations.{migration_id}")
        if getattr(module, "MIGRATION_ID", None) != migration_id or not callable(
            getattr(module, "upgrade", None)
        ):
            raise SetupError(
                f"Migration '{migration_id}' does not match the expected "
                "bootstrap history."
            )
    return migration_ids


def _seed_initial_data(session: Session) -> None:
    with redirect_stdout(io.StringIO()):
        for migration_id in INITIAL_DATA_MIGRATIONS:
            module = importlib.import_module(f"migrations.{migration_id}")
            module.upgrade(session)
    session.flush()


def _record_migration_baseline(connection: Any, migration_ids: tuple[str, ...]) -> None:
    """Mark the reviewed historical migrations as represented by this schema snapshot."""
    connection.exec_driver_sql(
        """
        CREATE TABLE schema_migrations (
            id SERIAL PRIMARY KEY,
            migration_id VARCHAR UNIQUE NOT NULL,
            applied_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    for migration_id in migration_ids:
        connection.execute(
            text(
                "INSERT INTO schema_migrations (migration_id, applied_at) "
                "VALUES (:migration_id, CURRENT_TIMESTAMP)"
            ),
            {"migration_id": migration_id},
        )


def _validated_user_data(
    username: str,
    email: str,
    password: str,
    user_create_model: Any,
    admin_role: Any,
) -> tuple[str, str, str]:
    username = username.strip()
    email = email.strip()

    if not password:
        raise SetupError("Password must not be empty.")
    if len(password.encode("utf-8")) > 72:
        raise SetupError("Password must not exceed 72 UTF-8 bytes.")

    try:
        email = str(TypeAdapter(EmailStr).validate_python(email))
    except ValidationError as exc:
        raise SetupError("Enter a valid email address.") from exc

    try:
        user_create_model(
            username=username,
            email=email,
            password=password,
            role=admin_role,
        )
    except ValidationError as exc:
        username_errors = {
            error["loc"][0] for error in exc.errors() if error.get("loc")
        }
        if "username" in username_errors:
            raise SetupError(
                "Username must be 3-20 characters and contain only letters, "
                "numbers, and underscores."
            ) from exc
        raise SetupError("The entered administrator details are invalid.") from exc

    return username, email, password


def _has_active_admin(session: Session, user_model: Any, admin_role: Any) -> bool:
    table = user_model.__table__
    return (
        session.exec(
            select(table.c.id)
            .where(
                table.c.role == admin_role,
                table.c.is_active.is_(True),
            )
            .limit(1)
        ).first()
        is not None
    )


def create_initial_admin(
    session: Session,
    username: str,
    email: str,
    password: str,
) -> str:
    User, UserCreate, UserRole, get_password_hash, _ = _load_application_components()

    try:
        username, email, password = _validated_user_data(
            username, email, password, UserCreate, UserRole.ADMIN
        )
        user_table = User.__table__

        if (
            session.exec(
                select(user_table.c.id)
                .where(user_table.c.username == username)
                .limit(1)
            ).first()
            is not None
        ):
            raise SetupError("That username already exists in this tenant database.")

        if (
            session.exec(
                select(user_table.c.id).where(user_table.c.email == email).limit(1)
            ).first()
            is not None
        ):
            raise SetupError(
                "That email address already exists in this tenant database."
            )

        if _has_active_admin(session, User, UserRole.ADMIN):
            raise SetupError(
                "An active administrator already exists in this tenant database."
            )

        session.execute(
            user_table.insert().values(
                username=username,
                email=email,
                password=get_password_hash(password),
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
        session.flush()
        session.commit()
        return username
    except SetupError:
        session.rollback()
        raise
    except IntegrityError as exc:
        session.rollback()
        raise SetupError(
            "Could not create the administrator because the username or email "
            "already exists."
        ) from exc
    except Exception as exc:
        session.rollback()
        raise SetupError(
            "Could not save the administrator; the database transaction was rolled back."
        ) from exc


def _prompt_for_user() -> tuple[str, str, str]:
    username = input("Administrator username: ")
    email = input("Administrator email: ")
    password = getpass.getpass("Administrator password: ")
    confirmation = getpass.getpass("Confirm password: ")

    if password != confirmation:
        raise SetupError("Passwords do not match.")
    return username, email, password


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Initialize an empty PostgreSQL tenant database from current SQLModel "
            "metadata, then create its first active ADMIN user."
        )
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help=(
            "Environment file to read (default: repository-root .env). Its "
            "DATABASE_URL takes precedence over the process environment when "
            "explicitly selected."
        ),
    )
    parser.add_argument(
        "--database-url",
        help=(
            "Explicit database URL; overrides DATABASE_URL from the environment "
            "file or process environment. Avoid placing secrets in shell history."
        ),
    )
    args = parser.parse_args()

    env_file = args.env_file or _default_env_file()
    engine = None
    try:
        database_url = _configure_environment(
            env_file,
            args.database_url,
            env_file_was_explicit=args.env_file is not None,
        )
        User, _, UserRole, _, normalize_database_url = _load_application_components()
        migration_ids = _verify_migration_baseline()
        engine = _make_engine(database_url, normalize_database_url)
        with engine.connect() as connection:
            _ensure_database_is_empty(connection)

        print(f"Target database: {_target_description(database_url)}")
        if (
            input(
                "Type INITIALIZE to confirm this is the intended empty tenant database: "
            )
            != "INITIALIZE"
        ):
            raise SetupError("Initialization cancelled; no database changes were made.")

        with engine.connect() as connection:
            with connection.begin():
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(8742201, 1)")
                _ensure_database_is_empty(connection)
                SQLModel.metadata.create_all(bind=connection)
                _create_migration_schema_objects(connection)

                with Session(
                    connection,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    _seed_initial_data(session)
                    print(
                        "Current schema and required defaults are ready in a "
                        "transaction. Create the initial administrator now."
                    )
                    username, email, password = _prompt_for_user()
                    created_username = create_initial_admin(
                        session, username, email, password
                    )

                _record_migration_baseline(connection, migration_ids)

        print(
            f"Tenant database initialized and administrator "
            f"'{created_username}' created successfully."
        )
        return 0
    except (SetupError, EOFError) as exc:
        if isinstance(exc, EOFError):
            print(
                "Setup cancelled: interactive input was unavailable.", file=sys.stderr
            )
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nSetup cancelled.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            "Initialization failed; no partial schema or administrator was "
            f"committed ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())


# Set-Location F:\2_PROJECTS\A_MMS\mzbs
# uv run python scripts\create_initial_admin.py
# uv run python scripts\create_initial_admin.py --env-file .env.newtenant
