"""
One-off corrective script: re-encrypt the `mzbs` tenant's db_connection_secret
in the Control Plane database using the CURRENT CONTROL_PLANE_ENCRYPTION_KEY.

Why this is needed:
    tenant_lookup.py's lookup_tenant_connection() raised InvalidToken when
    decrypting mzbs's stored secret -- meaning it was encrypted with a
    different key than what's currently set as CONTROL_PLANE_ENCRYPTION_KEY.
    This script overwrites just that one row's db_connection_secret with a
    freshly-encrypted value, using the CURRENT key, so future decryption
    succeeds.

Safety:
    - Only ever touches the single row matching TENANT_ID below.
    - Prints the existing (masked) value and the tenant's current status
      before writing anything.
    - Requires explicit "yes" confirmation before committing.
    - Does not touch status, school_name, contact_email, or any other column.

Run this locally, pointed at PRODUCTION Control Plane env vars
(CONTROL_PLANE_DATABASE_URL, CONTROL_PLANE_ENCRYPTION_KEY) -- the same
values Northflank currently has set. Do NOT run this against staging by
accident; the script prints the DB host it's connecting to up front so
you can double check before confirming.
"""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

TENANT_ID = "greenwood-khanschool"
# # TENANT_ID = "mzbs_staging_school" 
# TENANT_ID = "bwhs"  
# TENANT_ID = "mzbs" 

# Change the tenant name above to "any other tenant_id" if you want to re-encrypt a different tenant's db_connection_secret. The script will still only ever touch that one row.
# ---------------------------------------------------------------------------
# 1. Load env vars from the project .env or the current shell, matching
#    exactly what Northflank has for production.
# ---------------------------------------------------------------------------
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

CONTROL_PLANE_DATABASE_URL = os.environ.get("CONTROL_PLANE_DATABASE_URL")
CONTROL_PLANE_ENCRYPTION_KEY = os.environ.get("CONTROL_PLANE_ENCRYPTION_KEY")

missing_settings = [
    name
    for name, value in (
        ("CONTROL_PLANE_DATABASE_URL", CONTROL_PLANE_DATABASE_URL),
        ("CONTROL_PLANE_ENCRYPTION_KEY", CONTROL_PLANE_ENCRYPTION_KEY),
    )
    if not value
]
if missing_settings:
    print(
        "ERROR: Missing required setting(s): "
        + ", ".join(missing_settings)
        + ". Add them to the project .env or set them in the shell."
    )
    sys.exit(1)

fernet = Fernet(CONTROL_PLANE_ENCRYPTION_KEY.encode())
engine = create_engine(
    CONTROL_PLANE_DATABASE_URL,
    connect_args={"connect_timeout": 10},
    pool_pre_ping=True,  # test/refresh a pooled connection before using it,
                         # so a stale connection (e.g. from time spent at
                         # the input() prompts below) doesn't cause a
                         # "SSL connection has been closed unexpectedly"
                         # error on the final UPDATE.
)

parsed_host = urlparse(CONTROL_PLANE_DATABASE_URL).hostname
print(f"Connecting to Control Plane DB host: {parsed_host}")
print(f"Target tenant_id: {TENANT_ID}")
print()

# ---------------------------------------------------------------------------
# 2. Fetch current row, show status + masked existing secret
# ---------------------------------------------------------------------------
with engine.connect() as conn:
    row = conn.execute(
        text("SELECT db_connection_secret, status, school_name FROM tenants WHERE tenant_id = :tid"),
        {"tid": TENANT_ID},
    ).first()

if not row:
    print(f"ERROR: No tenant found with tenant_id = '{TENANT_ID}'. Aborting, nothing changed.")
    sys.exit(1)

old_encrypted_secret, current_status, school_name = row
masked_old = old_encrypted_secret[:12] + "..." + old_encrypted_secret[-6:]

print(f"School name:        {school_name}")
print(f"Current status:     {current_status}")
print(f"Current secret (masked): {masked_old}")
print()

# ---------------------------------------------------------------------------
# 3. Prompt for the correct raw connection string (never hardcoded in this
#    file, and never printed back out in full below)
# ---------------------------------------------------------------------------
raw_conn_str = input(
    "Paste the CORRECT raw Neon connection string for mzbs's production DB: "
).strip()

if not raw_conn_str or "://" not in raw_conn_str:
    print("That doesn't look like a valid connection string. Aborting, nothing changed.")
    sys.exit(1)

new_host = urlparse(raw_conn_str).hostname
print()
print(f"New connection string points to host: {new_host}")

# Round-trip sanity check: encrypt then immediately decrypt with the same
# key, so we never write something we can't read back.
new_encrypted_secret = fernet.encrypt(raw_conn_str.encode()).decode()
roundtrip_check = fernet.decrypt(new_encrypted_secret.encode()).decode()
assert roundtrip_check == raw_conn_str, "Round-trip encryption check failed -- aborting."
print("Round-trip encrypt/decrypt check: OK")
print()

# ---------------------------------------------------------------------------
# 4. Explicit confirmation before writing
# ---------------------------------------------------------------------------
confirm = input(
    f"About to OVERWRITE db_connection_secret for tenant_id='{TENANT_ID}' "
    f"(school: {school_name}, status: {current_status}) with a freshly "
    f"encrypted value pointing at host '{new_host}'.\n"
    f"Type 'yes' to proceed: "
).strip().lower()

if confirm != "yes":
    print("Not confirmed. Aborting, nothing changed.")
    sys.exit(0)

with engine.begin() as conn:
    result = conn.execute(
        text("UPDATE tenants SET db_connection_secret = :secret, updated_at = now() WHERE tenant_id = :tid"),
        {"secret": new_encrypted_secret, "tid": TENANT_ID},
    )

print()
print(f"Done. Rows updated: {result.rowcount}")
print(f"tenant_id '{TENANT_ID}' db_connection_secret re-encrypted with current CONTROL_PLANE_ENCRYPTION_KEY.")
print("Next: re-run your encryption_test.py check to confirm decryption now succeeds.")
