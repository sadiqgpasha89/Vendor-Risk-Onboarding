"""Database connection and session management."""

from sqlalchemy import create_engine, event, pool
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from src.config.settings import settings

# Create engine
engine = create_engine(
    settings.database.url,
    poolclass=pool.QueuePool,
    pool_size=settings.database.pool_size,
    max_overflow=settings.database.max_overflow,
    pool_timeout=settings.database.pool_timeout,
    echo=settings.database.echo,
    connect_args={
        "connect_timeout": 10,
        "application_name": settings.app_name,
    },
)

# Create session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db() -> Generator[Session, None, None]:
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables."""
    from src.db.models import Base
    Base.metadata.create_all(bind=engine)


def drop_db():
    """Drop all database tables."""
    from src.db.models import Base
    Base.metadata.drop_all(bind=engine)


# Connection pooling and optimization
@event.listens_for(engine, "connect")
def receive_connect(dbapi_conn, connection_record):
    """Configure connection on connect."""
    if "postgresql" in settings.database.url:
        cursor = dbapi_conn.cursor()
        cursor.execute("SET SESSION default_transaction_isolation = READ COMMITTED")
        cursor.close()


@event.listens_for(pool.Pool, "connect")
def receive_pool_connect(dbapi_conn, connection_record):
    """Configure connection pool."""
    if hasattr(dbapi_conn, "set_isolation_level"):
        dbapi_conn.set_isolation_level(1)  # READ_COMMITTED
