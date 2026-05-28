from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from circuit_worker.config import config

# Worker uses sync driver - strip asyncpg if present
db_url = config.DATABASE_URL
if "+asyncpg" in db_url:
    db_url = db_url.replace("+asyncpg", "")

engine = create_engine(db_url, echo=False)
SessionLocal = sessionmaker(bind=engine)


def get_session() -> Session:
    return SessionLocal()
