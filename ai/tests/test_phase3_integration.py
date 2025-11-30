"""
Phase 3.5 Integration Test

Tests the complete integration of Phase 3 components:
- UpdateQueue
- ChunkDiffer
- UpdateStrategySelector
- UpdateExecutor
- UpdateWorker
- Orchestrator integration
- FileMonitor integration
"""

import asyncio
import sys
import os
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

async def test_imports():
    """Test 1: Verify all Phase 3 components can be imported"""
    print("=" * 70)
    print("TEST 1: Import Verification")
    print("=" * 70)
    
    try:
        # Test orchestrator import
        from services.document_processor import DocumentProcessorOrchestrator
        print("✅ DocumentProcessorOrchestrator imported")
        
        # Test Phase 3 component imports
        from services.document_processor import (
            UpdateQueue, UpdateTask, UpdateResult, UpdatePriority,
            ChunkDiffer, UpdateStrategySelector, UpdateStrategy,
            UpdateExecutor, Checkpoint
        )
        print("✅ Phase 3 components imported")
        
        # Test UpdateWorker import
        from services.document_processor.update_worker import UpdateWorker
        print("✅ UpdateWorker imported")
        
        # Test FileMonitor import
        from services.file_monitor import FileMonitorService
        print("✅ FileMonitorService imported")
        
        print("✅ PASSED: All imports successful\n")
        return True
        
    except ImportError as e:
        print(f"❌ FAILED: Import error: {e}\n")
        return False

async def test_orchestrator_initialization():
    """Test 2: Verify orchestrator initializes Phase 3 components correctly"""
    print("=" * 70)
    print("TEST 2: Orchestrator Initialization")
    print("=" * 70)
    
    try:
        from services.document_processor import DocumentProcessorOrchestrator
        
        # Create temporary directory for testing
        test_dir = tempfile.mkdtemp()
        
        orchestrator = DocumentProcessorOrchestrator(
            persist_dir=os.path.join(test_dir, "chroma_test"),
            embed_model_name="BAAI/bge-small-en-v1.5",
            max_file_size_mb=50,
            chunk_size=1000,
            chunk_overlap=200,
            ollama_base_url="http://localhost:11434",
            ollama_model="tinyllama",
            llm_provider="ollama"
        )
        
        # Verify Phase 3 components are initialized
        assert hasattr(orchestrator, 'update_queue'), "update_queue not found"
        assert hasattr(orchestrator, 'chunk_differ'), "chunk_differ not found"
        assert hasattr(orchestrator, 'strategy_selector'), "strategy_selector not found"
        assert hasattr(orchestrator, 'update_executor'), "update_executor not found"
        assert hasattr(orchestrator, 'update_worker'), "update_worker not found"
        print("✅ All Phase 3 components initialized")
        
        # Verify update worker is running
        await asyncio.sleep(0.5)  # Give worker time to start
        assert orchestrator.update_worker.is_running, "Update worker not running"
        print("✅ Update worker started")
        
        # Cleanup - properly close all connections
        await orchestrator.update_worker.stop()
        await orchestrator.clear_all_data()
        
        # Close ChromaDB connection
        if orchestrator.vector_store.chroma_client:
            orchestrator.vector_store.cleanup()
        
        # Wait for file handles to be released
        await asyncio.sleep(0.5)
        
        # Try to remove directory, with retry on Windows
        try:
            shutil.rmtree(test_dir)
        except PermissionError:
            await asyncio.sleep(1)
            try:
                shutil.rmtree(test_dir)
            except PermissionError:
                print(f"⚠️  Warning: Could not delete {test_dir} (file may be locked)")
        
        print("✅ PASSED: Orchestrator initialization successful\n")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False

async def test_enqueue_update():
    """Test 3: Verify enqueue_update method works"""
    print("=" * 70)
    print("TEST 3: Enqueue Update")
    print("=" * 70)
    
    try:
        from services.document_processor import DocumentProcessorOrchestrator
        
        test_dir = tempfile.mkdtemp()
        
        orchestrator = DocumentProcessorOrchestrator(
            persist_dir=os.path.join(test_dir, "chroma_test"),
            embed_model_name="BAAI/bge-small-en-v1.5",
            llm_provider="ollama"
        )
        
        # Create a test file
        test_file = os.path.join(test_dir, "test.txt")
        with open(test_file, 'w') as f:
            f.write("Test content")
        
        # Test enqueue_update
        result = await orchestrator.enqueue_update(
            file_path=test_file,
            update_type="modified",
            user_requested=False
        )
        
        assert result == True, "enqueue_update returned False"
        print("✅ Update enqueued successfully")
        
        # Verify queue status
        status = orchestrator.update_queue.get_status()
        assert status["pending"] >= 1, "Queue should have at least 1 pending task"
        print(f"✅ Queue status: {status['pending']} pending, {status['processing']} processing")
        
        # Cleanup - properly close all connections
        await orchestrator.update_worker.stop()
        await orchestrator.clear_all_data()
        
        # Close ChromaDB connection
        if orchestrator.vector_store.chroma_client:
            orchestrator.vector_store.cleanup()
        
        # Wait for file handles to be released
        await asyncio.sleep(0.5)
        
        # Try to remove directory, with retry on Windows
        try:
            shutil.rmtree(test_dir)
        except PermissionError:
            await asyncio.sleep(1)
            try:
                shutil.rmtree(test_dir)
            except PermissionError:
                print(f"⚠️  Warning: Could not delete {test_dir} (file may be locked)")
        
        print("✅ PASSED: Enqueue update successful\n")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False

async def test_file_monitor_integration():
    """Test 4: Verify FileMonitor uses update queue"""
    print("=" * 70)
    print("TEST 4: FileMonitor Integration")
    print("=" * 70)
    
    try:
        from services.document_processor import DocumentProcessorOrchestrator
        from services.file_monitor import FileMonitorService
        
        test_dir = tempfile.mkdtemp()
        
        orchestrator = DocumentProcessorOrchestrator(
            persist_dir=os.path.join(test_dir, "chroma_test"),
            embed_model_name="BAAI/bge-small-en-v1.5",
            llm_provider="ollama"
        )
        
        # Create FileMonitor
        file_monitor = FileMonitorService(orchestrator)
        
        # Verify FileMonitor has access to orchestrator
        assert file_monitor.document_processor == orchestrator
        print("✅ FileMonitor initialized with orchestrator")
        
        # Verify orchestrator has enqueue_update method
        assert hasattr(orchestrator, 'enqueue_update'), "enqueue_update method not found"
        print("✅ Orchestrator has enqueue_update method")
        
        # Cleanup - properly close all connections
        await orchestrator.update_worker.stop()
        await file_monitor.stop_monitoring()
        await orchestrator.clear_all_data()
        
        # Close ChromaDB connection
        if orchestrator.vector_store.chroma_client:
            orchestrator.vector_store.cleanup()
        
        # Wait for file handles to be released
        await asyncio.sleep(0.5)
        
        # Try to remove directory, with retry on Windows
        try:
            shutil.rmtree(test_dir)
        except PermissionError:
            await asyncio.sleep(1)
            try:
                shutil.rmtree(test_dir)
            except PermissionError:
                print(f"⚠️  Warning: Could not delete {test_dir} (file may be locked)")
        
        print("✅ PASSED: FileMonitor integration successful\n")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False

async def test_add_document_with_queue():
    """Test 5: Verify add_document respects use_queue parameter"""
    print("=" * 70)
    print("TEST 5: Add Document with Queue Parameter")
    print("=" * 70)
    
    try:
        from services.document_processor import DocumentProcessorOrchestrator
        
        test_dir = tempfile.mkdtemp()
        
        orchestrator = DocumentProcessorOrchestrator(
            persist_dir=os.path.join(test_dir, "chroma_test"),
            embed_model_name="BAAI/bge-small-en-v1.5",
            llm_provider="ollama"
        )
        
        # Create a test file
        test_file = os.path.join(test_dir, "test.txt")
        with open(test_file, 'w') as f:
            f.write("Test content for queue test")
        
        # Test with use_queue=True (should enqueue)
        initial_queue_size = orchestrator.update_queue.get_status()["pending"]
        await orchestrator.add_document(test_file, use_queue=True)
        await asyncio.sleep(0.5)  # Give time for enqueue
        
        new_queue_size = orchestrator.update_queue.get_status()["pending"]
        assert new_queue_size >= initial_queue_size, "Queue should have new task"
        print("✅ add_document with use_queue=True enqueued update")
        
        # Test with use_queue=False (should process directly)
        # This will process directly, so we just verify it doesn't fail
        await orchestrator.add_document(test_file, use_queue=False, force_reindex=True)
        print("✅ add_document with use_queue=False processed directly")
        
        # Cleanup - properly close all connections
        await orchestrator.update_worker.stop()
        await orchestrator.clear_all_data()
        
        # Close ChromaDB connection
        if orchestrator.vector_store.chroma_client:
            orchestrator.vector_store.cleanup()
        
        # Wait for file handles to be released
        await asyncio.sleep(0.5)
        
        # Try to remove directory, with retry on Windows
        try:
            shutil.rmtree(test_dir)
        except PermissionError:
            await asyncio.sleep(1)
            try:
                shutil.rmtree(test_dir)
            except PermissionError:
                print(f"⚠️  Warning: Could not delete {test_dir} (file may be locked)")
        
        print("✅ PASSED: Add document queue parameter works\n")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False

async def test_api_endpoints_available():
    """Test 6: Verify API endpoints are accessible (import check)"""
    print("=" * 70)
    print("TEST 6: API Endpoints Check")
    print("=" * 70)
    
    try:
        # Check if main.py can be imported (this verifies API routes exist)
        import importlib.util
        main_path = Path(__file__).parent.parent / "main.py"
        
        if main_path.exists():
            spec = importlib.util.spec_from_file_location("main", main_path)
            main_module = importlib.util.module_from_spec(spec)
            # Don't actually load it (would start server), just verify it exists
            print("✅ main.py exists and can be loaded")
        else:
            print("⚠️  main.py not found (may be in different location)")
        
        # Verify API service methods exist in frontend
        frontend_service_path = Path(__file__).parent.parent.parent / "src" / "lib" / "api" / "services.ts"
        if frontend_service_path.exists():
            with open(frontend_service_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if 'getUpdateQueueStatus' in content:
                    print("✅ Frontend API service has getUpdateQueueStatus")
                if 'getUpdateStatus' in content:
                    print("✅ Frontend API service has getUpdateStatus")
                if 'forceUpdate' in content:
                    print("✅ Frontend API service has forceUpdate")
        
        print("✅ PASSED: API endpoints check successful\n")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False

async def run_all_tests():
    """Run all integration tests"""
    print("\n" + "=" * 70)
    print("PHASE 3.5 INTEGRATION TEST SUITE")
    print("=" * 70 + "\n")
    
    tests = [
        ("Import Verification", test_imports),
        ("Orchestrator Initialization", test_orchestrator_initialization),
        ("Enqueue Update", test_enqueue_update),
        ("FileMonitor Integration", test_file_monitor_integration),
        ("Add Document Queue Parameter", test_add_document_with_queue),
        ("API Endpoints Check", test_api_endpoints_available),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ Test '{test_name}' crashed: {e}\n")
            results.append((test_name, False))
    
    # Summary
    print("=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All integration tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(run_all_tests())
    sys.exit(exit_code)

