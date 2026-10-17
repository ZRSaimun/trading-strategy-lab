import os
from sqlalchemy import create_engine, String, Integer, Float, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

class Base(DeclarativeBase):
    pass

engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///./lab.db"))
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
