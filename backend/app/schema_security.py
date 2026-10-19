"""Private database namespace; browser Data API roles receive no grants."""
from sqlalchemy import text


def prepare_private_schema(connection):
    connection.exec_driver_sql('CREATE SCHEMA IF NOT EXISTS tsl_private')
    connection.exec_driver_sql('REVOKE ALL ON SCHEMA tsl_private FROM PUBLIC')


def harden_private_schema(connection):
    roles = ['PUBLIC']
    for role in ('anon', 'authenticated'):
        if connection.execute(text('SELECT 1 FROM pg_roles WHERE rolname=:role'), {'role': role}).scalar():
            roles.append(role)
    for role in roles:
        # Names are a fixed allowlist, not interpolated user input.
        connection.exec_driver_sql(f'REVOKE ALL ON SCHEMA tsl_private FROM {role}')
        connection.exec_driver_sql(f'REVOKE ALL ON ALL TABLES IN SCHEMA tsl_private FROM {role}')
        connection.exec_driver_sql(f'REVOKE ALL ON ALL SEQUENCES IN SCHEMA tsl_private FROM {role}')
        connection.exec_driver_sql(f'ALTER DEFAULT PRIVILEGES IN SCHEMA tsl_private REVOKE ALL ON TABLES FROM {role}')
        connection.exec_driver_sql(f'ALTER DEFAULT PRIVILEGES IN SCHEMA tsl_private REVOKE ALL ON SEQUENCES FROM {role}')
    for table in ('records', 'candles', 'audit', 'alembic_version'):
        connection.exec_driver_sql(f'ALTER TABLE tsl_private.{table} ENABLE ROW LEVEL SECURITY')
    # Server connects as schema/table owner. No policies grant browser roles access.
