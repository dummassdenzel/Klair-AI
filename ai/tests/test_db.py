import asyncio
import sys
import os

# Add the parent directory to sys.path so we can import from ai/
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.database import test_connection, engine
from sqlalchemy import text

async def test_async_connection():
    print("🔍 Testing async database connection...")
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"✅ Async connection successful!")
            print(f" PostgreSQL version: {version}")
            return True
    except Exception as e:
        print(f"❌ Async connection failed: {e}")
        return False

async def test_sync_connection():
    print("\n🔍 Testing sync database connection (for Alembic)...")
    try:
        # Test with psycopg2 directly
        import psycopg2
        from config import settings
        
        # Convert to sync URL
        sync_url = settings.DATABASE_URL
        if sync_url.startswith('postgresql+asyncpg://'):
            sync_url = sync_url.replace('postgresql+asyncpg://', 'postgresql://')
        
        # Parse connection string
        import urllib.parse
        parsed = urllib.parse.urlparse(sync_url)
        
        conn = psycopg2.connect(
            host=parsed.hostname,
            port=parsed.port,
            database=parsed.path[1:],  # Remove leading '/'
            user=parsed.username,
            password=parsed.password
        )
        
        cursor = conn.cursor()
        cursor.execute("SELECT version()")
        version = cursor.fetchone()[0]
        print(f"✅ Sync connection successful!")
        print(f" PostgreSQL version: {version}")
        
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Sync connection failed: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Starting database connection tests...\n")
    
    # Test both connections
    async_results = asyncio.run(test_async_connection())
    sync_results = asyncio.run(test_sync_connection())
    
    if async_results and sync_results:
        print("\n🎉 All database connections working!")
    else:
        print("\n💥 Some connections failed. Check your configuration.")