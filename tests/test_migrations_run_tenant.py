from types import SimpleNamespace

from migrations import run_tenant_migrations


def test_main_prompts_for_tenant_and_dry_runs_pending_migrations(monkeypatch, capsys):
    migration = SimpleNamespace(MIGRATION_ID="0001_example")
    looked_up = []
    run_args = []
    logged = []

    monkeypatch.setattr("builtins.input", lambda _prompt: "school-1")
    monkeypatch.setattr(
        run_tenant_migrations, "discover_migrations", lambda: [migration]
    )

    def lookup(tenant_id):
        looked_up.append(tenant_id)
        return "tenant-connection"

    def run_for_tenant(tenant_id, connection, migrations, dry_run=False):
        run_args.append((tenant_id, connection, migrations, dry_run))
        return {
            "tenant_id": tenant_id,
            "applied": [],
            "skipped": [],
            "pending": ["0001_example"],
            "failed": None,
        }

    monkeypatch.setattr(
        run_tenant_migrations,
        "lookup_tenant_connection_for_migration",
        lookup,
    )
    monkeypatch.setattr(run_tenant_migrations, "run_for_tenant", run_for_tenant)
    monkeypatch.setattr(
        run_tenant_migrations,
        "write_migration_run_log",
        lambda *args, **kwargs: logged.append((args, kwargs)),
    )

    exit_code = run_tenant_migrations.main(dry_run=True)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert looked_up == ["school-1"]
    assert run_args == [
        ("school-1", "tenant-connection", [migration], True)
    ]
    assert "[school-1] pending=['0001_example'] already_applied=0" in output
    assert logged == []


def test_main_rejects_unknown_migration(monkeypatch, capsys):
    migration = SimpleNamespace(MIGRATION_ID="0001_example")
    monkeypatch.setattr(
        run_tenant_migrations, "discover_migrations", lambda: [migration]
    )
    looked_up = []
    monkeypatch.setattr(
        run_tenant_migrations,
        "lookup_tenant_connection_for_migration",
        lambda tenant_id: looked_up.append(tenant_id),
    )

    exit_code = run_tenant_migrations.main(tenant="school-1", only="9999_missing")

    assert exit_code == 1
    assert "No migration found" in capsys.readouterr().err
    assert looked_up == []
