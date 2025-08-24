"""
Test script for database integration
"""

import asyncio
import sys
from pathlib import Path

# Add the current directory to the path for imports
sys.path.append(str(Path(__file__).parent))

async def test_database_service():
    """Test the database service layer"""
    try:
        print("🧪 Testing Database Service Layer\n")
        
        # Test 1: Import database components
        print("1. Testing imports...")
        from database import DatabaseService
        from database.models import ChatSession, ChatMessage, IndexedDocument
        print("✓ All database components imported successfully")
        
        # Test 2: Create database service
        print("\n2. Testing service creation...")
        db_service = DatabaseService()
        print("✓ DatabaseService created successfully")
        
        # Test 3: Test chat session creation
        print("\n3. Testing chat session creation...")
        chat_session = await db_service.create_chat_session(
            directory_path="/test/documents",
            title="Test Chat Session"
        )
        print(f"✓ Chat session created with ID: {chat_session.id}")
        
        # Test 4: Test message storage
        print("\n4. Testing message storage...")
        chat_message = await db_service.add_chat_message(
            session_id=chat_session.id,
            user_message="Hello, how are you?",
            ai_response="I'm doing well, thank you for asking!",
            sources=[{"file": "test.pdf", "relevance": 0.95}],
            response_time=2.5
        )
        print(f"✓ Chat message stored with ID: {chat_message.id}")
        
        # Test 5: Test document metadata storage
        print("\n5. Testing document metadata storage...")
        document = await db_service.store_document_metadata(
            file_path="/test/documents/test.pdf",
            file_hash="abc123hash",
            file_type="pdf",
            file_size=1024000,
            last_modified=chat_session.created_at,
            content_preview="This is a test document for testing the database integration.",
            chunks_count=5
        )
        print(f"✓ Document metadata stored with ID: {document.id}")
        
        # Test 6: Test document-chat linking
        print("\n6. Testing document-chat linking...")
        usage = await db_service.link_document_to_chat(
            document_id=document.id,
            chat_session_id=chat_session.id
        )
        print(f"✓ Document-chat usage linked successfully")
        
        # Test 7: Test retrieval methods
        print("\n7. Testing retrieval methods...")
        messages = await db_service.get_chat_history(chat_session.id)
        print(f"✓ Retrieved {len(messages)} messages from chat session")
        
        stats = await db_service.get_document_stats()
        print(f"✓ Retrieved document stats: {stats}")
        
        print("\n All database tests passed!")
        return True
        
    except Exception as e:
        print(f"\n❌ Database test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    asyncio.run(test_database_service())
