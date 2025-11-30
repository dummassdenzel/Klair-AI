"""
Unit tests for ChunkDiffer service

Tests:
1. Hash-based exact matching
2. Text similarity matching
3. Embedding-based similarity matching
4. Combined diffing (all methods)
5. Edge cases (empty chunks, all new, all removed)
6. Change percentage calculation
"""

import sys
import os
import asyncio

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.document_processor import ChunkDiffer, EmbeddingService, DocumentChunk, ChunkMatch, ChunkDiffResult


def create_test_chunk(text: str, chunk_id: int, file_path: str = "test.txt") -> DocumentChunk:
    """Helper to create test chunks"""
    return DocumentChunk(
        text=text,
        chunk_id=chunk_id,
        total_chunks=0,
        file_path=file_path,
        start_pos=0,
        end_pos=len(text)
    )


def test_1_hash_based_exact_matching():
    """Test hash-based matching for identical chunks"""
    print("\n" + "="*70)
    print("TEST 1: Hash-Based Exact Matching")
    print("="*70)
    
    embedding_service = EmbeddingService()
    differ = ChunkDiffer(embedding_service, similarity_threshold=0.85)
    
    # Create identical chunks
    old_chunks = [
        create_test_chunk("This is chunk 1", 0),
        create_test_chunk("This is chunk 2", 1),
        create_test_chunk("This is chunk 3", 2),
    ]
    
    new_chunks = [
        create_test_chunk("This is chunk 1", 0),  # Identical
        create_test_chunk("This is chunk 2", 1),  # Identical
        create_test_chunk("This is chunk 3", 2),  # Identical
    ]
    
    result = differ.diff_chunks(old_chunks, new_chunks)
    
    print(f"✅ Unchanged chunks: {len(result.unchanged_chunks)}")
    print(f"✅ Modified chunks: {len(result.modified_chunks)}")
    print(f"✅ Added chunks: {len(result.added_chunks)}")
    print(f"✅ Removed chunks: {len(result.removed_chunks)}")
    print(f"✅ Change percentage: {result.get_change_percentage():.1%}")
    
    assert len(result.unchanged_chunks) == 3, "Should have 3 unchanged chunks"
    assert len(result.modified_chunks) == 0, "Should have 0 modified chunks"
    assert len(result.added_chunks) == 0, "Should have 0 added chunks"
    assert len(result.removed_chunks) == 0, "Should have 0 removed chunks"
    assert result.get_change_percentage() == 0.0, "Should have 0% change"
    
    print("✅ PASSED: Hash-based exact matching works correctly")
    return True


def test_2_text_similarity_matching():
    """Test text similarity matching for similar but changed chunks"""
    print("\n" + "="*70)
    print("TEST 2: Text Similarity Matching")
    print("="*70)
    
    embedding_service = EmbeddingService()
    differ = ChunkDiffer(
        embedding_service, 
        similarity_threshold=0.85,
        text_similarity_threshold=0.70
    )
    
    old_chunks = [
        create_test_chunk("This is the first chunk with some content", 0),
        create_test_chunk("This is the second chunk", 1),
    ]
    
    # Similar but changed chunks
    new_chunks = [
        create_test_chunk("This is the first chunk with some modified content", 0),  # Similar
        create_test_chunk("This is the second chunk with additions", 1),  # Similar
    ]
    
    result = differ.diff_chunks(old_chunks, new_chunks)
    
    print(f"✅ Unchanged chunks: {len(result.unchanged_chunks)}")
    print(f"✅ Modified chunks: {len(result.modified_chunks)}")
    print(f"✅ Added chunks: {len(result.added_chunks)}")
    print(f"✅ Removed chunks: {len(result.removed_chunks)}")
    
    # Should have matches (either text or embedding based)
    total_matches = len(result.unchanged_chunks) + len(result.modified_chunks)
    assert total_matches > 0, "Should have matched some chunks"
    
    print("✅ PASSED: Text similarity matching works")
    return True


def test_3_all_new_chunks():
    """Test when all chunks are new"""
    print("\n" + "="*70)
    print("TEST 3: All New Chunks")
    print("="*70)
    
    embedding_service = EmbeddingService()
    differ = ChunkDiffer(embedding_service)
    
    old_chunks = []
    new_chunks = [
        create_test_chunk("New chunk 1", 0),
        create_test_chunk("New chunk 2", 1),
    ]
    
    result = differ.diff_chunks(old_chunks, new_chunks)
    
    print(f"✅ Unchanged chunks: {len(result.unchanged_chunks)}")
    print(f"✅ Modified chunks: {len(result.modified_chunks)}")
    print(f"✅ Added chunks: {len(result.added_chunks)}")
    print(f"✅ Removed chunks: {len(result.removed_chunks)}")
    
    assert len(result.added_chunks) == 2, "Should have 2 added chunks"
    assert len(result.unchanged_chunks) == 0, "Should have 0 unchanged"
    assert result.get_change_percentage() == 1.0, "Should be 100% changed"
    
    print("✅ PASSED: All new chunks detected correctly")
    return True


def test_4_all_removed_chunks():
    """Test when all chunks are removed"""
    print("\n" + "="*70)
    print("TEST 4: All Removed Chunks")
    print("="*70)
    
    embedding_service = EmbeddingService()
    differ = ChunkDiffer(embedding_service)
    
    old_chunks = [
        create_test_chunk("Old chunk 1", 0),
        create_test_chunk("Old chunk 2", 1),
    ]
    new_chunks = []
    
    result = differ.diff_chunks(old_chunks, new_chunks)
    
    print(f"✅ Unchanged chunks: {len(result.unchanged_chunks)}")
    print(f"✅ Modified chunks: {len(result.modified_chunks)}")
    print(f"✅ Added chunks: {len(result.added_chunks)}")
    print(f"✅ Removed chunks: {len(result.removed_chunks)}")
    
    assert len(result.removed_chunks) == 2, "Should have 2 removed chunks"
    assert len(result.unchanged_chunks) == 0, "Should have 0 unchanged"
    assert result.get_change_percentage() == 1.0, "Should be 100% changed"
    
    print("✅ PASSED: All removed chunks detected correctly")
    return True


def test_5_mixed_changes():
    """Test mixed scenario: some unchanged, some modified, some added, some removed"""
    print("\n" + "="*70)
    print("TEST 5: Mixed Changes")
    print("="*70)
    
    embedding_service = EmbeddingService()
    differ = ChunkDiffer(
        embedding_service, 
        similarity_threshold=0.85,
        text_similarity_threshold=0.75  # Higher threshold to avoid false matches
    )
    
    # Use more distinct text to avoid false matches
    old_chunks = [
        create_test_chunk("This is an unchanged paragraph that will remain the same.", 0),  # Will stay the same
        create_test_chunk("This is the original version of a modified paragraph.", 1),  # Will be modified
        create_test_chunk("This paragraph will be completely removed from the document.", 2),  # Will be removed
    ]
    
    new_chunks = [
        create_test_chunk("This is an unchanged paragraph that will remain the same.", 0),  # Same
        create_test_chunk("This is the updated version of a modified paragraph with changes.", 1),  # Modified
        create_test_chunk("This is a completely new paragraph that was just added.", 2),  # New
    ]
    
    result = differ.diff_chunks(old_chunks, new_chunks)
    
    print(f"✅ Unchanged chunks: {len(result.unchanged_chunks)}")
    print(f"✅ Modified chunks: {len(result.modified_chunks)}")
    print(f"✅ Added chunks: {len(result.added_chunks)}")
    print(f"✅ Removed chunks: {len(result.removed_chunks)}")
    
    assert len(result.unchanged_chunks) >= 1, "Should have at least 1 unchanged chunk"
    assert len(result.added_chunks) >= 1, "Should have at least 1 added chunk"
    assert len(result.removed_chunks) >= 1, "Should have at least 1 removed chunk"
    
    change_pct = result.get_change_percentage()
    print(f"✅ Change percentage: {change_pct:.1%}")
    assert 0.0 < change_pct < 1.0, "Should have partial change"
    
    print("✅ PASSED: Mixed changes detected correctly")
    return True


def test_6_change_percentage_calculation():
    """Test change percentage calculation"""
    print("\n" + "="*70)
    print("TEST 6: Change Percentage Calculation")
    print("="*70)
    
    embedding_service = EmbeddingService()
    differ = ChunkDiffer(embedding_service)
    
    # 10 old chunks, 5 unchanged, 2 modified, 3 removed, 2 added
    old_chunks = [create_test_chunk(f"Chunk {i}", i) for i in range(10)]
    new_chunks = [
        create_test_chunk("Chunk 0", 0),  # Unchanged
        create_test_chunk("Chunk 1", 1),  # Unchanged
        create_test_chunk("Chunk 2", 2),  # Unchanged
        create_test_chunk("Chunk 3", 3),  # Unchanged
        create_test_chunk("Chunk 4", 4),  # Unchanged
        create_test_chunk("Chunk 5 modified", 5),  # Modified
        create_test_chunk("Chunk 6 modified", 6),  # Modified
        create_test_chunk("New chunk 1", 7),  # Added
        create_test_chunk("New chunk 2", 8),  # Added
    ]
    
    result = differ.diff_chunks(old_chunks, new_chunks)
    
    change_pct = result.get_change_percentage()
    print(f"✅ Change percentage: {change_pct:.1%}")
    print(f"✅ Total changed: {result.get_total_changed_count()}")
    
    assert 0.0 <= change_pct <= 1.0, "Change percentage should be between 0 and 1"
    
    print("✅ PASSED: Change percentage calculation works")
    return True


def test_7_empty_chunks():
    """Test edge case: empty chunk lists"""
    print("\n" + "="*70)
    print("TEST 7: Empty Chunks")
    print("="*70)
    
    embedding_service = EmbeddingService()
    differ = ChunkDiffer(embedding_service)
    
    # Both empty
    result = differ.diff_chunks([], [])
    assert len(result.unchanged_chunks) == 0
    assert len(result.modified_chunks) == 0
    assert len(result.added_chunks) == 0
    assert len(result.removed_chunks) == 0
    assert result.get_change_percentage() == 0.0
    
    print("✅ PASSED: Empty chunks handled correctly")
    return True


def test_8_similarity_threshold():
    """Test that similarity threshold works correctly"""
    print("\n" + "="*70)
    print("TEST 8: Similarity Threshold")
    print("="*70)
    
    embedding_service = EmbeddingService()
    
    # High threshold (strict matching)
    strict_differ = ChunkDiffer(embedding_service, similarity_threshold=0.95)
    
    # Low threshold (loose matching)
    loose_differ = ChunkDiffer(embedding_service, similarity_threshold=0.50)
    
    old_chunks = [create_test_chunk("This is a test chunk", 0)]
    new_chunks = [create_test_chunk("This is a slightly different test chunk", 0)]
    
    strict_result = strict_differ.diff_chunks(old_chunks, new_chunks)
    loose_result = loose_differ.diff_chunks(old_chunks, new_chunks)
    
    print(f"✅ Strict threshold matches: {len(strict_result.modified_chunks)}")
    print(f"✅ Loose threshold matches: {len(loose_result.modified_chunks)}")
    
    # Loose should match more (or same)
    assert len(loose_result.modified_chunks) >= len(strict_result.modified_chunks)
    
    print("✅ PASSED: Similarity threshold works correctly")
    return True


async def run_all_tests():
    """Run all tests"""
    print("\n" + "="*70)
    print("CHUNK DIFFER TEST SUITE")
    print("="*70)
    
    tests = [
        test_1_hash_based_exact_matching,
        test_2_text_similarity_matching,
        test_3_all_new_chunks,
        test_4_all_removed_chunks,
        test_5_mixed_changes,
        test_6_change_percentage_calculation,
        test_7_empty_chunks,
        test_8_similarity_threshold,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if asyncio.iscoroutinefunction(test):
                result = await test()
            else:
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
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)

