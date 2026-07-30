from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.config import settings
from app.models import Base

# Database engine with connection pooling and health checks
# pool_pre_ping ensures stale connections are recycled
# Default isolation level: READ COMMITTED (PostgreSQL default)
# This provides optimal balance between consistency and performance
# MVCC handles concurrent transactions without explicit locking
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
