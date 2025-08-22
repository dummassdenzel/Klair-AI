import asyncio
import sys
import os

# Add the parent directory to sys.path so we can import from ai/
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.database import engine
from sqlalchemy import text

async def verify_tables():
    print(" Verifying database tables...")
    try:
        async with engine.begin() as conn:
            # Check if tables exist
            result = await conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                AND table_name IN ('chat_sessions', 'chat_messages', 'indexed_documents')
                ORDER BY table_name
            """))
            
            tables = [row[0] for row in result.fetchall()]
            
            expected_tables = ['chat_sessions', 'chat_messages', 'indexed_documents']
            
            print(f"📋 Found tables: {tables}")
            print(f" Expected tables: {expected_tables}")
            
            missing_tables = set(expected_tables) - set(tables)
            if missing_tables:
                print(f"❌ Missing tables: {missing_tables}")
                return False
            else:
                print("✅ All expected tables found!")
                return True
                
    except Exception as e:
        print(f"❌ Error verifying tables: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(verify_tables())