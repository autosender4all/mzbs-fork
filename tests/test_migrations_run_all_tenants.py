from contextlib import nullcontext
from types import SimpleNamespace

from migrations import run_all_tenants


def test_main_continues_after_tenant_connection_lookup_failure(monkeypatch, capsys):
    tenants = [
        SimpleNamespace(tenant_id="tenant-1", status="active"),
        SimpleNamespace(tenant_id="tenant-2", status="active"),
        SimpleNamespace(tenant_id="tenant-3", status="active"),
    ]
    checked_tenants = []

    monkeypatch.setattr(run_all_tenants, "discover_migrations", lambda: [])
    monkeypatch.setattr(run_all_tenants, "get_control_plane_session", nullcontext)
    monkeypatch.setattr(run_all_tenants, "list_tenants", lambda _session: tenants)

    def lookup_connection(tenant_id):
        if tenant_id == "tenant-2":
            raise ValueError("invalid encrypted connection secret")
        return f"connection-{tenant_id}"

    def run_tenant(tenant_id, _conn_str, _migrations, dry_run=False):
        checked_tenants.append(tenant_id)
        return {
            "tenant_id": tenant_id,
            "applied": [],
            "skipped": [],
            "pending": [],
            "failed": None,
        }

    monkeypatch.setattr(run_all_tenants, "lookup_tenant_connection", lookup_connection)
    monkeypatch.setattr(run_all_tenants, "run_for_tenant", run_tenant)

    exit_code = run_all_tenants.main(dry_run=True)

    output = capsys.readouterr().out
    assert exit_code == 1
    assert checked_tenants == ["tenant-1", "tenant-3"]
    assert "[tenant-2] FAILED: ValueError: invalid encrypted connection secret" in output
    assert "pending=[] already_applied=0" in output
    assert "!! ERROR" not in output
    assert "Dry run incomplete: resolve the tenant errors above" in output
    assert "migration_run_log" not in output
    assert "Done." not in output
