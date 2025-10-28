from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from config import settings
from sqlalchemy import text

# SQLAlchemy Base class for models
Base = declarative_base()

# Create engine from .env DATABASE_URL
async_database_url = settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://')
engine = create_async_engine(async_database_url, echo=settings.SQLALCHEMY_ECHO)

# Create a session factory
AsyncSessionLocal = sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

# Dependency for FastAPI routes
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def test_connection():
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            print("✅ Database connected! Result:", result.scalar())
    except Exception as e:
        print("❌ Database connection failed:", e)