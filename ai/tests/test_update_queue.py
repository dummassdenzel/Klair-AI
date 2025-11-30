"""
Unit tests for UpdateQueue

Tests:
1. Enqueue and dequeue operations
2. Priority ordering
3. Priority calculation
4. Active update tracking
5. Completed update tracking
6. Queue status
7. Edge cases (empty queue, full queue, duplicates)
"""

import sys
import os
import asyncio

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.document_processor import (
    UpdateQueue, UpdateTask, UpdateResult, UpdatePriority, UpdateStrategy
)
from datetime import datetime, timedelta


async def test_1_enqueue_dequeue():
    """Test basic enqueue and dequeue operations"""
    print("\n" + "="*70)
    print("TEST 1: Enqueue and Dequeue")
    print("="*70)
    
    queue = UpdateQueue(max_queue_size=10)
    
    # Enqueue a task
    success = await queue.enqueue(
        file_path="test1.txt",
        update_type="modified",
        priority=500
    )
    assert success, "Should enqueue successfully"
    
    # Get next task
    task = await queue.get_next(timeout=1.0)
    assert task is not None, "Should get a task"
    assert task.file_path == "test1.txt", "Should get correct file"
    assert task.priority == 500, "Should have correct priority"
    
    print(f"✅ Enqueued and dequeued: {task.file_path}")
    print("✅ PASSED: Basic enqueue/dequeue works")
    return True


async def test_2_priority_ordering():
    """Test that higher priority tasks are processed first"""
    print("\n" + "="*70)
    print("TEST 2: Priority Ordering")
    print("="*70)
    
    queue = UpdateQueue(max_queue_size=10)
    
    # Enqueue tasks with different priorities
    await queue.enqueue("low.txt", priority=100)
    await queue.enqueue("high.txt", priority=900)
    await queue.enqueue("medium.txt", priority=500)
    
    # Dequeue and check order
    task1 = await queue.get_next(timeout=1.0)
    assert task1.file_path == "high.txt", "Highest priority should come first"
    
    task2 = await queue.get_next(timeout=1.0)
    assert task2.file_path == "medium.txt", "Medium priority should come second"
    
    task3 = await queue.get_next(timeout=1.0)
    assert task3.file_path == "low.txt", "Lowest priority should come last"
    
    print(f"✅ Order: {task1.file_path} → {task2.file_path} → {task3.file_path}")
    print("✅ PASSED: Priority ordering works correctly")
    return True


async def test_3_priority_calculation():
    """Test automatic priority calculation"""
    print("\n" + "="*70)
    print("TEST 3: Priority Calculation")
    print("="*70)
    
    queue = UpdateQueue()
    
    # Test user requested (should be URGENT)
    await queue.enqueue(
        "urgent.txt",
        user_requested=True
    )
    task = await queue.get_next(timeout=1.0)
    assert task.priority == UpdatePriority.URGENT, "User requested should be URGENT"
    print(f"✅ User requested: priority {task.priority}")
    
    # Test active session
    await queue.enqueue(
        "active.txt",
        is_in_active_session=True,
        last_queried=datetime.utcnow()
    )
    task = await queue.get_next(timeout=1.0)
    assert task.priority >= 200, "Active session should boost priority"
    print(f"✅ Active session: priority {task.priority}")
    
    # Test recency (recent file)
    await queue.enqueue(
        "recent.txt",
        last_queried=datetime.utcnow() - timedelta(minutes=30)  # 30 minutes ago
    )
    task = await queue.get_next(timeout=1.0)
    recent_priority = task.priority
    print(f"✅ Recent file: priority {recent_priority}")
    
    # Test old file
    await queue.enqueue(
        "old.txt",
        last_queried=datetime.utcnow() - timedelta(days=2)  # 2 days ago
    )
    task = await queue.get_next(timeout=1.0)
    old_priority = task.priority
    print(f"✅ Old file: priority {old_priority}")
    
    assert recent_priority > old_priority, "Recent files should have higher priority"
    
    # Test small file vs large file
    await queue.enqueue("small.txt", file_size_bytes=1024)  # 1 KB
    task_small = await queue.get_next(timeout=1.0)
    
    await queue.enqueue("large.txt", file_size_bytes=100*1024*1024)  # 100 MB
    task_large = await queue.get_next(timeout=1.0)
    
    print(f"✅ Small file: priority {task_small.priority}")
    print(f"✅ Large file: priority {task_large.priority}")
    assert task_small.priority > task_large.priority, "Small files should have higher priority"
    
    # Test small change vs large change
    await queue.enqueue("small_change.txt", change_percentage=0.1)  # 10% change
    task_small_change = await queue.get_next(timeout=1.0)
    
    await queue.enqueue("large_change.txt", change_percentage=0.8)  # 80% change
    task_large_change = await queue.get_next(timeout=1.0)
    
    print(f"✅ Small change: priority {task_small_change.priority}")
    print(f"✅ Large change: priority {task_large_change.priority}")
    assert task_small_change.priority > task_large_change.priority, "Small changes should have higher priority"
    
    print("✅ PASSED: Priority calculation works correctly")
    return True


async def test_4_active_tracking():
    """Test active update tracking"""
    print("\n" + "="*70)
    print("TEST 4: Active Update Tracking")
    print("="*70)
    
    queue = UpdateQueue()
    
    # Enqueue and get task
    await queue.enqueue("active1.txt", priority=500)
    task = await queue.get_next(timeout=1.0)
    
    # Check active updates
    status = queue.get_status()
    assert status["processing"] == 1, "Should have 1 active update"
    assert "active1.txt" in status["active_files"], "Should track active file"
    
    print(f"✅ Active updates: {status['processing']}")
    print(f"✅ Active files: {status['active_files']}")
    
    # Mark as completed
    result = UpdateResult(
        success=True,
        file_path="active1.txt",
        strategy=UpdateStrategy.FULL_REINDEX,
        chunks_updated=10,
        processing_time=1.5
    )
    await queue.mark_completed("active1.txt", result)
    
    # Check status again
    status = queue.get_status()
    assert status["processing"] == 0, "Should have 0 active updates"
    assert status["completed"] == 1, "Should have 1 completed update"
    
    print(f"✅ After completion: processing={status['processing']}, completed={status['completed']}")
    print("✅ PASSED: Active tracking works correctly")
    return True


async def test_5_completed_tracking():
    """Test completed update tracking"""
    print("\n" + "="*70)
    print("TEST 5: Completed Update Tracking")
    print("="*70)
    
    queue = UpdateQueue()
    
    # Complete a successful update
    result = UpdateResult(
        success=True,
        file_path="success.txt",
        strategy=UpdateStrategy.CHUNK_UPDATE,
        chunks_updated=5,
        processing_time=0.5
    )
    await queue.mark_completed("success.txt", result)
    
    status = queue.get_status()
    assert status["completed"] == 1, "Should track completed updates"
    assert "success.txt" in queue.completed_updates, "Should store completed result"
    
    # Complete a failed update
    await queue.mark_failed("failed.txt", "Test error")
    
    status = queue.get_status()
    assert status["failed"] == 1, "Should track failed updates"
    assert "failed.txt" in queue.failed_updates, "Should store failed result"
    
    print(f"✅ Completed: {status['completed']}, Failed: {status['failed']}")
    print("✅ PASSED: Completed tracking works correctly")
    return True


async def test_6_queue_status():
    """Test queue status reporting"""
    print("\n" + "="*70)
    print("TEST 6: Queue Status")
    print("="*70)
    
    queue = UpdateQueue(max_queue_size=10)
    
    # Empty queue
    status = queue.get_status()
    assert status["pending"] == 0, "Should have 0 pending"
    assert status["processing"] == 0, "Should have 0 processing"
    
    # Add some tasks
    await queue.enqueue("file1.txt", priority=100)
    await queue.enqueue("file2.txt", priority=200)
    await queue.enqueue("file3.txt", priority=300)
    
    status = queue.get_status()
    assert status["pending"] == 3, "Should have 3 pending"
    
    # Get one task (moves to active)
    task = await queue.get_next(timeout=1.0)
    status = queue.get_status()
    assert status["pending"] == 2, "Should have 2 pending"
    assert status["processing"] == 1, "Should have 1 processing"
    
    print(f"✅ Status: {status}")
    print("✅ PASSED: Queue status works correctly")
    return True


async def test_7_duplicate_prevention():
    """Test that duplicate files are not enqueued if already processing"""
    print("\n" + "="*70)
    print("TEST 7: Duplicate Prevention")
    print("="*70)
    
    queue = UpdateQueue()
    
    # Enqueue and get task (moves to active)
    await queue.enqueue("duplicate.txt", priority=500)
    task = await queue.get_next(timeout=1.0)
    
    # Try to enqueue same file again
    success = await queue.enqueue("duplicate.txt", priority=900)
    assert not success, "Should not enqueue duplicate if already processing"
    
    # Mark as completed
    result = UpdateResult(
        success=True,
        file_path="duplicate.txt",
        strategy=UpdateStrategy.FULL_REINDEX,
        chunks_updated=10,
        processing_time=1.0
    )
    await queue.mark_completed("duplicate.txt", result)
    
    # Now should be able to enqueue again
    success = await queue.enqueue("duplicate.txt", priority=500)
    assert success, "Should be able to enqueue after completion"
    
    print("✅ PASSED: Duplicate prevention works")
    return True


async def test_8_full_queue():
    """Test behavior when queue is full"""
    print("\n" + "="*70)
    print("TEST 8: Full Queue")
    print("="*70)
    
    queue = UpdateQueue(max_queue_size=3)
    
    # Fill queue
    await queue.enqueue("file1.txt", priority=100)
    await queue.enqueue("file2.txt", priority=200)
    await queue.enqueue("file3.txt", priority=300)
    
    # Try to add one more (should fail)
    success = await queue.enqueue("file4.txt", priority=400)
    assert not success, "Should not enqueue when queue is full"
    
    # Remove one
    task = await queue.get_next(timeout=1.0)
    
    # Now should be able to add
    success = await queue.enqueue("file4.txt", priority=400)
    assert success, "Should be able to enqueue after space available"
    
    print("✅ PASSED: Full queue handling works")
    return True


async def test_9_timeout():
    """Test timeout when getting next task from empty queue"""
    print("\n" + "="*70)
    print("TEST 9: Timeout")
    print("="*70)
    
    queue = UpdateQueue()
    
    # Try to get from empty queue with short timeout
    start = datetime.utcnow()
    task = await queue.get_next(timeout=0.1)
    elapsed = (datetime.utcnow() - start).total_seconds()
    
    assert task is None, "Should return None on timeout"
    assert 0.1 <= elapsed < 0.2, "Should timeout after ~0.1 seconds"
    
    print(f"✅ Timeout after {elapsed:.2f} seconds")
    print("✅ PASSED: Timeout works correctly")
    return True


async def run_all_tests():
    """Run all tests"""
    print("\n" + "="*70)
    print("UPDATE QUEUE TEST SUITE")
    print("="*70)
    
    tests = [
        test_1_enqueue_dequeue,
        test_2_priority_ordering,
        test_3_priority_calculation,
        test_4_active_tracking,
        test_5_completed_tracking,
        test_6_queue_status,
        test_7_duplicate_prevention,
        test_8_full_queue,
        test_9_timeout,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            result = await test()
            if result:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ ERROR in {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "="*70)
    print(f"TEST RESULTS: {passed} passed, {failed} failed")
    print("="*70)
    
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)

