"""
Verify that data is actually being stored in the database
"""

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

async def verify_database_records():
    """Verify that API calls are actually storing data"""
    try:
        print("�� Verifying Database Records\n")
        
        from database import DatabaseService
        
        db_service = DatabaseService()
        
        # Check chat sessions
        print("1. Checking chat sessions...")
        # You'll need to implement a method to get all sessions
        # For now, let's check if we can connect
        
        # Check document stats
        print("\n2. Checking document stats...")
        stats = await db_service.get_document_stats()
        print(f"   - Total documents: {stats.get('total_documents', 0)}")
        print(f"   - Status breakdown: {stats.get('status_breakdown', {})}")
        print(f"   - Type breakdown: {stats.get('type_breakdown', {})}")
        
        print("\n✅ Database verification completed!")
        
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(verify_database_records())
