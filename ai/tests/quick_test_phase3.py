"""
Quick Phase 3 Integration Test
Simple test to verify imports and basic functionality
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

async def main():
    print("=" * 70)
    print("QUICK PHASE 3 INTEGRATION TEST")
    print("=" * 70)
    
    # Test 1: Imports
    print("\n1. Testing imports...")
    try:
        from services.document_processor import (
            DocumentProcessorOrchestrator,
            UpdateQueue,
            UpdateWorker,
            ChunkDiffer,
            UpdateStrategySelector,
            UpdateExecutor,
            UpdateStrategy
        )
        print("   ✅ All Phase 3 components imported")
    except ImportError as e:
        print(f"   ❌ Import failed: {e}")
        return 1
    
    # Test 2: FileMonitor import
    print("\n2. Testing FileMonitor import...")
    try:
        from services.file_monitor import FileMonitorService
        print("   ✅ FileMonitorService imported")
    except ImportError as e:
        print(f"   ❌ Import failed: {e}")
        return 1
    
    # Test 3: Orchestrator initialization (without starting worker)
    print("\n3. Testing orchestrator initialization...")
    try:
        orchestrator = DocumentProcessorOrchestrator(
            persist_dir="./test_chroma",
            embed_model_name="BAAI/bge-small-en-v1.5",
            llm_provider="ollama"
        )
        
        # Check Phase 3 components
        assert hasattr(orchestrator, 'update_queue'), "update_queue missing"
        assert hasattr(orchestrator, 'chunk_differ'), "chunk_differ missing"
        assert hasattr(orchestrator, 'strategy_selector'), "strategy_selector missing"
        assert hasattr(orchestrator, 'update_executor'), "update_executor missing"
        assert hasattr(orchestrator, 'update_worker'), "update_worker missing"
        assert hasattr(orchestrator, 'enqueue_update'), "enqueue_update method missing"
        
        print("   ✅ Orchestrator initialized with all Phase 3 components")
        print("   ✅ enqueue_update method available")
        
        # Stop worker and cleanup
        await orchestrator.update_worker.stop()
        await orchestrator.clear_all_data()
        
    except Exception as e:
        print(f"   ❌ Initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Test 4: UpdateQueue status
    print("\n4. Testing UpdateQueue status...")
    try:
        queue = UpdateQueue()
        status = queue.get_status()
        assert "pending" in status
        assert "processing" in status
        assert "completed" in status
        assert "failed" in status
        print("   ✅ UpdateQueue status method works")
    except Exception as e:
        print(f"   ❌ UpdateQueue test failed: {e}")
        return 1
    
    print("\n" + "=" * 70)
    print("✅ ALL TESTS PASSED!")
    print("=" * 70)
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

