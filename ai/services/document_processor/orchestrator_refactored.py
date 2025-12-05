"""
REFACTORED Document Processor Orchestrator

This is a comprehensive refactoring that:
1. Removes enumeration query special handling
2. Removes query rewriting
3. Simplifies file selection
4. Consolidates query classification
5. Uses single retrieval pipeline for all queries
6. Externalizes configuration

This file serves as a reference implementation.
The actual changes will be applied to orchestrator.py incrementally.
"""

import asyncio
import logging
import re
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path

from .models import QueryResult, ProcessingResult, FileMetadata
from .text_extractor import TextExtractor
from .chunker import DocumentChunker
from .embedding_service import EmbeddingService
from .vector_store import VectorStoreService
from .llm_service import LLMService
from .file_validator import FileValidator
from .bm25_service import BM25Service
from .hybrid_search import HybridSearchService
from .reranker_service import ReRankingService
from .filename_trie import FilenameTrie
from .query_config import RetrievalConfig, default_retrieval_config
from database import DatabaseService

logger = logging.getLogger(__name__)


class DocumentProcessorOrchestratorRefactored:
    """
    Refactored orchestrator with simplified query processing.
    
    Key improvements:
    - Single retrieval pipeline for all queries
    - No pattern matching lists
    - No query rewriting
    - Simplified file selection
    - Configuration externalized
    """
    
    def __init__(self, 
                 persist_dir: str = "./chroma_db",
                 embed_model_name: str = "BAAI/bge-small-en-v1.5",
                 max_file_size_mb: int = 50,
                 chunk_size: int = 1000,
                 chunk_overlap: int = 200,
                 ollama_base_url: str = "http://localhost:11434",
                 ollama_model: str = "tinyllama",
                 gemini_api_key: Optional[str] = None,
                 gemini_model: str = "gemini-2.5-pro",
                 llm_provider: str = "ollama",
                 retrieval_config: RetrievalConfig = None):
        
        # Initialize services (same as before)
        self.text_extractor = TextExtractor()
        self.chunker = DocumentChunker(chunk_size, chunk_overlap)
        self.embedding_service = EmbeddingService(embed_model_name)
        self.vector_store = VectorStoreService(persist_dir)
        self.llm_service = LLMService(
            ollama_base_url=ollama_base_url,
            ollama_model=ollama_model,
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
            provider=llm_provider
        )
        self.file_validator = FileValidator(max_file_size_mb)
        self.database_service = DatabaseService()
        self.bm25_service = BM25Service(persist_dir)
        self.hybrid_search = HybridSearchService(k=60)
        self.reranker = ReRankingService(model_name="cross-encoder/ms-marco-MiniLM-L-6-v2")
        self.filename_trie = FilenameTrie()
        
        # Retrieval configuration
        self.retrieval_config = retrieval_config or default_retrieval_config
        
        # State tracking (simplified - consider moving to database)
        self.file_hashes: Dict[str, str] = {}
        self.file_metadata: Dict[str, FileMetadata] = {}
        self.current_directory: Optional[str] = None
        self.is_initializing: bool = False
        self.files_being_processed: set = set()
        
        logger.info("DocumentProcessorOrchestrator initialized (refactored)")
    
    async def _classify_query(self, question: str, conversation_history: list = None) -> str:
        """
        Unified query classification.
        
        Returns:
            'greeting' - Simple greetings
            'general' - General questions not about documents
            'document_listing' - Requests to list/show all documents
            'document_search' - Questions requiring document retrieval
        """
        try:
            # Build conversation context
            conversation_context = ""
            if conversation_history:
                conversation_context = "\n\nRecent conversation:\n"
                for msg in conversation_history[-2:]:
                    role = "User" if msg["role"] == "user" else "Assistant"
                    conversation_context += f"{role}: {msg['content'][:150]}...\n"
            
            classification_prompt = f"""Classify this query into ONE category:

{conversation_context}
USER QUERY: "{question}"

CATEGORIES:
1. greeting - Greetings, pleasantries ("hello", "hi", "thanks", "goodbye")
2. general - Questions about the AI itself, not documents ("what can you do?", "how does this work?")
3. document_listing - Requests to list/show documents ("what files do we have?", "list all documents", "show me all PDFs")
4. document_search - Questions requiring document content ("what's in sales_report.pdf?", "who attended?", "list all speakers")

IMPORTANT:
- If query contains pronouns (that, it, this) or references previous context → document_search
- If query asks to "list" or "show" documents/files → document_listing
- If query asks about document CONTENT → document_search

Respond with ONLY ONE WORD: greeting, general, document_listing, or document_search"""

            response = await self.llm_service.generate_simple(classification_prompt)
            classification = response.strip().lower()
            
            # Validate and default to document_search if uncertain
            valid_types = ['greeting', 'general', 'document_listing', 'document_search']
            if classification not in valid_types:
                logger.warning(f"Invalid classification '{classification}', defaulting to document_search")
                return 'document_search'
            
            logger.info(f"Query classified as: {classification}")
            return classification
            
        except Exception as e:
            logger.error(f"Classification failed: {e}, defaulting to document_search")
            return 'document_search'
    
    def _find_explicit_filename(self, question: str) -> Optional[str]:
        """
        Simple filename detection: only for explicit filename mentions.
        
        Returns:
            Filename if explicitly mentioned (quoted or obvious pattern), None otherwise
        """
        # Check for quoted filenames
        quoted = re.findall(r'"([^"]+)"', question)
        if quoted:
            return quoted[0]
        
        # Check for obvious filename patterns (e.g., "sales_report.pdf", "TCO005")
        filename_pattern = re.search(r'\b([A-Z][A-Z0-9_-]+\.(pdf|docx|txt|xlsx|pptx)|[A-Z][A-Z0-9]{2,})\b', question)
        if filename_pattern:
            return filename_pattern.group(1)
        
        return None
    
    async def _get_document_listing(self) -> QueryResult:
        """
        Get listing of all documents from database.
        Used for document_listing queries.
        """
        try:
            from database.database import get_db
            from database.models import IndexedDocument
            from sqlalchemy import select
            
            all_docs = []
            async for db_session in get_db():
                stmt = select(IndexedDocument).where(
                    IndexedDocument.processing_status.in_(["indexed", "metadata_only"])
                )
                result = await db_session.execute(stmt)
                all_docs = result.scalars().all()
                break
            
            if not all_docs:
                return QueryResult(
                    message="No documents are currently indexed.",
                    sources=[],
                    response_time=0.0,
                    query_type="document_listing",
                    retrieval_count=0,
                    rerank_count=0
                )
            
            # Build context from all documents
            sources = []
            context_parts = []
            for doc in all_docs:
                filename = Path(doc.file_path).name
                
                if doc.processing_status == "metadata_only":
                    preview = f"[Indexing in progress...] {filename}"
                else:
                    preview = doc.content_preview if doc.content_preview else ""
                    if not preview and doc.chunks_count > 0:
                        preview = f"[File indexed with {doc.chunks_count} chunk(s)]"
                
                context_parts.append(f"[Document: {filename}]\n{preview}")
                sources.append({
                    "file_path": doc.file_path,
                    "relevance_score": 1.0,
                    "content_snippet": preview[:300] + "..." if len(preview) > 300 else preview,
                    "chunks_found": doc.chunks_count,
                    "file_type": doc.file_type,
                    "processing_status": doc.processing_status
                })
            
            context = "\n\n---\n\n".join(context_parts)
            
            # Generate response with comprehensive prompt
            response_prompt = f"""You are a document assistant. The user asked to see all documents.

Here are all indexed documents:

{context}

Provide a clear, organized list of all documents. For each document, mention:
- The filename
- Brief description if available
- File type
- Status (if still indexing)

Be comprehensive and list ALL documents mentioned above."""

            response_text = await self.llm_service.generate_simple(response_prompt)
            
            return QueryResult(
                message=response_text,
                sources=sources,
                response_time=0.0,  # Will be set by caller
                query_type="document_listing",
                retrieval_count=len(all_docs),
                rerank_count=0
            )
            
        except Exception as e:
            logger.error(f"Document listing failed: {e}")
            raise
    
    async def _retrieve_chunks(self, query: str, query_type: str, explicit_filename: Optional[str] = None) -> tuple:
        """
        Single retrieval pipeline for all document queries.
        
        Returns:
            (documents, metadatas, scores, retrieval_count, rerank_count)
        """
        # Get retrieval parameters
        is_listing = (query_type == 'document_listing')
        params = self.retrieval_config.get_retrieval_params(query_type, is_listing)
        
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
        
        # Step 4: Re-ranking (if enabled for this query type)
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
    
    async def query(self, question: str, max_results: int = 15, conversation_history: list = None) -> QueryResult:
        """
        Simplified query method with single retrieval pipeline.
        """
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Step 1: Classify query
            query_type = await self._classify_query(question, conversation_history)
            
            # Step 2: Handle non-document queries
            if query_type in ['greeting', 'general']:
                response_text = await self._generate_direct_response(question, query_type)
                return QueryResult(
                    message=response_text,
                    sources=[],
                    response_time=asyncio.get_event_loop().time() - start_time,
                    query_type=query_type,
                    retrieval_count=0,
                    rerank_count=0
                )
            
            # Step 3: Handle document listing
            if query_type == 'document_listing':
                result = await self._get_document_listing()
                result.response_time = asyncio.get_event_loop().time() - start_time
                return result
            
            # Step 4: Document search - check for explicit filename
            explicit_filename = self._find_explicit_filename(question)
            
            # Step 5: Retrieve chunks using single pipeline
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
            
            # Step 6: Group chunks by file
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
            
            # Step 7: Build context and sources
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
            
            # Step 8: Limit sources
            source_limit = self.retrieval_config.get_source_limit(query_type, explicit_filename is not None)
            sources = sources[:source_limit]
            
            # Step 9: Generate response with comprehensive prompt
            context = "\n\n---\n\n".join(context_parts)
            
            # Enhanced prompt for comprehensive extraction
            response_prompt = f"""You are a document analysis assistant. Answer the user's question based on the provided document context.

USER QUESTION: {question}

DOCUMENT CONTEXT:
{context}

INSTRUCTIONS:
- Answer the question comprehensively using ALL relevant information from the documents
- If the question asks for a list (e.g., "list all speakers", "all participants"), be thorough and include ALL items mentioned
- If information appears in multiple chunks, combine it into a complete answer
- Cite specific documents when referencing information
- If you cannot find the answer, say so clearly

Your response:"""

            response_text = await self.llm_service.generate_response(
                question,
                context,
                conversation_history=conversation_history or []
            )
            
            return QueryResult(
                message=response_text,
                sources=sources,
                response_time=asyncio.get_event_loop().time() - start_time,
                query_type=query_type,
                retrieval_count=retrieval_count,
                rerank_count=rerank_count
            )
            
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return QueryResult(
                message=f"Sorry, I encountered an error: {str(e)}",
                sources=[],
                response_time=asyncio.get_event_loop().time() - start_time,
                query_type="error",
                retrieval_count=0,
                rerank_count=0
            )
    
    # ... (keep all other methods from original orchestrator unchanged)
    # This is just the query processing refactoring

