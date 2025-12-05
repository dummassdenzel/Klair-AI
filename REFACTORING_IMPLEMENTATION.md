# Orchestrator Refactoring - Implementation Guide

## Summary of Changes Applied

### ✅ Completed
1. Created `query_config.py` with `RetrievalConfig` class
2. Added `_find_explicit_filename()` method
3. Refactored `_classify_query()` to return 4 types (greeting, general, document_listing, document_search)
4. Simplified `_select_relevant_files()` to use only Trie for explicit filenames
5. Added `_get_document_listing()` method

### 🔄 Remaining Changes Needed

## 1. Remove Query Rewriting

**Delete lines ~1089-1092:**
```python
# Step 0.5: Rewrite ambiguous queries using conversation context
rewritten_question = await self._rewrite_query(question, conversation_history)
# Use rewritten query for retrieval, but keep original for LLM response
retrieval_query = rewritten_question if rewritten_question != question else question
```

**Replace with:**
```python
# Use original question for retrieval - modern LLMs handle context natively
retrieval_query = question
```

## 2. Remove Pattern Matching Lists

**Delete lines ~1094-1113:**
- `listing_query_patterns` list
- `is_listing_query` detection
- `enumeration_patterns` list  
- `is_enumeration_query` detection

## 3. Replace Listing Query Handling

**Delete lines ~1118-1244** (entire listing query special case block)

**Replace with:**
```python
# Handle document_listing queries
if query_type == 'document_listing':
    result = await self._get_document_listing()
    result.response_time = asyncio.get_event_loop().time() - start_time
    return result
```

## 4. Add _retrieve_chunks() Method

**Add before query() method:**
```python
async def _retrieve_chunks(self, query: str, query_type: str, explicit_filename: Optional[str] = None) -> tuple:
    """
    Single retrieval pipeline for all document queries.
    
    Returns:
        (documents, metadatas, scores, retrieval_count, rerank_count)
    """
    # Get retrieval parameters
    params = self.retrieval_config.get_retrieval_params(query_type, False)
    
    top_k = params['top_k']
    rerank_top_k = params['rerank_top_k']
    final_top_k = params['final_top_k']
    
    logger.info(f"Retrieval params: top_k={top_k}, rerank_top_k={rerank_top_k}, final_top_k={final_top_k}")
    
    # Step 1: Semantic search
    query_embedding = self.embedding_service.encode_single_text(query)
    semantic_results = await self.vector_store.search_similar(query_embedding, top_k)
    
    if not semantic_results['documents'] or not semantic_results['documents'][0]:
        return ([], [], [], 0, 0)
    
    # Step 2: BM25 boost
    bm25_results = self.bm25_service.search(query, top_k=top_k)
    bm25_hits = set()
    for doc_id, score, meta in (bm25_results or []):
        fp = meta.get('file_path', '')
        cid = meta.get('chunk_id')
        if fp and cid is not None:
            bm25_hits.add((fp, cid))
    
    # Step 3: Combine semantic + BM25 boost
    documents = []
    metadatas = []
    scores = []
    
    for doc, meta, dist in zip(
        semantic_results['documents'][0],
        semantic_results['metadatas'][0],
        semantic_results['distances'][0]
    ):
        if not doc or not doc.strip():
            continue
        
        base_score = max(0.0, 1.0 - float(dist))
        fp = meta.get('file_path', '')
        cid = meta.get('chunk_id')
        
        # Apply BM25 boost
        boost = self.retrieval_config.bm25_boost if (fp, cid) in bm25_hits else 0.0
        final_score = min(1.0, base_score + boost)
        
        documents.append(doc)
        metadatas.append(meta)
        scores.append(final_score)
    
    retrieval_count = len(documents)
    
    # Step 4: Re-ranking (if enabled)
    rerank_count = 0
    if rerank_top_k > 0 and len(documents) > final_top_k:
        logger.info(f"Re-ranking top {min(rerank_top_k, len(documents))} of {len(documents)} results")
        
        docs_to_rerank = documents[:min(rerank_top_k, len(documents))]
        metas_to_rerank = metadatas[:min(rerank_top_k, len(metadatas))]
        scores_to_rerank = scores[:min(rerank_top_k, len(scores))]
        
        reranked_docs, reranked_metas, reranked_scores = self.reranker.rerank_with_metadata(
            query=query,
            documents=docs_to_rerank,
            metadata_list=metas_to_rerank,
            scores_list=scores_to_rerank,
            top_k=final_top_k
        )
        
        # Combine reranked + remaining
        remaining_docs = documents[min(rerank_top_k, len(documents)):]
        remaining_metas = metadatas[min(rerank_top_k, len(metadatas)):]
        remaining_scores = scores[min(rerank_top_k, len(scores)):]
        
        documents = reranked_docs + remaining_docs
        metadatas = reranked_metas + remaining_metas
        scores = reranked_scores + remaining_scores
        rerank_count = len(docs_to_rerank)
    
    # Step 5: Filter by explicit filename if provided
    if explicit_filename:
        filtered_docs = []
        filtered_metas = []
        filtered_scores = []
        for doc, meta, score in zip(documents, metadatas, scores):
            if explicit_filename.lower() in meta.get('file_path', '').lower():
                filtered_docs.append(doc)
                filtered_metas.append(meta)
                filtered_scores.append(score)
        if filtered_docs:
            documents = filtered_docs
            metadatas = filtered_metas
            scores = filtered_scores
    
    return (documents, metadatas, scores, retrieval_count, rerank_count)
```

## 5. Remove Enumeration Query Special Handling

**Delete lines ~1430-1461** (enumeration query bypass code)

## 6. Simplify Main Query Flow

**Replace the entire retrieval section (after listing query handling) with:**

```python
# Document search - check for explicit filename
explicit_filename = self._find_explicit_filename(question)

# Retrieve chunks using single pipeline
documents, metadatas, scores, retrieval_count, rerank_count = await self._retrieve_chunks(
    question, query_type, explicit_filename
)

if not documents:
    return QueryResult(
        message="I don't have information about that in the current documents.",
        sources=[],
        response_time=asyncio.get_event_loop().time() - start_time,
        query_type=query_type,
        retrieval_count=0,
        rerank_count=0
    )

# Group chunks by file
file_chunks = {}
for doc, meta, score in zip(documents, metadatas, scores):
    file_path = meta.get("file_path", "Unknown")
    if file_path not in file_chunks:
        file_chunks[file_path] = []
    file_chunks[file_path].append({
        "text": doc,
        "score": score,
        "chunk_id": meta.get("chunk_id", 0),
        "metadata": meta
    })

# Build context and sources
sources = []
context_parts = []

for file_path, chunks in file_chunks.items():
    chunks.sort(key=lambda x: x["chunk_id"])
    filename = Path(file_path).name
    file_text = "\n".join([chunk["text"] for chunk in chunks])
    
    context_parts.append(f"[Document: {filename}]\n{file_text}")
    
    avg_score = sum(chunk["score"] for chunk in chunks) / len(chunks)
    sources.append({
        "file_path": file_path,
        "relevance_score": round(min(1.0, avg_score * 50), 3),
        "content_snippet": file_text[:300] + "..." if len(file_text) > 300 else file_text,
        "chunks_found": len(chunks),
        "file_type": chunks[0]["metadata"].get("file_type", "unknown")
    })

sources.sort(key=lambda x: x["relevance_score"], reverse=True)

# Limit sources
source_limit = self.retrieval_config.get_source_limit(query_type, explicit_filename is not None)
sources = sources[:source_limit]

# Generate response with enhanced prompt
context = "\n\n---\n\n".join(context_parts)

# Enhanced prompt for comprehensive extraction
response_text = await self.llm_service.generate_response(
    question,
    context,
    conversation_history=conversation_history or []
)
```

## 7. Update LLM Service Prompt

**In llm_service.py, enhance the prompt template to include:**

```
INSTRUCTIONS:
- Answer the question comprehensively using ALL relevant information
- If the question asks for a list (e.g., "list all speakers"), be thorough and include ALL items
- If information appears in multiple chunks, combine it into a complete answer
- Cite specific documents when referencing information
```

## 8. Delete Unused Methods

**Remove these methods entirely:**
- `_rewrite_query()` (~967-1020)
- `_is_simple_filename_query()` (~597-669) 
- `_extract_filename_patterns()` (~671-720)
- `_llm_select_files()` (~784-887)

## Expected Results

- **Lines removed:** ~325 lines
- **Lines added:** ~150 lines (new methods)
- **Net reduction:** ~175 lines (~17% reduction)
- **Complexity reduction:** Significant (removed 5+ pattern lists, 3 special cases)

## Testing Checklist

After refactoring, test these queries:

1. ✅ "List all speakers" - Should retrieve all chunks, LLM extracts comprehensively
2. ✅ "What documents do we have?" - Should use document_listing path
3. ✅ "What's in sales_report.pdf?" - Should use explicit filename detection
4. ✅ "Who attended?" - Should use normal retrieval with comprehensive prompt
5. ✅ [After context] "Who drove that?" - Should work without query rewriting

