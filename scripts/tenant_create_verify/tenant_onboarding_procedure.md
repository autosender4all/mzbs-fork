# Tenant Onboarding Procedure

This document captures the full tenant onboarding and verification workflow for a new school, including the control-plane setup and the final live-check steps.

## 1. Create the tenant's own Neon database

- Create a new Neon project dedicated to this school only.
- Never share a database across tenants.
- Run the full schema creation process for that database using the application's normal initialization flow, such as `create_db_and_tables()` on first connect or the existing schema process.
- Save the raw Neon connection string securely in a password manager or secure note.
- You will need this value again in step 3; do not store it in backend env vars going forward.

## 2. Register the tenant in the Control Plane via the platform-admin panel

- Use the platform-admin panel's "create tenant" flow instead of manually editing a row.
- Choose a unique `tenant_id` slug, such as `khatam_e_nabowat`.
- Use lowercase, no spaces, and confirm the slug is not reused from an older or renamed tenant.
- Fill in the required school details:
  - school name
  - contact email
  - frontend URL
  - raw Neon connection string from step 1
- The create-tenant form should route the connection string through the normal `encrypt_connection_string()` path using the current key.
- Confirm the tenant appears in the control-plane tenant list with status `provisioning`. New tenants are created in this state; the backend deliberately blocks login for `provisioning` tenants.

## 3. Run migrations against this tenant only

Run the targeted migration command for the one tenant being onboarded:

```bash
uv run python -c "from migrations.run_all_tenants import run_for_tenant, discover_migrations; run_for_tenant('<tenant_id>', '<connection_string>', discover_migrations())"
```

This is the per-tenant onboarding path for a single school and is the intended alternative to running the full fan-out across all tenants.

## 4. Seed initial data and create the admin user

- Apply the standard seed process for the new tenant, including default role permissions and initial module setup.
- Create the first real admin user for the school directly in that tenant's database.

## 5. Deploy the frontend

- In Netlify, choose "Add new site" and then "Import existing project".
- Use the same `mzbs` repository and the same build configuration used by the other tenant sites.
- Give the site a clear, unambiguous name.
- Set the frontend env vars:

```bash
NEXT_PUBLIC_API_URL=<same shared backend URL as every other tenant>
NEXT_PUBLIC_TENANT_ID=<the tenant_id from step 2, exact match>
```

- Trigger the first deploy so the tenant ID is baked into the site.

## 6. Enable login for verification

The backend allows database access only when a tenant's control-plane status is
`trial` or `active`. After migrations and admin-user setup are complete, change
the tenant from `provisioning` to `trial` in the platform-admin panel before
attempting to log in. Branding can load while the tenant is still
`provisioning`, so a visible school logo does not confirm that login is enabled.

## 7. Verify before marking fully live

- Open the site in an incognito window and log in as the new admin.
- Confirm the login request payload includes the correct `tenant_id`.
- Confirm dashboard and CRUD activity is touching the new tenant's database and not another tenant's database.
- Try a suspend/reactivate toggle from the admin panel and confirm it takes effect without restarting the backend.

## 8. Mark the tenant Active in the Control Plane

- After verification succeeds, update the tenant's status from `trial` to
  `active` in the control plane if it should be fully live.
- Once verified, the onboarding is complete.
- No backend redeploy is needed during this process.
