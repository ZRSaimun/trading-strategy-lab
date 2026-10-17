"""Run locally with the backend environment. Never paste provider keys into chat or a web page."""
import getpass
import os
from pathlib import Path
from cryptography.fernet import Fernet
root=Path(__file__).resolve().parents[1]/'.secrets'
if root.is_symlink():raise SystemExit('Refusing a symlinked credential directory')
root.mkdir(mode=0o700,exist_ok=True)
os.chmod(root,0o700)
master=root/'provider-master.key'
if master.is_symlink():raise SystemExit('Refusing a symlinked master key')
if not master.exists():
    fd=os.open(master,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as f:f.write(Fernet.generate_key())
key=getpass.getpass('Twelve Data API key (input hidden; local only): ')
if not key or len(key)>256 or not key.isalnum():raise SystemExit('Invalid API-key format; no credential saved')
if (root/'twelvedata.enc').exists():raise SystemExit('Credential already exists. Remove it intentionally before rotating.')
fd=os.open(root/'twelvedata.enc',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'wb') as f:f.write(Fernet(master.read_bytes()).encrypt(key.encode()))
print('Encrypted credential saved. Provider remains disabled until explicitly enabled in the private deployment.')
