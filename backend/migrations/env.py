from alembic import context
from app.db import engine, Base, DATABASE_SCHEMA
from app.bulk_import import metadata as historical_metadata
from app.schema_security import prepare_private_schema, harden_private_schema
with engine.begin() as connection:
    if DATABASE_SCHEMA:
        prepare_private_schema(connection)
    context.configure(connection=connection,target_metadata=[Base.metadata, historical_metadata],
                      version_table_schema=DATABASE_SCHEMA or None)
    with context.begin_transaction():
        context.run_migrations()
    if DATABASE_SCHEMA:
        harden_private_schema(connection)
