"""
Unit tests for UpdateExecutor

Tests:
1. Checkpoint creation
2. Full re-index execution
3. Chunk update execution
4. Smart hybrid execution
5. Rollback on failure
6. Update verification
7. Error handling
"""

import sys
import os
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch, MagicMock
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import modules that will be patched
import database.database
import services.document_processor.extraction.file_validator

from services.document_processor import (
    UpdateExecutor, UpdateTask, UpdateResult, UpdateStrategy,
    ChunkDiffResult, ChunkMatch, DocumentChunk
)


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


async def test_1_checkpoint_creation():
    """Test checkpoint creation"""
    print("\n" + "="*70)
    print("TEST 1: Checkpoint Creation")
    print("="*70)
    
    # Mock services
    vector_store = Mock()
    vector_store.get_document_chunks = Mock(return_value={
        'ids': ['chunk1', 'chunk2'],
        'documents': ['Text 1', 'Text 2'],
        'metadatas': [{'chunk_id': 0}, {'chunk_id': 1}],
        'embeddings': [[0.1, 0.2], [0.3, 0.4]]
    })
    
    bm25_service = Mock()
    text_extractor = Mock()
    chunker = Mock()
    embedding_service = Mock()
    database_service = Mock()
    chunk_differ = Mock()
    
    executor = UpdateExecutor(
        vector_store=vector_store,
        bm25_service=bm25_service,
        text_extractor=text_extractor,
        chunker=chunker,
        embedding_service=embedding_service,
        database_service=database_service,
        chunk_differ=chunk_differ
    )
    
    # Mock database query
    async def mock_get_db_generator():
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_doc = Mock()
        mock_doc.file_hash = "hash123"
        mock_doc.file_size = 1024
        mock_doc.chunks_count = 2
        mock_doc.content_preview = "Preview"
        mock_doc.processing_status = "indexed"
        mock_result.scalar_one_or_none = Mock(return_value=mock_doc)
        mock_session.execute = AsyncMock(return_value=mock_result)
        yield mock_session
    
    with patch('database.database.get_db', return_value=mock_get_db_generator()):
        checkpoint = await executor._create_checkpoint("test.txt")
        
        assert checkpoint.file_path == "test.txt", "Checkpoint should have correct file path"
        assert len(checkpoint.old_chunks_data) == 2, "Checkpoint should have 2 chunks"
        assert checkpoint.old_metadata is not None, "Checkpoint should have metadata"
        
        print(f"✅ Checkpoint created: {len(checkpoint.old_chunks_data)} chunks")
        print("✅ PASSED: Checkpoint creation works")
        return True


async def test_2_full_reindex_execution():
    """Test full re-index execution"""
    print("\n" + "="*70)
    print("TEST 2: Full Re-index Execution")
    print("="*70)
    
    # Mock services
    vector_store = Mock()
    vector_store.remove_document_chunks = AsyncMock()
    vector_store.batch_insert_chunks = AsyncMock()
    vector_store.get_document_chunks = Mock(return_value={'ids': []})
    
    bm25_service = Mock()
    bm25_service.add_documents = Mock()
    
    text_extractor = Mock()
    text_extractor.extract_text_async = AsyncMock(return_value="Test document text")
    
    chunker = Mock()
    chunker.create_chunks = Mock(return_value=[
        create_test_chunk("Chunk 1", 0),
        create_test_chunk("Chunk 2", 1)
    ])
    
    embedding_service = Mock()
    embedding_service.encode_texts = Mock(return_value=[[0.1, 0.2], [0.3, 0.4]])
    
    database_service = Mock()
    database_service.store_document_metadata = AsyncMock()
    
    chunk_differ = Mock()
    
    executor = UpdateExecutor(
        vector_store=vector_store,
        bm25_service=bm25_service,
        text_extractor=text_extractor,
        chunker=chunker,
        embedding_service=embedding_service,
        database_service=database_service,
        chunk_differ=chunk_differ
    )
    
    # Mock file validator
    with patch('services.document_processor.extraction.file_validator.FileValidator') as mock_validator_class:
        mock_validator = Mock()
        mock_validator.extract_file_metadata = Mock(return_value={
            "file_type": "txt",
            "size_bytes": 1024,
            "modified_at": datetime.utcnow()
        })
        mock_validator.calculate_file_hash = Mock(return_value="hash123")
        mock_validator_class.return_value = mock_validator
        
        task = UpdateTask(
            priority=500,
            file_path="test.txt",
            update_type="modified",
            strategy=UpdateStrategy.FULL_REINDEX
        )
        
        chunks_updated = await executor._execute_full_reindex(task)
        
        assert chunks_updated == 2, "Should have updated 2 chunks"
        assert vector_store.remove_document_chunks.called, "Should remove old chunks"
        assert vector_store.batch_insert_chunks.called, "Should insert new chunks"
        assert bm25_service.add_documents.called, "Should update BM25"
        assert database_service.store_document_metadata.called, "Should update database"
        
        print(f"✅ Updated {chunks_updated} chunks")
        print("✅ PASSED: Full re-index execution works")
        return True


async def test_3_chunk_update_execution():
    """Test chunk update execution"""
    print("\n" + "="*70)
    print("TEST 3: Chunk Update Execution")
    print("="*70)
    
    # Mock services
    vector_store = Mock()
    vector_store.remove_document_chunks = AsyncMock()
    vector_store.batch_insert_chunks = AsyncMock()
    vector_store.get_document_chunks = Mock(return_value={'ids': []})
    
    bm25_service = Mock()
    bm25_service.add_documents = Mock()
    
    text_extractor = Mock()
    chunker = Mock()
    
    embedding_service = Mock()
    embedding_service.encode_texts = Mock(return_value=[[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]])
    
    database_service = Mock()
    database_service.store_document_metadata = AsyncMock()
    
    chunk_differ = Mock()
    
    executor = UpdateExecutor(
        vector_store=vector_store,
        bm25_service=bm25_service,
        text_extractor=text_extractor,
        chunker=chunker,
        embedding_service=embedding_service,
        database_service=database_service,
        chunk_differ=chunk_differ
    )
    
    # Mock file validator
    with patch('services.document_processor.extraction.file_validator.FileValidator') as mock_validator_class:
        mock_validator = Mock()
        mock_validator.extract_file_metadata = Mock(return_value={
            "file_type": "txt",
            "size_bytes": 1024,
            "modified_at": datetime.utcnow()
        })
        mock_validator.calculate_file_hash = Mock(return_value="hash123")
        mock_validator_class.return_value = mock_validator
        
        task = UpdateTask(
            priority=500,
            file_path="test.txt",
            update_type="modified",
            strategy=UpdateStrategy.CHUNK_UPDATE
        )
        
        # Create diff result: 1 unchanged, 1 modified, 1 added
        diff_result = create_diff_result(unchanged=1, modified=1, added=1, removed=0)
        
        chunks_updated = await executor._execute_chunk_update(task, diff_result)
        
        assert chunks_updated == 3, "Should have updated 3 chunks (1 unchanged + 1 modified + 1 added)"
        assert vector_store.remove_document_chunks.called, "Should remove old chunks"
        assert vector_store.batch_insert_chunks.called, "Should insert new chunks"
        assert embedding_service.encode_texts.called, "Should generate embeddings"
        
        print(f"✅ Updated {chunks_updated} chunks")
        print("✅ PASSED: Chunk update execution works")
        return True


async def test_4_rollback_on_failure():
    """Test rollback on failure"""
    print("\n" + "="*70)
    print("TEST 4: Rollback on Failure")
    print("="*70)
    
    # Mock services
    vector_store = Mock()
    vector_store.remove_document_chunks = AsyncMock()
    vector_store.batch_insert_chunks = AsyncMock()
    vector_store.get_document_chunks = Mock(return_value={
        'ids': ['chunk1'],
        'documents': ['Old text'],
        'metadatas': [{'chunk_id': 0, 'start_pos': 0, 'end_pos': 8}],
        'embeddings': [[0.1, 0.2]]
    })
    
    bm25_service = Mock()
    text_extractor = Mock()
    text_extractor.extract_text_async = AsyncMock(side_effect=Exception("Extraction failed"))
    
    chunker = Mock()
    embedding_service = Mock()
    embedding_service.encode_single_text = Mock(return_value=[0.1, 0.2])
    
    database_service = Mock()
    database_service.store_document_metadata = AsyncMock()
    
    chunk_differ = Mock()
    
    executor = UpdateExecutor(
        vector_store=vector_store,
        bm25_service=bm25_service,
        text_extractor=text_extractor,
        chunker=chunker,
        embedding_service=embedding_service,
        database_service=database_service,
        chunk_differ=chunk_differ
    )
    
    # Mock database query for checkpoint
    async def mock_get_db_generator():
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_doc = Mock()
        mock_doc.file_hash = "hash123"
        mock_doc.file_size = 1024
        mock_doc.chunks_count = 1
        mock_doc.content_preview = "Preview"
        mock_doc.processing_status = "indexed"
        mock_result.scalar_one_or_none = Mock(return_value=mock_doc)
        mock_session.execute = AsyncMock(return_value=mock_result)
        yield mock_session
    
    with patch('database.database.get_db', return_value=mock_get_db_generator()):
        task = UpdateTask(
            priority=500,
            file_path="test.txt",
            update_type="modified",
            strategy=UpdateStrategy.FULL_REINDEX
        )
        
        result = await executor.execute_update(task)
        
        assert not result.success, "Update should have failed"
        assert result.error_message is not None, "Should have error message"
        assert "Extraction failed" in result.error_message, "Should have correct error"
        
        # Check that rollback was called (remove_document_chunks called twice: once for update, once for rollback)
        assert vector_store.remove_document_chunks.call_count >= 1, "Should have attempted rollback"
        
        print(f"✅ Rollback executed: {result.error_message}")
        print("✅ PASSED: Rollback on failure works")
        return True


async def test_5_update_verification():
    """Test update verification"""
    print("\n" + "="*70)
    print("TEST 5: Update Verification")
    print("="*70)
    
    # Mock services
    vector_store = Mock()
    vector_store.get_document_chunks = Mock(return_value={
        'ids': ['chunk1', 'chunk2'],
        'documents': ['Text 1', 'Text 2']
    })
    
    bm25_service = Mock()
    text_extractor = Mock()
    chunker = Mock()
    embedding_service = Mock()
    database_service = Mock()
    chunk_differ = Mock()
    
    executor = UpdateExecutor(
        vector_store=vector_store,
        bm25_service=bm25_service,
        text_extractor=text_extractor,
        chunker=chunker,
        embedding_service=embedding_service,
        database_service=database_service,
        chunk_differ=chunk_differ
    )
    
    # Mock database query
    async def mock_get_db_generator():
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_doc = Mock()
        mock_doc.processing_status = "indexed"
        mock_result.scalar_one_or_none = Mock(return_value=mock_doc)
        mock_session.execute = AsyncMock(return_value=mock_result)
        yield mock_session
    
    with patch('database.database.get_db', return_value=mock_get_db_generator()):
        # Should not raise exception
        await executor._verify_update("test.txt")
        
        print("✅ Verification passed")
        print("✅ PASSED: Update verification works")
        return True


async def test_6_verification_failure():
    """Test verification failure when chunks don't exist"""
    print("\n" + "="*70)
    print("TEST 6: Verification Failure")
    print("="*70)
    
    # Mock services
    vector_store = Mock()
    vector_store.get_document_chunks = Mock(return_value=None)  # No chunks
    
    bm25_service = Mock()
    text_extractor = Mock()
    chunker = Mock()
    embedding_service = Mock()
    database_service = Mock()
    chunk_differ = Mock()
    
    executor = UpdateExecutor(
        vector_store=vector_store,
        bm25_service=bm25_service,
        text_extractor=text_extractor,
        chunker=chunker,
        embedding_service=embedding_service,
        database_service=database_service,
        chunk_differ=chunk_differ
    )
    
    try:
        await executor._verify_update("test.txt")
        assert False, "Should have raised exception"
    except ValueError as e:
        assert "No chunks found" in str(e), "Should have correct error message"
        print(f"✅ Verification correctly failed: {e}")
        print("✅ PASSED: Verification failure works")
        return True


async def test_7_smart_hybrid_execution():
    """Test smart hybrid execution"""
    print("\n" + "="*70)
    print("TEST 7: Smart Hybrid Execution")
    print("="*70)
    
    # Mock services (same setup as chunk update)
    vector_store = Mock()
    vector_store.remove_document_chunks = AsyncMock()
    vector_store.batch_insert_chunks = AsyncMock()
    vector_store.get_document_chunks = Mock(return_value={'ids': []})
    
    bm25_service = Mock()
    bm25_service.add_documents = Mock()
    
    text_extractor = Mock()
    chunker = Mock()
    
    embedding_service = Mock()
    embedding_service.encode_texts = Mock(return_value=[[0.1, 0.2], [0.3, 0.4]])
    
    database_service = Mock()
    database_service.store_document_metadata = AsyncMock()
    
    chunk_differ = Mock()
    
    executor = UpdateExecutor(
        vector_store=vector_store,
        bm25_service=bm25_service,
        text_extractor=text_extractor,
        chunker=chunker,
        embedding_service=embedding_service,
        database_service=database_service,
        chunk_differ=chunk_differ
    )
    
    # Mock file validator
    with patch('services.document_processor.extraction.file_validator.FileValidator') as mock_validator_class:
        mock_validator = Mock()
        mock_validator.extract_file_metadata = Mock(return_value={
            "file_type": "txt",
            "size_bytes": 1024,
            "modified_at": datetime.utcnow()
        })
        mock_validator.calculate_file_hash = Mock(return_value="hash123")
        mock_validator_class.return_value = mock_validator
        
        task = UpdateTask(
            priority=500,
            file_path="test.txt",
            update_type="modified",
            strategy=UpdateStrategy.SMART_HYBRID
        )
        
        diff_result = create_diff_result(unchanged=1, modified=1, added=0, removed=0)
        
        chunks_updated = await executor._execute_smart_hybrid(task, diff_result)
        
        assert chunks_updated == 2, "Should have updated 2 chunks"
        print(f"✅ Updated {chunks_updated} chunks")
        print("✅ PASSED: Smart hybrid execution works")
        return True


async def test_8_chunk_update_fallback():
    """Test chunk update falls back to full re-index if no diff result"""
    print("\n" + "="*70)
    print("TEST 8: Chunk Update Fallback")
    print("="*70)
    
    # Mock services
    vector_store = Mock()
    vector_store.remove_document_chunks = AsyncMock()
    vector_store.batch_insert_chunks = AsyncMock()
    vector_store.get_document_chunks = Mock(return_value={'ids': []})
    
    bm25_service = Mock()
    bm25_service.add_documents = Mock()
    
    text_extractor = Mock()
    text_extractor.extract_text_async = AsyncMock(return_value="Test text")
    
    chunker = Mock()
    chunker.create_chunks = Mock(return_value=[create_test_chunk("Chunk 1", 0)])
    
    embedding_service = Mock()
    embedding_service.encode_texts = Mock(return_value=[[0.1, 0.2]])
    
    database_service = Mock()
    database_service.store_document_metadata = AsyncMock()
    
    chunk_differ = Mock()
    
    executor = UpdateExecutor(
        vector_store=vector_store,
        bm25_service=bm25_service,
        text_extractor=text_extractor,
        chunker=chunker,
        embedding_service=embedding_service,
        database_service=database_service,
        chunk_differ=chunk_differ
    )
    
    # Mock file validator
    with patch('services.document_processor.extraction.file_validator.FileValidator') as mock_validator_class:
        mock_validator = Mock()
        mock_validator.extract_file_metadata = Mock(return_value={
            "file_type": "txt",
            "size_bytes": 1024,
            "modified_at": datetime.utcnow()
        })
        mock_validator.calculate_file_hash = Mock(return_value="hash123")
        mock_validator_class.return_value = mock_validator
        
        task = UpdateTask(
            priority=500,
            file_path="test.txt",
            update_type="modified",
            strategy=UpdateStrategy.CHUNK_UPDATE
        )
        
        # No diff result provided
        chunks_updated = await executor._execute_chunk_update(task, None)
        
        assert chunks_updated == 1, "Should have updated 1 chunk (full re-index)"
        assert text_extractor.extract_text_async.called, "Should have extracted text (full re-index)"
        
        print("✅ Fell back to full re-index")
        print("✅ PASSED: Chunk update fallback works")
        return True


async def run_all_tests():
    """Run all tests"""
    print("\n" + "="*70)
    print("UPDATE EXECUTOR TEST SUITE")
    print("="*70)
    
    tests = [
        test_1_checkpoint_creation,
        test_2_full_reindex_execution,
        test_3_chunk_update_execution,
        test_4_rollback_on_failure,
        test_5_update_verification,
        test_6_verification_failure,
        test_7_smart_hybrid_execution,
        test_8_chunk_update_fallback,
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

