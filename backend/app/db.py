import os
from sqlalchemy import create_engine, event, String, Integer, Float, Text, UniqueConstraint
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

class Base(DeclarativeBase):
    pass

DATABASE_SCHEMA = os.getenv('DATABASE_SCHEMA', '')
if DATABASE_SCHEMA not in ('', 'tsl_private'):
    raise ValueError('DATABASE_SCHEMA must be empty or tsl_private')
url = make_url(os.getenv("DATABASE_URL", "sqlite:///./lab.db"))
if url.drivername == 'postgresql':
    url = url.set(drivername='postgresql+psycopg')
if DATABASE_SCHEMA and url.get_backend_name() != 'postgresql':
    raise ValueError('Private schema requires PostgreSQL')
options = {}
if url.get_backend_name() == 'postgresql':
    options = dict(pool_pre_ping=True, pool_size=2, max_overflow=0, pool_timeout=10,
                   connect_args={'connect_timeout': 10})
engine = create_engine(url, **options)
if DATABASE_SCHEMA:
    @event.listens_for(engine, 'begin')
    def private_transaction(connection):
        # Every transaction sets its own path; never fall back to public tables.
        connection.exec_driver_sql('SET LOCAL search_path TO tsl_private')
        connection.exec_driver_sql("SET LOCAL statement_timeout TO '30s'")
Session = sessionmaker(engine)

class Record(Base):
    __tablename__ = "records"
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    value: Mapped[str] = mapped_column(Text)

class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (UniqueConstraint("instrument", "time"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    instrument: Mapped[str] = mapped_column(String(80), index=True)
    time: Mapped[int] = mapped_column(Integer, index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(160))
    retrieved_at: Mapped[int] = mapped_column(Integer)

class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    time: Mapped[int] = mapped_column(Integer)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(80))
    detail: Mapped[str] = mapped_column(Text)
