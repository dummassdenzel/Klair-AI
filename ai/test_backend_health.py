"""
Quick health check for backend
"""
import requests
import json

BASE_URL = "http://127.0.0.1:8000"

def test_health():
    """Test basic endpoints"""
    print("Testing backend health...")
    
    # Test 1: Root endpoint
    try:
        print("\n1. Testing root endpoint (/)...")
        response = requests.get(f"{BASE_URL}/", timeout=5)
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.text[:100]}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 2: Status endpoint
    try:
        print("\n2. Testing status endpoint (/api/status)...")
        response = requests.get(f"{BASE_URL}/api/status", timeout=5)
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Directory set: {data.get('directory_set')}")
            print(f"   Processor ready: {data.get('processor_ready')}")
        else:
            print(f"   Response: {response.text[:200]}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 3: Chat endpoint (should fail gracefully)
    try:
        print("\n3. Testing chat endpoint (/api/chat)...")
        response = requests.post(
            f"{BASE_URL}/api/chat",
            json={"message": "Hello"},
            timeout=10
        )
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.text[:200]}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

if __name__ == "__main__":
    test_health()

