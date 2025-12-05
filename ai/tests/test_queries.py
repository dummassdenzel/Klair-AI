"""
Test script to query the API and see what the AI responds.
"""

import asyncio
import sys
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
import logging

logging.basicConfig(level=logging.INFO)

def test_query(question: str, session_id: int = None):
    """Test a query via the API"""
    print("\n" + "="*80)
    print(f"QUERY: {question}")
    print("="*80)
    
    try:
        # Create session if needed
        if session_id is None:
            session_response = requests.post(
                "http://localhost:8000/api/chat-sessions",
                json={"title": "Test Session"},
                timeout=10
            )
            if session_response.status_code == 200:
                session_data = session_response.json()
                session_id = session_data.get('id')
                print(f"✅ Created session: {session_id}")
            else:
                print(f"⚠️  Could not create session, using session_id=1")
                session_id = 1
        
        # Send query to API
        response = requests.post(
            "http://localhost:8000/api/chat",
            json={
                "message": question,
                "session_id": session_id
            },
            timeout=60
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"\n✅ Response received:")
            print(f"📝 AI Response:\n{data.get('message', 'No message')}")
            print(f"\n📊 Sources: {len(data.get('sources', []))} documents")
            
            # Show sources
            sources = data.get('sources', [])
            if sources:
                print(f"\n📄 Sources found:")
                for i, source in enumerate(sources, 1):
                    filename = Path(source.get('file_path', '')).name
                    print(f"   {i}. {filename}")
                    print(f"      - Status: {source.get('processing_status', 'unknown')}")
                    print(f"      - Chunks: {source.get('chunks_found', 0)}")
                    print(f"      - Type: {source.get('file_type', 'unknown')}")
        else:
            print(f"❌ Error: {response.status_code}")
            print(f"   {response.text}")
            
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to server. Is the server running on http://localhost:8000?")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Test all queries"""
    print("="*80)
    print("API QUERY TEST")
    print("="*80)
    print("\n⚠️  Make sure the server is running on http://localhost:8000")
    print("⚠️  Make sure you have selected a directory with the PPTX files")
    
    # Create a session for all queries
    session_id = None
    try:
        session_response = requests.post(
            "http://localhost:8000/api/chat-sessions",
            json={"title": "PPTX Debug Test"},
            timeout=10
        )
        if session_response.status_code == 200:
            session_data = session_response.json()
            session_id = session_data.get('id')
            print(f"✅ Created test session: {session_id}")
    except Exception as e:
        print(f"⚠️  Could not create session: {e}, will use session_id=1")
        session_id = 1
    
    questions = [
        "What do you know about our files?",
        "What do you know about Lazt Bean Cafe?",
        "What do you know about Copy of PJTC Speaker Pubmat?"
    ]
    
    for question in questions:
        test_query(question, session_id)
        print("\n" + "-"*80)
    
    print("\n" + "="*80)
    print("ALL TESTS COMPLETE")
    print("="*80)

if __name__ == "__main__":
    main()

