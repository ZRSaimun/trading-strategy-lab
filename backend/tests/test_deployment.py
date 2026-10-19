from argon2 import PasswordHasher
import pytest
from app.deployment import validate_cloud_environment
from app.market import parse_csv
from test_foundation import client, unlock, CSV


@pytest.fixture
def environment():
    return dict(DEPLOYMENT_PROFILE='free-cloud', DATABASE_URL='postgresql://lab:test@db/lab',
                DATABASE_SCHEMA='tsl_private', RENDER_EXTERNAL_URL='https://lab.example',
                OWNER_PASSWORD_HASH=PasswordHasher().hash('software-test-only-password'))


def test_free_cloud_enforces_secure_runtime_and_small_node_heap(environment):
    env = validate_cloud_environment(environment)
    assert env['COOKIE_SECURE'] == 'true'
    assert env['PUBLIC_ORIGIN'] == 'https://lab.example'
    assert env['FREE_ONLY'] == 'true' and env['TWELVEDATA_ENABLED'] == 'false'
    assert env['API_INTERNAL_URL'] == 'http://127.0.0.1:8000'
    assert env['NODE_OPTIONS'] == '--max-old-space-size=128'
    assert 'COOKIE_SECURE' not in environment


@pytest.mark.parametrize('key,value',[
    ('DATABASE_URL','sqlite:///lost-on-restart.db'),
    ('DATABASE_URL','postgresql://lab:secret@db:6543/lab'),
    ('DATABASE_SCHEMA','public'), ('FREE_ONLY','false'), ('FREE_ONLY','unknown'),
    ('TWELVEDATA_ENABLED','true'), ('RENDER_EXTERNAL_URL','http://lab.example'),
    ('RENDER_EXTERNAL_URL','https://lab.example/path'),
    ('OWNER_PASSWORD_HASH','plaintext-secret'), ('PORT','8000'), ('PORT','19099'), ('PORT','0'),
])
def test_cloud_configuration_fails_closed_without_echoing_secrets(environment,key,value):
    environment[key] = value
    with pytest.raises(ValueError) as error:
        validate_cloud_environment(environment)
    assert 'plaintext-secret' not in str(error.value)
    assert 'lab:secret' not in str(error.value)


def test_remote_database_requires_certificate_and_identity_verification(environment):
    environment['DATABASE_URL'] = 'postgresql://lab:test@database.example/lab?sslmode=require'
    with pytest.raises(ValueError): validate_cloud_environment(environment)
    environment['DATABASE_URL'] = 'postgresql://lab:test@database.example/lab?sslmode=verify-full'
    with pytest.raises(ValueError): validate_cloud_environment(environment)
    environment['DATABASE_CA_PEM'] = '-----BEGIN CERTIFICATE-----\nfixture-not-a-real-certificate'
    assert validate_cloud_environment(environment)['DATABASE_CA_PEM']
    # Actual certificate verification belongs to psycopg at connection time.


def test_profile_import_limit_is_atomic_and_standard_profile_is_unchanged(client,monkeypatch):
    unlock(client)
    fields=dict(instrument='XAUUSD-IMPORT',source='Software fixture only',rights_confirmed='true')
    assert client.post('/api/import',data=fields,files={'file':('test.csv',CSV)}).status_code == 200
    monkeypatch.setenv('DEPLOYMENT_PROFILE','free-cloud')
    assert client.get('/api/health').json()['profile'] == 'free-cloud'
    oversized = client.post('/api/import',data=fields,files={'file':('test.csv',b'x'*2_000_001)})
    assert oversized.status_code == 413
    assert client.get('/api/candles/XAUUSD-IMPORT').json()['dataset']['rows'] == 3
    with pytest.raises(ValueError,match='Maximum 2 rows'):
        parse_csv(CSV,max_rows=2)
    assert len(parse_csv(CSV)) == 3


def test_cloud_password_memory_is_serialized(client,monkeypatch):
    from app.main import login_memory_lock
    monkeypatch.setenv('DEPLOYMENT_PROFILE','free-cloud')
    with login_memory_lock:
        assert client.post('/api/login',json={'password':'correct-horse-private-lab'}).status_code == 429
    unlock(client)
