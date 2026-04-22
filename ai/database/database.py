from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import event, text
from config import settings
import logging

logger = logging.getLogger(__name__)

Base = declarative_base()


def _build_engine():
    """Build the async engine for the configured DATABASE_URL."""
    url = settings.DATABASE_URL
    is_sqlite = url.startswith("sqlite")

    if is_sqlite:
        if "aiosqlite" not in url and "+aiosqlite" not in url:
            url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)
        eng = create_async_engine(
            url,
            echo=settings.SQLALCHEMY_ECHO,
            connect_args={"check_same_thread": False},
        )
    else:
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        eng = create_async_engine(url, echo=settings.SQLALCHEMY_ECHO)

    return eng, is_sqlite


engine, _is_sqlite = _build_engine()

if _is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def create_tables():
    """Create all tables if they don't exist (used on startup for SQLite)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured")


async def test_connection():
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            logger.info(f"Database connected: {result.scalar()}")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
