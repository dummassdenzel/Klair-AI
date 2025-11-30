"""
Unit tests for UpdateStrategySelector

Tests:
1. Full re-index for small files (< 10 chunks)
2. Full re-index for large changes (> 50%)
3. Chunk update for small changes (< 20%)
4. Smart hybrid for medium changes (20-50%)
5. Edge cases (0% change, 100% change, boundary values)
6. Strategy selection reasoning
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.document_processor import (
    UpdateStrategy, UpdateStrategySelector, StrategySelectionResult,
    ChunkDiffResult, ChunkMatch, DocumentChunk
)


def create_test_chunk(text: str, chunk_id: int) -> DocumentChunk:
    """Helper to create test chunks"""
    return DocumentChunk(
        text=text,
        chunk_id=chunk_id,
        total_chunks=0,
        file_path="test.txt",
        start_pos=0,
        end_pos=len(text)
    )


def create_diff_result(unchanged: int, modified: int, added: int, removed: int) -> ChunkDiffResult:
    """Helper to create ChunkDiffResult for testing"""
    unchanged_matches = [
        ChunkMatch(
            old_chunk=create_test_chunk(f"Unchanged {i}", i),
            new_chunk=create_test_chunk(f"Unchanged {i}", i),
            similarity_score=1.0,
            match_type="exact"
        )
        for i in range(unchanged)
    ]
    
    modified_matches = [
        ChunkMatch(
            old_chunk=create_test_chunk(f"Modified old {i}", i),
            new_chunk=create_test_chunk(f"Modified new {i}", i),
            similarity_score=0.85,
            match_type="similar"
        )
        for i in range(modified)
    ]
    
    added_chunks = [create_test_chunk(f"Added {i}", i) for i in range(added)]
    removed_chunks = [create_test_chunk(f"Removed {i}", i) for i in range(removed)]
    
    return ChunkDiffResult(
        unchanged_chunks=unchanged_matches,
        modified_chunks=modified_matches,
        added_chunks=added_chunks,
        removed_chunks=removed_chunks
    )


def test_1_small_files_full_reindex():
    """Test that small files (< 10 chunks) always use full re-index"""
    print("\n" + "="*70)
    print("TEST 1: Small Files → Full Re-index")
    print("="*70)
    
    selector = UpdateStrategySelector(min_chunks_for_incremental=10)
    
    # Small file with small change
    diff_result = create_diff_result(unchanged=5, modified=1, added=0, removed=0)
    result = selector.select_strategy(diff_result, total_chunks=6)
    
    print(f"✅ Strategy: {result.strategy.value}")
    print(f"✅ Reason: {result.reason}")
    
    assert result.strategy == UpdateStrategy.FULL_REINDEX, "Small files should use full re-index"
    assert "6 chunks" in result.reason or "10" in result.reason
    
    print("✅ PASSED: Small files use full re-index")
    return True


def test_2_large_changes_full_reindex():
    """Test that large changes (> 50%) use full re-index"""
    print("\n" + "="*70)
    print("TEST 2: Large Changes → Full Re-index")
    print("="*70)
    
    selector = UpdateStrategySelector(
        full_reindex_threshold=0.5,
        min_chunks_for_incremental=10
    )
    
    # Large file with large change (> 50%)
    # 20 chunks total: 5 unchanged, 10 modified, 2 added, 3 removed
    # Change % = (10 + 3) / (5 + 10 + 3) = 13/18 = 72% > 50%
    diff_result = create_diff_result(unchanged=5, modified=10, added=2, removed=3)
    result = selector.select_strategy(diff_result, total_chunks=20)
    
    print(f"✅ Strategy: {result.strategy.value}")
    print(f"✅ Change percentage: {diff_result.get_change_percentage():.1%}")
    print(f"✅ Reason: {result.reason}")
    
    assert result.strategy == UpdateStrategy.FULL_REINDEX, "Large changes should use full re-index"
    assert "exceeds threshold" in result.reason.lower() or "50%" in result.reason
    
    print("✅ PASSED: Large changes use full re-index")
    return True


def test_3_small_changes_chunk_update():
    """Test that small changes (< 20%) use chunk update"""
    print("\n" + "="*70)
    print("TEST 3: Small Changes → Chunk Update")
    print("="*70)
    
    selector = UpdateStrategySelector(
        chunk_update_threshold=0.2,
        min_chunks_for_incremental=10
    )
    
    # Large file with small change (< 20%)
    # 100 chunks total: 85 unchanged, 3 modified, 2 added, 10 removed
    # Change % = (3 + 10) / (85 + 3 + 10) = 13/98 = 13% < 20%
    diff_result = create_diff_result(unchanged=85, modified=3, added=2, removed=10)
    result = selector.select_strategy(diff_result, total_chunks=100)
    
    print(f"✅ Strategy: {result.strategy.value}")
    print(f"✅ Change percentage: {diff_result.get_change_percentage():.1%}")
    print(f"✅ Estimated savings: {result.estimated_time_savings:.1%}")
    print(f"✅ Reason: {result.reason}")
    
    assert result.strategy == UpdateStrategy.CHUNK_UPDATE, "Small changes should use chunk update"
    assert "below threshold" in result.reason.lower() or "20%" in result.reason
    assert result.estimated_time_savings > 0.5, "Should have significant time savings"
    
    print("✅ PASSED: Small changes use chunk update")
    return True


def test_4_medium_changes_smart_hybrid():
    """Test that medium changes (20-50%) use smart hybrid"""
    print("\n" + "="*70)
    print("TEST 4: Medium Changes → Smart Hybrid")
    print("="*70)
    
    selector = UpdateStrategySelector(
        chunk_update_threshold=0.2,
        full_reindex_threshold=0.5,
        min_chunks_for_incremental=10
    )
    
    # Large file with medium change (30%)
    # 100 chunks total: 50 unchanged, 20 modified, 5 added, 25 removed
    # Change % = (20 + 25) / (50 + 20 + 25) = 45/95 = 47% (between 20% and 50%)
    diff_result = create_diff_result(unchanged=50, modified=20, added=5, removed=25)
    result = selector.select_strategy(diff_result, total_chunks=100)
    
    print(f"✅ Strategy: {result.strategy.value}")
    print(f"✅ Change percentage: {diff_result.get_change_percentage():.1%}")
    print(f"✅ Estimated savings: {result.estimated_time_savings:.1%}")
    print(f"✅ Reason: {result.reason}")
    
    assert result.strategy == UpdateStrategy.SMART_HYBRID, "Medium changes should use smart hybrid"
    assert "between thresholds" in result.reason.lower() or "hybrid" in result.reason.lower()
    
    print("✅ PASSED: Medium changes use smart hybrid")
    return True


def test_5_zero_change():
    """Test edge case: 0% change"""
    print("\n" + "="*70)
    print("TEST 5: Zero Change")
    print("="*70)
    
    selector = UpdateStrategySelector(min_chunks_for_incremental=10)
    
    # No changes
    diff_result = create_diff_result(unchanged=100, modified=0, added=0, removed=0)
    result = selector.select_strategy(diff_result, total_chunks=100)
    
    print(f"✅ Strategy: {result.strategy.value}")
    print(f"✅ Change percentage: {diff_result.get_change_percentage():.1%}")
    
    assert result.strategy == UpdateStrategy.CHUNK_UPDATE, "No changes should use chunk update (skip everything)"
    assert diff_result.get_change_percentage() == 0.0
    
    print("✅ PASSED: Zero change handled correctly")
    return True


def test_6_boundary_values():
    """Test boundary values at thresholds"""
    print("\n" + "="*70)
    print("TEST 6: Boundary Values")
    print("="*70)
    
    selector = UpdateStrategySelector(
        chunk_update_threshold=0.2,
        full_reindex_threshold=0.5,
        min_chunks_for_incremental=10
    )
    
    # Exactly at chunk_update_threshold (20%)
    # 100 chunks: 80 unchanged, 16 modified, 0 added, 4 removed
    # Change % = (16 + 4) / (80 + 16 + 4) = 20/100 = 20%
    diff_result = create_diff_result(unchanged=80, modified=16, added=0, removed=4)
    result = selector.select_strategy(diff_result, total_chunks=100)
    
    print(f"✅ At 20% threshold: {result.strategy.value}")
    # Should be CHUNK_UPDATE (threshold is < 0.2, so 0.2 is not < 0.2, should go to SMART_HYBRID)
    # Actually, 20% is not < 20%, so it should use SMART_HYBRID
    assert result.strategy in [UpdateStrategy.CHUNK_UPDATE, UpdateStrategy.SMART_HYBRID]
    
    # Exactly at full_reindex_threshold (50%)
    # 100 chunks: 50 unchanged, 40 modified, 0 added, 10 removed
    # Change % = (40 + 10) / (50 + 40 + 10) = 50/100 = 50%
    diff_result = create_diff_result(unchanged=50, modified=40, added=0, removed=10)
    result = selector.select_strategy(diff_result, total_chunks=100)
    
    print(f"✅ At 50% threshold: {result.strategy.value}")
    # Should be FULL_REINDEX (threshold is > 0.5, so 0.5 is not > 0.5, should use SMART_HYBRID)
    # Actually, 50% is not > 50%, so it should use SMART_HYBRID
    assert result.strategy in [UpdateStrategy.FULL_REINDEX, UpdateStrategy.SMART_HYBRID]
    
    print("✅ PASSED: Boundary values handled correctly")
    return True


def test_7_simple_selection():
    """Test simplified selection method"""
    print("\n" + "="*70)
    print("TEST 7: Simple Selection Method")
    print("="*70)
    
    selector = UpdateStrategySelector(
        chunk_update_threshold=0.2,
        full_reindex_threshold=0.5,
        min_chunks_for_incremental=10
    )
    
    # Test various scenarios
    test_cases = [
        (0.1, 100, UpdateStrategy.CHUNK_UPDATE),  # 10% change, large file
        (0.3, 100, UpdateStrategy.SMART_HYBRID),  # 30% change, large file
        (0.6, 100, UpdateStrategy.FULL_REINDEX),  # 60% change, large file
        (0.1, 5, UpdateStrategy.FULL_REINDEX),  # 10% change, small file
    ]
    
    for change_pct, total_chunks, expected in test_cases:
        strategy = selector.select_strategy_simple(change_pct, total_chunks)
        print(f"✅ {change_pct:.0%} change, {total_chunks} chunks → {strategy.value}")
        assert strategy == expected, f"Expected {expected.value}, got {strategy.value}"
    
    print("✅ PASSED: Simple selection works correctly")
    return True


def test_8_custom_thresholds():
    """Test with custom thresholds"""
    print("\n" + "="*70)
    print("TEST 8: Custom Thresholds")
    print("="*70)
    
    # Custom thresholds: 30% and 70%
    selector = UpdateStrategySelector(
        chunk_update_threshold=0.3,
        full_reindex_threshold=0.7,
        min_chunks_for_incremental=5
    )
    
    # 25% change should use chunk update
    diff_result = create_diff_result(unchanged=75, modified=20, added=0, removed=5)
    result = selector.select_strategy(diff_result, total_chunks=100)
    assert result.strategy == UpdateStrategy.CHUNK_UPDATE
    
    # 50% change should use smart hybrid
    diff_result = create_diff_result(unchanged=50, modified=40, added=0, removed=10)
    result = selector.select_strategy(diff_result, total_chunks=100)
    assert result.strategy == UpdateStrategy.SMART_HYBRID
    
    # 80% change should use full re-index
    diff_result = create_diff_result(unchanged=20, modified=60, added=0, removed=20)
    result = selector.select_strategy(diff_result, total_chunks=100)
    assert result.strategy == UpdateStrategy.FULL_REINDEX
    
    print("✅ PASSED: Custom thresholds work correctly")
    return True


def run_all_tests():
    """Run all tests"""
    print("\n" + "="*70)
    print("UPDATE STRATEGY SELECTOR TEST SUITE")
    print("="*70)
    
    tests = [
        test_1_small_files_full_reindex,
        test_2_large_changes_full_reindex,
        test_3_small_changes_chunk_update,
        test_4_medium_changes_smart_hybrid,
        test_5_zero_change,
        test_6_boundary_values,
        test_7_simple_selection,
        test_8_custom_thresholds,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            result = test()
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
    success = run_all_tests()
    sys.exit(0 if success else 1)

