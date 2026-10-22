# Migration Runbook

Applies to every schema change from Phase 4 onward — one FastAPI backend,
dozens of independent tenant Postgres databases, no shared DB.

## Golden rules, in order

1. **Test against the staging tenant first, always.**
   `mzbs-staging-school` (from Phase 0) is the canary. Use its exact
   `tenant_id` from the control plane; tenant IDs are matched exactly. Never
   run a new migration against a real school's database before it has run
   cleanly here:
   ```bash
   uv run python -m migrations.run_all_tenants --tenant <staging_tenant_id>
   ```

2. **Dry-run across all active tenants before any real run.**
   ```bash
   uv run python -m migrations.run_all_tenants --dry-run
   ```
   This checks every tenant whose control-plane status is `active`. Read the
   `pending=[...]` list per tenant. If any tenant shows something unexpected
   (e.g. a migration you thought was already applied everywhere), stop and
   investigate before proceeding — don't run for real "to see what happens."
   Dry-run does not execute migration upgrades or write run-log entries, but
   it does create the tenant's `schema_migrations` table if that table is
   missing.

3. **Apply to all active tenants only after reviewing the dry-run output.**
   ```bash
   uv run python -m migrations.run_all_tenants
   ```
   This applies every pending migration to each active tenant. Already-applied
   migrations are skipped. For a risky migration, use `--only` and follow the
   staged procedure below instead of applying the full pending set.

4. **Use `--only` for risky or multi-phase migrations.**
   The classic case is a Postgres native enum change (adding a new `UserRole`
   value), which must happen in separate steps that can't be undone within
   one transaction:
   - Step A: `ALTER TYPE userrole ADD VALUE 'NEW_ROLE'`
   - Step B: any data backfill/UPDATE that depends on the new value existing
   - Step C: any follow-up cleanup

   Run each step as its own migration file, applied with `--only`, checking
   tenant health between steps — not all three back-to-back with no checkpoint:
   ```bash
   uv run python -m migrations.run_all_tenants --only 0007_add_new_role_enum_value
   # check things look right
   uv run python -m migrations.run_all_tenants --only 0008_backfill_new_role_data
   ```

5. **After a real run, check `migration_run_log` for `failed` rows.**
   ```sql
   SELECT * FROM migration_run_log WHERE status = 'failed' ORDER BY run_at DESC;
   ```
   Investigate and fix the underlying cause before re-running. Do not
   blindly re-run the whole fan-out hoping it works the second time —
   `run_for_tenant()` is idempotent per-migration, but a failure usually
   means something tenant-specific needs a look (e.g. unexpected existing
   data shape, a locked table, a connectivity blip worth distinguishing
   from a real schema conflict).

## Verify and apply one migration on selected tenants

Use `--dry-run` to check whether a migration is pending. It does not apply
the migration. Add `--tenant` to limit the check to one exact tenant ID, or
omit it to check all active tenants.

Check migration `0015_add_user_active_and_teacher_delete_metadata` across all
active tenants:

```bash
uv run python -m migrations.run_all_tenants --dry-run --only 0015_add_user_active_and_teacher_delete_metadata
```

Check all pending migrations for one tenant:

```bash
uv run python -m migrations.run_all_tenants --dry-run --tenant <tenant_id>
```

Check one migration for one tenant without applying it:

```bash
uv run python -m migrations.run_all_tenants --dry-run --only <migration_id> --tenant <tenant_id>
```

After reviewing the dry-run output and confirming the tenant ID, apply only
that migration to the staging tenant:

```bash
uv run python -m migrations.run_all_tenants --only 0015_add_user_active_and_teacher_delete_metadata --tenant mzbs_staging_school
```

The last command is a live schema change, not a verification command. For a
different tenant, replace `mzbs_staging_school` with its exact control-plane
`tenant_id`; use this only after the staging run succeeds and the change is
approved for that tenant.

6. **Never delete or renumber an already-applied migration file.**
   `schema_migrations` (inside each tenant DB) references files by
   `migration_id`, and onboarding a brand-new school (#2, #3, ... #50) means
   running the *entire* historical sequence against a fresh empty database.
   Deleting an old file breaks that school's onboarding, not just historical
   record-keeping.

7. **One tenant's failure never blocks another tenant's run.**
   Tenant connection lookup/decryption and migration execution failures are
   reported against that tenant and do not stop the loop. A dry-run exits
   nonzero if any active tenant could not be checked; resolve the reported
   tenant-specific error before treating the run as a complete check. If
   decryption fails, verify that `CONTROL_PLANE_ENCRYPTION_KEY` matches the
   key used to encrypt that tenant's `db_connection_secret` and that the
   stored value is valid.

## Retrying a single failed tenant

```bash
uv run python -m migrations.run_all_tenants --tenant <tenant_id>
```
This re-runs the full pending set for just that tenant. Because
`schema_migrations` tracks per-migration application, anything that already
succeeded for that tenant is skipped — only the genuinely pending/failed ones
re-apply.

To run pending migrations for one tenant by ID, including a tenant still in
`provisioning` status:

```bash
uv run python -m migrations.run_tenant_migrations --tenant <tenant_id> --dry-run
uv run python -m migrations.run_tenant_migrations --tenant <tenant_id>
```

Omit `--tenant` to be prompted for the ID. Review the dry-run output before
running migrations. This command does not activate the tenant; activate it only
after onboarding checks have passed.

## Onboarding a brand-new school (manual, per Phase 0/2 decisions)

1. Create the new Neon project, empty.
2. Add the tenant to the control plane (`tenants` table) with status
   `provisioning`.
3. Run the full migration history against it:
   ```bash
   uv run python -m migrations.run_tenant_migrations --tenant <new_tenant_id> --dry-run
   uv run python -m migrations.run_tenant_migrations --tenant <new_tenant_id>
   ```
4. Verify manually (log in as a seeded test user, exercise each module).
5. Flip status to `active` in the control plane.
6. Deploy the new school's frontend with its `NEXT_PUBLIC_TENANT_ID` set.

## Quick reference

| Command | Effect |
|---|---|
| `--dry-run` | Show pending migrations per active tenant; does not run upgrades or write run-log rows, but may create a missing `schema_migrations` table |
| `--only <migration_id>` | Restrict the run to one migration across all active tenants |
| `--tenant <tenant_id>` | Restrict the run to one tenant across all pending migrations |
| `--only ... --tenant ...` | Combine both — one migration, one tenant (rare, mostly for a targeted retry) |

## Checklist before merging any change to `migrations/run_all_tenants.py` or `runner_core.py`

- [ ] Dry-run mode still shows accurate pending lists
- [ ] Staging tenant used for the change itself before trusting it
- [ ] `--only` still correctly restricts to a single migration
- [ ] A deliberately-failing migration on one tenant does not stop the others
- [ ] Re-running the same fan-out twice produces zero duplicate applications
- [ ] `migration_run_log` rows are written correctly for both `applied` and `failed`
