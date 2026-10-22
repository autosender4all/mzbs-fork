from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()

TENANT_ID = "greenwood-khanschool"
# TENANT_ID = "bwhs"  
# TENANT_ID = "mzbs" 
# Tenant_id = "mzbs_staging_school" 
# Change the tenant name above to "any other tenant_id" if you want to re-encrypt a different tenant's db_connection_secret. The script will still only ever touch that one row.

database_url = os.getenv("CONTROL_PLANE_DATABASE_URL")
encryption_key = os.getenv("CONTROL_PLANE_ENCRYPTION_KEY")
missing_settings = [
    name
    for name, value in (
        ("CONTROL_PLANE_DATABASE_URL", database_url),
        ("CONTROL_PLANE_ENCRYPTION_KEY", encryption_key),
    )
    if not value
]
if missing_settings:
    raise RuntimeError(
        "Missing required environment setting(s): "
        + ", ".join(missing_settings)
        + ". Add them to .env or set them in the shell before running this script."
    )

engine = create_engine(database_url)
fernet = Fernet(encryption_key.encode())

with engine.connect() as conn:
    row = conn.execute(text("SELECT db_connection_secret, status FROM tenants WHERE tenant_id = :tid"), {"tid": TENANT_ID}).first()

print("status:", row[1])
try:
    fernet.decrypt(row[0].encode())
    print("Decryption OK")
except Exception as e:
    print("Decryption FAILED:", type(e).__name__, str(e))