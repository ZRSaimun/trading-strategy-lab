"""Small-host profile. No provider accounts, billing API or paid upgrade path."""
import os
from urllib.parse import urlsplit
from sqlalchemy.engine import make_url


def cloud_profile():
    return os.getenv('DEPLOYMENT_PROFILE') == 'free-cloud'


def validate_cloud_environment(env):
    """Return a validated child environment; never include secrets in errors."""
    result = dict(env)
    if result.get('DEPLOYMENT_PROFILE') != 'free-cloud':
        raise ValueError('Combined runtime requires DEPLOYMENT_PROFILE=free-cloud')
    try:
        url = make_url(result.get('DATABASE_URL', ''))
        if url.drivername not in ('postgresql', 'postgresql+psycopg') or not url.host:
            raise ValueError()
        if url.port == 6543:
            raise ValueError()
    except Exception:
        raise ValueError('Use a persistent PostgreSQL direct or session-pooler connection, not SQLite or transaction pooling') from None
    if result.get('DATABASE_SCHEMA') != 'tsl_private':
        raise ValueError('Free cloud requires DATABASE_SCHEMA=tsl_private')
    if result.get('FREE_ONLY', 'true').strip().lower() != 'true':
        raise ValueError('Free cloud requires FREE_ONLY=true')
    if result.get('TWELVEDATA_ENABLED', 'false').lower() != 'false':
        raise ValueError('External paid data adapter must remain disabled')
    origin = result.get('PUBLIC_ORIGIN') or result.get('RENDER_EXTERNAL_URL', '')
    try:
        parsed = urlsplit(origin)
        port = parsed.port
        if parsed.scheme != 'https' or not parsed.hostname or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username or (port is not None and port == 0):
            raise ValueError()
    except ValueError:
        raise ValueError('Set a public HTTPS origin without path, query or credentials') from None
    try:
        from argon2 import extract_parameters
        from argon2.low_level import Type
        params = extract_parameters(result.get('OWNER_PASSWORD_HASH', ''))
        if params.type != Type.ID or params.memory_cost != 65536 or not 3 <= params.time_cost <= 6 or not 1 <= params.parallelism <= 4 or params.hash_len < 16 or params.salt_len < 16:
            raise ValueError()
    except Exception:
        raise ValueError('Configure a strong Argon2id owner password hash') from None
    # Loopback-only test databases are allowed without TLS. All remote DBs verify identity.
    if url.host not in ('db', 'localhost', '127.0.0.1', '::1'):
        if url.query.get('sslmode') != 'verify-full' or not result.get('DATABASE_CA_PEM', '').startswith('-----BEGIN CERTIFICATE-----'):
            raise ValueError('Remote database requires sslmode=verify-full and DATABASE_CA_PEM')
    port = result.get('PORT', '10000')
    if not port.isascii() or not port.isdecimal() or not 1024 <= int(port) <= 65535 or int(port) in (8000, 18012, 18013, 19099):
        raise ValueError('Choose a non-reserved public port from 1024 to 65535')
    result.update(PUBLIC_ORIGIN=origin.rstrip('/'), COOKIE_SECURE='true', FREE_ONLY='true',
                  TWELVEDATA_ENABLED='false', AUTO_CREATE_SCHEMA='false',
                  API_INTERNAL_URL='http://127.0.0.1:8000', PORT=port,
                  HOSTNAME='0.0.0.0', NODE_OPTIONS='--max-old-space-size=128',
                  NEXT_TELEMETRY_DISABLED='1')
    return result
