"""
RetrievalService — owns chunk retrieval and context assembly.

Responsibilities:
- Hybrid search: semantic (ChromaDB) + keyword (BM25) fused via RRF.
- Explicit-filename detection and file-priority selection.
- Context building: single-file mode, multi-file mode, optional compression.
- Document listing (DB query + LLM-formatted response).

The orchestrator passes a shared FilenameTrie reference so the trie updated
by IndexingService is immediately visible here without any synchronisation.
"""

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import QueryResult
from .extraction.embedding_service import EmbeddingService
from .storage.vector_store import VectorStoreService
from .storage.bm25_service import BM25Service
from .retrieval.hybrid_search import HybridSearchService
from .retrieval.filename_trie import FilenameTrie
from .llm.llm_service import LLMService
from .query_config import RetrievalConfig, default_retrieval_config, is_aggregation_query, CONTEXT_CHUNK_SEP
from .corpus_summary import summarize_corpus


logger = logging.getLogger(__name__)


class RetrievalService:
    """
    Owns the read side of the RAG pipeline: retrieve → build context.

    filename_trie is passed in by the orchestrator and is the same object held
    by IndexingService, so all trie mutations are immediately reflected here.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService,
        vector_store: VectorStoreService,
        bm25_service: BM25Service,
        hybrid_search: HybridSearchService,
        llm_service: LLMService,
        retrieval_config: RetrievalConfig,
        filename_trie: FilenameTrie,
    ) -> None:
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.bm25_service = bm25_service
        self.hybrid_search = hybrid_search
        self.llm_service = llm_service
        self.retrieval_config = retrieval_config
        self.filename_trie = filename_trie

    # ------------------------------------------------------------------
    # Public API (called by QueryPipelineService)
    # ------------------------------------------------------------------

    async def get_all_indexed_docs(self) -> List[Any]:
        """Return all indexed documents (indexed or metadata_only) from the DB."""
        from database.database import AsyncSessionLocal
        from database.models import IndexedDocument
        from sqlalchemy import select

        async with AsyncSessionLocal() as db_session:
            stmt = select(IndexedDocument).where(
                IndexedDocument.processing_status.in_(["indexed", "metadata_only"])
            )
            result = await db_session.execute(stmt)
            return list(result.scalars().all())

    async def get_document_listing(self, question: str = "") -> QueryResult:
        """
        Get listing of all documents from the database.
        Used for document_listing queries. The user question tailors the response.
        """
        try:
            all_docs = await self.get_all_indexed_docs()
            if not all_docs:
                return QueryResult(
                    message="No documents are currently indexed.",
                    sources=[],
                    response_time=0.0,
                    query_type="document_listing",
                    retrieval_count=0,
                    rerank_count=0,
                )

            corpus_summary_text = summarize_corpus(all_docs)

            sources = []
            context_parts = []
            listing_context_max = self.llm_service.get_max_listing_context_chars()
            per_doc_max = max(80, listing_context_max // len(all_docs)) if all_docs else 500
            for doc in all_docs:
                filename = Path(doc.file_path).name
                if doc.processing_status == "metadata_only":
                    preview = f"[Indexing in progress...] {filename}"
                else:
                    preview = doc.content_preview if doc.content_preview else ""
                    if not preview and doc.chunks_count > 0:
                        preview = f"[File indexed with {doc.chunks_count} chunk(s)]"
                    if len(preview) > per_doc_max:
                        preview = preview[:per_doc_max].rstrip() + "..."
                context_parts.append(f"[Document: {filename}]\n{preview}")
                sources.append(
                    {
                        "file_path": doc.file_path,
                        "relevance_score": 1.0,
                        "content_snippet": preview[:300] + "..." if len(preview) > 300 else preview,
                        "chunks_found": doc.chunks_count,
                        "file_type": doc.file_type,
                        "processing_status": doc.processing_status,
                    }
                )

            context = CONTEXT_CHUNK_SEP.join(context_parts)
            user_question_line = (
                f'The user asked: "{question.strip()}"\n\n'
                if question and question.strip()
                else ""
            )
            response_prompt = (
                f"You are a document assistant. {user_question_line}Folder overview:\n"
                f"{corpus_summary_text}\n\nDocuments in this folder:\n\n{context}\n\n"
                "Tailor your response precisely to what the user asked:\n"
                "- If they asked how many of a specific category/type (e.g. 'how many delivery "
                "receipts', 'count invoices'): identify EVERY document in the list above that "
                "matches that category by reading its filename AND content preview, enumerate them "
                "with their filenames, and state the exact count. Do NOT give a general summary.\n"
                "- If they asked what kind or type of files exist: give a short summary by file "
                "format and document category (e.g. 'PDFs, spreadsheets, Word docs: invoices, "
                "permits, reports…') — do NOT list every filename.\n"
                "- If they asked to list, show, or tell about all documents: list each document "
                "with filename, brief description, file type, and status.\n"
                "Be precise and consistent. Never say 'the context does not contain' — the full "
                "document list is provided above; always derive your answer from it."
            )

            response_text = await self.llm_service.generate_simple(
                response_prompt, prompt_type="document_listing"
            )

            return QueryResult(
                message=response_text,
                sources=sources,
                response_time=0.0,
                query_type="document_listing",
                retrieval_count=len(all_docs),
                rerank_count=0,
            )

        except Exception as e:
            logger.error(f"Document listing failed: {e}")
            return QueryResult(
                message=f"Sorry, I encountered an error while retrieving the document list: {str(e)}",
                sources=[],
                response_time=0.0,
                query_type="document_listing",
                retrieval_count=0,
                rerank_count=0,
            )

    async def retrieve_and_build_context(
        self,
        question: str,
        query_type: str,
        query_embedding: List[float],
        explicit_filename_override: Optional[str] = None,
        retrieval_params_override: Optional[Dict[str, int]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Shared retrieval + context-building pipeline for document_search queries.
        Returns dict with context, sources, retrieval_count, rerank_count — or None if no results.
        """
        explicit_filename = (
            explicit_filename_override
            if explicit_filename_override is not None
            else self._find_explicit_filename(question)
        )
        selected_files = await self._select_relevant_files(question)
        is_aggregation = is_aggregation_query(question)
        if is_aggregation:
            logger.info("Aggregation-style query detected: using higher recall and per-doc cap")

        documents, metadatas, scores, retrieval_count, rerank_count = await self._retrieve_chunks(
            question,
            query_type,
            explicit_filename,
            query_embedding=query_embedding,
            is_aggregation=is_aggregation,
            retrieval_params_override=retrieval_params_override,
        )
        if not documents:
            return None

        if selected_files:
            prioritized_docs, prioritized_metas, prioritized_scores = [], [], []
            other_docs, other_metas, other_scores = [], [], []
            for doc, meta, score in zip(documents, metadatas, scores):
                fp = meta.get("file_path", "")
                if any(sf in fp for sf in selected_files):
                    prioritized_docs.append(doc)
                    prioritized_metas.append(meta)
                    prioritized_scores.append(score)
                else:
                    other_docs.append(doc)
                    other_metas.append(meta)
                    other_scores.append(score)
            documents = prioritized_docs + other_docs
            metadatas = prioritized_metas + other_metas
            scores = prioritized_scores + other_scores
            logger.info(
                f"Prioritized {len(prioritized_docs)} chunks from {len(selected_files)} selected files"
            )

        # Context compression: gated on CONTEXT_COMPRESSION_ENABLED (default: false).
        total_context_chars = sum(len(d) for d in documents)
        from config import settings
        from ..context_compressor import compress_chunks

        if (
            getattr(settings, "CONTEXT_COMPRESSION_ENABLED", False)
            and not explicit_filename
            and not is_aggregation
            and len(documents) >= 2
            and total_context_chars >= getattr(settings, "CONTEXT_COMPRESSION_MIN_CHARS", 8000)
        ):
            filenames_for_compression = [
                Path(meta.get("file_path", "")).name for meta in metadatas
            ]
            compressed = await compress_chunks(
                question, documents, self.llm_service, filenames=filenames_for_compression
            )
            if len(compressed) == len(documents):
                documents = compressed

        file_chunks: Dict[str, list] = {}
        for doc, metadata, score in zip(documents, metadatas, scores):
            raw_path = metadata.get("file_path", "Unknown")
            fp = os.path.normpath(raw_path) if raw_path else "Unknown"
            file_chunks.setdefault(fp, []).append(
                {
                    "text": doc,
                    "score": score,
                    "chunk_id": metadata.get("chunk_id", 0),
                    "metadata": metadata,
                }
            )

        # Detect single-file intent
        single_file_mode = False
        primary_file_path: Optional[str] = None

        if file_chunks:
            per_file_counts = {fp: len(chunks) for fp, chunks in file_chunks.items()}
            total_chunks = sum(per_file_counts.values())
            primary_file_path, primary_count = max(
                per_file_counts.items(), key=lambda kv: kv[1]
            )

            if len(per_file_counts) == 1:
                single_file_mode = True
            else:
                dominant_ratio = primary_count / max(1, total_chunks)
                if explicit_filename and not is_aggregation and dominant_ratio >= 0.6:
                    single_file_mode = True
                elif not is_aggregation and dominant_ratio >= 0.8 and primary_count >= 3:
                    single_file_mode = True

        sources: List[Dict] = []
        context_parts: List[str] = []

        if single_file_mode and primary_file_path:
            try:
                all_chunks_data = self.vector_store.get_document_chunks(primary_file_path)
            except Exception as e:
                logger.warning(f"Could not load full chunks for {primary_file_path}: {e}")
                all_chunks_data = None

            full_text = ""
            full_chunk_count = 0
            if all_chunks_data and all_chunks_data.get("documents"):
                docs_list = all_chunks_data.get("documents") or []
                metas_list = all_chunks_data.get("metadatas") or [{} for _ in docs_list]
                pairs = list(zip(docs_list, metas_list))
                pairs.sort(key=lambda p: p[1].get("chunk_id", 0))
                full_text = "\n".join(doc for doc, _ in pairs)
                full_chunk_count = len(pairs)
            else:
                chunks = file_chunks.get(primary_file_path, [])
                chunks.sort(key=lambda x: x["chunk_id"])
                full_text = "\n".join(c["text"] for c in chunks)
                full_chunk_count = len(chunks)

            max_per_doc = self.retrieval_config.get_rag_max_per_doc_chars(is_aggregation)
            if max_per_doc > 0 and len(full_text) > max_per_doc:
                full_text_display = full_text[:max_per_doc].rstrip() + "\n[...]"
            else:
                full_text_display = full_text

            filename = Path(primary_file_path).name
            context_parts.append(f"[Document: {filename}]\n{full_text_display}")

            primary_chunks = file_chunks.get(primary_file_path, [])
            if primary_chunks:
                avg_score = sum(c["score"] for c in primary_chunks) / len(primary_chunks)
                sample_meta = primary_chunks[0]["metadata"]
                snippet_source = full_text if full_text else "\n".join(
                    c["text"] for c in primary_chunks
                )
                snippet = snippet_source[:300] + "..." if len(snippet_source) > 300 else snippet_source
                sources.append(
                    {
                        "file_path": primary_file_path,
                        "relevance_score": round(avg_score, 3),
                        "content_snippet": snippet,
                        "chunks_found": full_chunk_count or len(primary_chunks),
                        "file_type": sample_meta.get("file_type", "unknown"),
                    }
                )
            else:
                snippet = full_text[:300] + "..." if len(full_text) > 300 else full_text
                sources.append(
                    {
                        "file_path": primary_file_path,
                        "relevance_score": 1.0,
                        "content_snippet": snippet,
                        "chunks_found": full_chunk_count,
                        "file_type": "unknown",
                    }
                )
        else:
            files_to_process = file_chunks.items()
            if selected_files:
                files_to_process = [
                    (fp, ch)
                    for fp, ch in file_chunks.items()
                    if any(sf in fp for sf in selected_files)
                ]

            max_per_doc = self.retrieval_config.get_rag_max_per_doc_chars(is_aggregation)
            for fp, chunks in files_to_process:
                chunks.sort(key=lambda x: x["chunk_id"])
                filename = Path(fp).name
                file_text = "\n".join(c["text"] for c in chunks)
                if max_per_doc > 0 and len(file_text) > max_per_doc:
                    file_text = file_text[:max_per_doc].rstrip() + "\n[...]"
                context_parts.append(f"[Document: {filename}]\n{file_text}")
                avg_score = sum(c["score"] for c in chunks) / len(chunks)
                snippet = file_text[:300] + "..." if len(file_text) > 300 else file_text
                sources.append(
                    {
                        "file_path": fp,
                        "relevance_score": round(avg_score, 3),
                        "content_snippet": snippet,
                        "chunks_found": len(chunks),
                        "file_type": chunks[0]["metadata"].get("file_type", "unknown"),
                    }
                )

            sources.sort(key=lambda x: x["relevance_score"], reverse=True)
            source_limit = self.retrieval_config.get_source_limit(
                query_type, explicit_filename is not None, is_aggregation
            )
            sources = sources[:source_limit]

        return {
            "context": CONTEXT_CHUNK_SEP.join(context_parts),
            "sources": sources,
            "retrieval_count": retrieval_count,
            "rerank_count": rerank_count,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_explicit_filename(self, question: str) -> Optional[str]:
        """
        Detect explicit document identifiers so we can resolve to a single file.
        Handles: quoted names, full filenames with extension, and stems like BIP-12046.
        """
        quoted = re.findall(r'"([^"]+)"', question)
        if quoted:
            return quoted[0]

        with_ext = re.search(
            r"\b([A-Za-z][A-Za-z0-9_.-]+\.(pdf|docx|txt|xlsx|xls|pptx))\b",
            question,
            re.IGNORECASE,
        )
        if with_ext:
            return with_ext.group(1)

        stem = re.search(r"\b([A-Za-z][A-Za-z0-9_-]{2,})\b", question)
        if stem:
            token = stem.group(1)
            if any(c in token for c in "0123456789-_"):
                return token
        return None

    async def _select_relevant_files(self, question: str) -> Optional[List[str]]:
        """
        Simplified file selection: only use Trie for explicit filenames.
        For all other queries, return None and let retrieval handle relevance.
        """
        try:
            if self.filename_trie.file_count == 0:
                return None

            explicit_filename = self._find_explicit_filename(question)
            if explicit_filename:
                matching_files = self.filename_trie.search(explicit_filename.lower())
                if matching_files:
                    logger.info(
                        f"Found explicit filename '{explicit_filename}': {len(matching_files)} files"
                    )
                    return list(matching_files)

            logger.info("No explicit filename detected, using retrieval for relevance")
            return None

        except Exception as e:
            logger.error(f"File selection failed: {e}, falling back to retrieval")
            return None

    async def _retrieve_chunks(
        self,
        query: str,
        query_type: str,
        explicit_filename: Optional[str] = None,
        query_embedding: Optional[List[float]] = None,
        is_aggregation: bool = False,
        retrieval_params_override: Optional[Dict[str, int]] = None,
    ) -> Tuple[List, List, List, int, int]:
        """
        Single retrieval pipeline: hybrid semantic + keyword search with RRF fusion.
        """
        params = retrieval_params_override or self.retrieval_config.get_retrieval_params(
            query_type, False, is_aggregation
        )
        top_k = params["top_k"]
        final_top_k = params["final_top_k"]
        logger.info(
            f"Retrieval params: top_k={top_k}, final_top_k={final_top_k}"
        )

        if query_embedding is None:
            query_embedding = self.embedding_service.encode_query(query)

        semantic_task = asyncio.create_task(
            self.vector_store.search_similar(query_embedding, top_k)
        )
        bm25_task = asyncio.to_thread(self.bm25_service.search, query, top_k)
        semantic_results, bm25_results = await asyncio.gather(semantic_task, bm25_task)

        if not semantic_results["documents"] or not semantic_results["documents"][0]:
            return ([], [], [], 0, 0)

        text_by_key: Dict[str, str] = {}
        base_score_by_key: Dict[str, float] = {}
        semantic_list = []
        for doc, meta, dist in zip(
            semantic_results["documents"][0],
            semantic_results["metadatas"][0],
            semantic_results["distances"][0],
        ):
            if not doc or not doc.strip():
                continue
            chunk_key = f"{meta.get('file_path', '')}:{meta.get('chunk_id', 0)}"
            base_score = max(0.0, 1.0 - float(dist))
            semantic_list.append((chunk_key, base_score, meta))
            text_by_key[chunk_key] = doc
            base_score_by_key[chunk_key] = base_score

        keyword_list = bm25_results or []
        semantic_count = len(semantic_list)
        keyword_count = len(keyword_list)

        logger.info(
            f"Hybrid RRF: {semantic_count} semantic + {keyword_count} keyword results",
            extra={
                "extra_fields": {
                    "event_type": "retrieval",
                    "semantic_results": semantic_count,
                    "keyword_results": keyword_count,
                }
            },
        )

        fused = self.hybrid_search.fuse_results(semantic_list, keyword_list)

        bm25_only_keys = [cid for cid, _, _ in fused if cid not in text_by_key]
        if bm25_only_keys:
            text_by_key.update(self.bm25_service.get_texts(bm25_only_keys))

        documents = []
        metadatas = []
        scores = []
        for chunk_key, _fused_score, meta in fused:
            text = text_by_key.get(chunk_key)
            if not text:
                continue
            documents.append(text)
            metadatas.append(meta)
            scores.append(base_score_by_key.get(chunk_key, 0.0))

        retrieval_count = len(documents)

        if not documents:
            logger.warning("RRF fusion produced no results, falling back to semantic-only")
            for doc, meta, dist in zip(
                semantic_results["documents"][0],
                semantic_results["metadatas"][0],
                semantic_results["distances"][0],
            ):
                if doc and doc.strip():
                    documents.append(doc)
                    metadatas.append(meta)
                    scores.append(max(0.0, 1.0 - float(dist)))
            retrieval_count = len(documents)

        # Filter by explicit filename
        if explicit_filename:
            filtered_docs, filtered_metas, filtered_scores = [], [], []
            for doc, meta, score in zip(documents, metadatas, scores):
                if explicit_filename.lower() in meta.get("file_path", "").lower():
                    filtered_docs.append(doc)
                    filtered_metas.append(meta)
                    filtered_scores.append(score)
            if filtered_docs:
                documents = filtered_docs
                metadatas = filtered_metas
                scores = filtered_scores
                logger.info(
                    f"Filtered to {len(documents)} chunks from explicit filename '{explicit_filename}'"
                )

        # File-diversity selection (general search only)
        if not explicit_filename and len(documents) > final_top_k:
            max_per_file = getattr(self.retrieval_config, "max_chunks_per_file", 2)
            if max_per_file > 0:
                selected_docs, selected_metas, selected_scores = [], [], []
                file_counts: Dict[str, int] = {}
                for doc, meta, score in zip(documents, metadatas, scores):
                    fp = meta.get("file_path", "")
                    count = file_counts.get(fp, 0)
                    if count < max_per_file:
                        selected_docs.append(doc)
                        selected_metas.append(meta)
                        selected_scores.append(score)
                        file_counts[fp] = count + 1
                    if len(selected_docs) >= final_top_k:
                        break
                documents = selected_docs
                metadatas = selected_metas
                scores = selected_scores
                logger.info(
                    "File-diversity selection: %s chunks from %s files (max %s per file)",
                    len(documents),
                    len(file_counts),
                    max_per_file,
                )

        return (documents, metadatas, scores, retrieval_count, 0)
