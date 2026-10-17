"""Encrypted local credential files; never expose plaintext through an API."""
import os
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken

class CredentialUnavailable(Exception):
    pass

def load_key():
    try:
        master=Path(os.environ['PROVIDER_MASTER_KEY_FILE']).read_bytes().strip()
        encrypted=Path(os.environ['TWELVEDATA_KEY_FILE']).read_bytes()
        secret=Fernet(master).decrypt(encrypted).decode('ascii')
        if not secret or len(secret)>256 or not secret.isalnum():
            raise CredentialUnavailable('Invalid credential format')
        return secret
    except (OSError,KeyError,ValueError,UnicodeError,InvalidToken) as e:
        raise CredentialUnavailable('Provider credential is unavailable') from None

def configured():
    try:
        load_key();return True
    except CredentialUnavailable:
        return False
