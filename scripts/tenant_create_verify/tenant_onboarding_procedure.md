# Tenant Onboarding Procedure

This document describes how to initialize a new tenant database, create its
first administrator, check its connection secret, and apply pending migrations.

## 1. Create the tenant database

- Create a new, empty PostgreSQL database dedicated to this school.
- Never share a database across tenants.
- Save its raw connection string securely. Do not commit it or paste it into
  source code.

## 2. Register the tenant in the Control Plane

- Use the platform-admin panel's tenant-creation flow.
- Choose a unique, lowercase `tenant_id` slug with no spaces.
- Enter the school details and the database connection string.
- Confirm the connection string is encrypted by the normal
  `encrypt_connection_string()` path using the current
  `CONTROL_PLANE_ENCRYPTION_KEY`.
- Confirm the tenant is registered with status `provisioning`.

## 3. Optional: verify the saved connection secret

From the repository root in PowerShell:

```powershell
Set-Location F:\2_PROJECTS\A_MMS\mzbs
F:\2_PROJECTS\A_MMS\mzbs\.venv\Scripts\python.exe scripts\tenant_create_verify\encryption_test.py
```

Before running, set `TENANT_ID` in `encryption_test.py` to the new tenant ID.
The script reports whether the stored secret can be decrypted; it does not
change the Control Plane or tenant database.

## 4. Initialize the tenant and create its first admin

Create a tenant-specific environment file such as `.env.newtenant` containing
the tenant database's `DATABASE_URL`, then run from the repository root:

```powershell
F:\2_PROJECTS\A_MMS\mzbs\.venv\Scripts\python.exe scripts\create_initial_admin.py --env-file .env.newtenant
```

The script requires an empty PostgreSQL database, creates its schema and
required defaults, prompts for confirmation, creates the first administrator,
and records its reviewed migration baseline. Run it only once for that new
tenant database. Do not rerun it to apply later migrations.

## 5. Check and apply pending migrations for this tenant

First do a dry run:

```powershell
F:\2_PROJECTS\A_MMS\mzbs\.venv\Scripts\python.exe -m migrations.run_tenant_migrations --tenant <tenant_id> --dry-run
```

If it reports pending migrations and no errors, apply them:

```powershell
F:\2_PROJECTS\A_MMS\mzbs\.venv\Scripts\python.exe -m migrations.run_tenant_migrations --tenant <tenant_id>
```

This script resolves the database connection using the tenant ID, checks
`schema_migrations`, skips recorded IDs, and applies only unrecorded migrations.
It supports tenants in `provisioning` status and does not activate the tenant.
Do not expect it to replay migration IDs already recorded by the initializer.

For example, the tenant `bwhs` was initialized and its dry run reported all 16
migrations already applied and none pending. In that case, do not run the live
migration command; continue with verification.

## 6. Repair a connection secret only if necessary

The repair script overwrites the stored database connection secret for the
tenant ID hard-coded in the script. It is not part of routine onboarding.
Before using it, verify that:

- `TENANT_ID` in the script is the intended tenant.
- The repository-root `.env` points to the intended Control Plane.
- The database URL entered at the prompt belongs to that tenant.
- You have verified the encryption key is the one currently used by the
  application.

Run from the repository root only when a repair is required:

```powershell
F:\2_PROJECTS\A_MMS\mzbs\.venv\Scripts\python.exe scripts\tenant_create_verify\fix_mzbs_connection_secret.py
```

Review the displayed Control Plane host and tenant details, and only type
`yes` after confirming the target. Then rerun the encryption check and the
migration dry run.

## 7. Deploy the frontend

- In Netlify, choose **Add new site** and then **Import existing project**.
- Use the same `mzbs` repository and build configuration as the other tenant
  sites.
- Set the frontend environment variables:

```text
NEXT_PUBLIC_API_URL=<shared backend URL>
NEXT_PUBLIC_TENANT_ID=<exact tenant_id from the Control Plane>
```

- Trigger the first deploy so the tenant ID is baked into the site.

## 8. Enable login and verify the tenant

The backend allows database access only when the Control Plane status is
`trial` or `active`. After initialization and migrations are complete, change
the tenant from `provisioning` to `trial` in the platform-admin panel before
attempting login.

- Open the site in an incognito window and log in as the new admin.
- Confirm the login request includes the correct `tenant_id`.
- Confirm dashboard and CRUD activity uses the new tenant's database.
- Verify expected modules and data.

## 9. Mark the tenant active

After verification succeeds, change the tenant status from `trial` to `active`
if it should be fully live. No backend redeploy is needed for this process.
