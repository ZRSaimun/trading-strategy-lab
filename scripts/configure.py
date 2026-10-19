"""Interactive owner configuration. Never prints the password or hash."""
import getpass
import os
import secrets
from pathlib import Path
from argon2 import PasswordHasher
p=Path(__file__).resolve().parents[1]/".env"
if p.exists():
    raise SystemExit(".env exists; edit intentionally rather than overwriting credentials")
password=getpass.getpass("Owner password (minimum 14 characters): ")
if len(password)<14 or password!=getpass.getpass("Confirm password: "):
    raise SystemExit("Password too short or confirmation mismatch")
# Single quotes stop Compose from interpolating Argon2's dollar signs.
content="POSTGRES_PASSWORD="+secrets.token_hex(32)+"\nOWNER_PASSWORD_HASH='"+PasswordHasher().hash(password)+"'\nPUBLIC_ORIGIN=http://localhost:3000\nCOOKIE_SECURE=false\nFREE_ONLY=true\n"
fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,"w") as f:f.write(content)
print("Configuration created. Run docker compose up --build -d")
