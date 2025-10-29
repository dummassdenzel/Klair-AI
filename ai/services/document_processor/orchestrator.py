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
from database import DatabaseService


logger = logging.getLogger(__name__)


class DocumentProcessorOrchestrator:
    """Main orchestrator that coordinates all document processing services"""
    
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
                 llm_provider: str = "ollama"):
        
        # Initialize all services
        self.text_extractor = TextExtractor()
        self.chunker = DocumentChunker(chunk_size, chunk_overlap)
        self.embedding_service = EmbeddingService(embed_model_name)
        self.vector_store = VectorStoreService(persist_dir)
        # LLM service now supports provider switch (ollama | gemini)
        self.llm_service = LLMService(
            ollama_base_url=ollama_base_url,
            ollama_model=ollama_model,
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
            provider=llm_provider
        )
        self.file_validator = FileValidator(max_file_size_mb)
        self.database_service = DatabaseService()
        
        # State tracking
        self.file_hashes: Dict[str, str] = {}
        self.file_metadata: Dict[str, FileMetadata] = {}
        self.current_directory: Optional[str] = None
        
        logger.info("DocumentProcessorOrchestrator initialized successfully")
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()
    
    async def clear_all_data(self):
        """Clear all indexed data (vector store and database records)"""
        logger.info("Clearing all indexed data...")
        
        # Clear vector store
        await self.vector_store.clear_collection()
        self.file_hashes.clear()
        self.file_metadata.clear()
        logger.info("Vector store cleared")
        
        # Clear database records
        try:
            from database.database import get_db
            from database.models import IndexedDocument
            from sqlalchemy import delete
            
            async for session in get_db():
                stmt = delete(IndexedDocument)
                await session.execute(stmt)
                await session.commit()
                logger.info("Database document index records cleared")
                break
        except Exception as e:
            logger.warning(f"Failed to clear database records: {e}")
    
    async def initialize_from_directory(self, directory_path: str):
        """Initialize processor with documents from directory"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            dir_path = Path(directory_path)
            if not dir_path.exists():
                raise ValueError(f"Directory does not exist: {directory_path}")
            
            if not dir_path.is_dir():
                raise ValueError(f"Path is not a directory: {directory_path}")
            
            logger.info(f"Initializing from directory: {directory_path}")
            self.current_directory = directory_path
            
            # Find all supported files
            supported_files = []
            for file_path in dir_path.rglob("*"):
                if file_path.is_file():
                    is_valid, error = self.file_validator.validate_file(str(file_path))
                    if is_valid:
                        supported_files.append(str(file_path))
                    elif error and "Unsupported file type" not in error:
                        logger.warning(f"Skipping {file_path}: {error}")
            
            if not supported_files:
                logger.warning(f"No supported files found in {directory_path}")
                return
            
            logger.info(f"Found {len(supported_files)} files to process")
            
            # Process files in batches for better memory management
            batch_size = 10
            processed = 0
            failed = 0
            
            for i in range(0, len(supported_files), batch_size):
                batch = supported_files[i:i + batch_size]
                
                # Process batch concurrently
                tasks = [self._process_single_file(file_path) for file_path in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Count results
                for result in results:
                    if isinstance(result, Exception):
                        failed += 1
                    else:
                        processed += 1
                
                logger.info(f"Processed {processed + failed}/{len(supported_files)} files")
            
            elapsed = asyncio.get_event_loop().time() - start_time
            logger.info(f"Initialization complete: {processed} files processed, "
                       f"{failed} failed in {elapsed:.2f}s")
                
        except Exception as e:
            logger.error(f"Failed to initialize from directory: {e}")
            raise
    
    async def _process_single_file(self, file_path: str) -> ProcessingResult:
        """Process a single file (used in batch processing)"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            await self.add_document(file_path)
            processing_time = asyncio.get_event_loop().time() - start_time
            
            return ProcessingResult(
                success=True,
                file_path=file_path,
                chunks_created=0,
                processing_time=processing_time
            )
            
        except Exception as e:
            processing_time = asyncio.get_event_loop().time() - start_time
            logger.error(f"Failed to process {file_path}: {e}")
            
            return ProcessingResult(
                success=False,
                file_path=file_path,
                chunks_created=0,
                error_message=str(e),
                processing_time=processing_time
            )
    
    async def add_document(self, file_path: str):
        """Add or update a document"""
        try:
            # Get real file metadata
            file_metadata = self.file_validator.extract_file_metadata(file_path)
            current_hash = self.file_validator.calculate_file_hash(file_path)
            
            # Process document...
            text = await self.text_extractor.extract_text_async(file_path)
            if not text or not text.strip():
                logger.warning(f"No text extracted from {file_path}")
                return
            
            chunks = self.chunker.create_chunks(text, file_path)
            embeddings = self.embedding_service.encode_texts([chunk.text for chunk in chunks])
            await self.vector_store.batch_insert_chunks(chunks, embeddings)
            
            # Store complete metadata in database
            await self.database_service.store_document_metadata(
                file_path=file_path,
                file_hash=current_hash,
                file_type=file_metadata["file_type"],
                file_size=file_metadata["size_bytes"],
                last_modified=file_metadata["modified_at"],
                content_preview=text[:500],
                chunks_count=len(chunks)
            )
            
            # Update tracking
            self.file_hashes[file_path] = current_hash
            self.file_metadata[file_path] = file_metadata
            
        except Exception as e:
            logger.error(f"Error processing document {file_path}: {e}")
            raise
    
    async def remove_document(self, file_path: str):
        """Remove document and clean up tracking"""
        try:
            await self.vector_store.remove_document_chunks(file_path)
            
            # Clean up tracking
            self.file_hashes.pop(file_path, None)
            self.file_metadata.pop(file_path, None)
            
            logger.info(f"Removed document: {file_path}")
            
        except Exception as e:
            logger.error(f"Error removing document {file_path}: {e}")
    
    async def _select_relevant_files(self, question: str) -> Optional[List[str]]:
        """
        Use LLM to intelligently select which files are relevant to the query.
        Returns None if all files should be considered (general query).
        Returns list of file paths if specific files are relevant.
        """
        try:
            # Get all indexed files with their metadata
            if not self.file_metadata:
                logger.info("No files indexed, skipping file selection")
                return None
            
            # Build file list for LLM
            file_list = []
            for idx, (file_path, metadata) in enumerate(self.file_metadata.items(), 1):
                filename = Path(file_path).name
                file_type = metadata.get("file_type", "unknown")
                file_list.append(f"{idx}. {filename} (type: {file_type})")
            
            file_list_str = "\n".join(file_list)
            
            # Create selection prompt
            selection_prompt = f"""You are a file selection AI. Your ONLY job is to pick which files are needed to answer a question.

AVAILABLE FILES:
{file_list_str}

USER QUESTION: "{question}"

INSTRUCTIONS:
• If the question needs ALL files (e.g., "summarize everything", "list all documents"), respond: ALL_FILES
• If the question needs SPECIFIC files, respond with ONLY their numbers separated by commas

EXAMPLES:
• "What's in REQUEST LETTER?" → Find file with "REQUEST LETTER" in name → Return: 5
• "How many TCO documents?" → Find files starting with "TCO" → Return: 1,2,7,9
• "Files NOT delivery receipts" → Find files that are NOT receipts → Return: 3,5,8,10,11
• "Summarize all documents" → Return: ALL_FILES

CRITICAL RULES:
1. Look at filenames carefully
2. For "NOT X" queries, EXCLUDE X files
3. For pattern queries (e.g., "TCO"), match filename patterns
4. Only return numbers or "ALL_FILES"
5. NO explanations, NO other text

YOUR RESPONSE (ONLY numbers or "ALL_FILES"):"""

            # Get LLM selection (use simple method without templating)
            response = await self.llm_service.generate_simple(selection_prompt)
            
            response = response.strip()
            logger.info(f"🤖 LLM file selection response: {response}")
            
            # Handle error responses from LLM
            if "couldn't generate" in response.lower() or "error" in response.lower():
                logger.warning(f"LLM selection failed, falling back to ALL files")
                return None
            
            # Parse response
            if "ALL_FILES" in response.upper() or response.upper() == "ALL":
                logger.info("📋 LLM decided: ALL files are relevant (general query)")
                return None
            
            # Parse file numbers - be more flexible with parsing
            try:
                # Remove any text, keep only numbers and commas
                # Handle responses like "1,3,5,7" or "1, 3, 5, 7" or even "Files: 1,3,5"
                cleaned = ''.join(c for c in response if c.isdigit() or c == ',')
                if not cleaned:
                    logger.warning(f"No numbers found in LLM response: '{response}'")
                    return None
                
                file_numbers = [int(num.strip()) for num in cleaned.split(",") if num.strip()]
                file_paths_list = list(self.file_metadata.keys())
                
                selected_files = []
                for num in file_numbers:
                    if 1 <= num <= len(file_paths_list):
                        selected_files.append(file_paths_list[num - 1])
                    else:
                        logger.warning(f"File number {num} out of range (1-{len(file_paths_list)})")
                
                if selected_files:
                    selected_names = [Path(f).name for f in selected_files]
                    logger.info(f"🎯 LLM selected {len(selected_files)} specific files: {selected_names}")
                    return selected_files
                else:
                    logger.warning(f"LLM returned invalid file numbers: {response}")
                    return None
                    
            except ValueError as e:
                logger.warning(f"Failed to parse LLM response '{response}': {e}")
                return None
                
        except Exception as e:
            logger.error(f"File selection failed: {e}, falling back to all files")
            return None
    
    async def _classify_query(self, question: str) -> str:
        """
        Classify the query to determine if document retrieval is needed.
        Returns: 'greeting', 'general', or 'document'
        """
        try:
            classification_prompt = f"""You are a query classification AI. Classify the user's query into ONE of these categories:

USER QUERY: "{question}"

CATEGORIES:
1. greeting - Simple greetings, pleasantries, or introductions
   Examples: "hello", "hi", "how are you?", "good morning", "thanks", "goodbye"
   
2. general - General questions NOT about documents, or questions about the AI itself
   Examples: "what can you do?", "how does this work?", "who made you?", "what's the weather?"
   
3. document - Questions that need document retrieval to answer
   Examples: "what's in the sales report?", "how many TCO documents?", "summarize the meeting notes"

INSTRUCTIONS:
- Respond with ONLY ONE WORD: "greeting", "general", or "document"
- If the query mentions files, documents, or specific information that would be in documents, return "document"
- If the query is casual conversation or about the system itself, return "greeting" or "general"
- NO explanations, NO other text

YOUR CLASSIFICATION (ONE WORD):"""

            response = await self.llm_service.generate_simple(classification_prompt)
            classification = response.strip().lower()
            
            # Validate response
            if classification in ['greeting', 'general', 'document']:
                logger.info(f"🔍 Query classified as: {classification.upper()}")
                return classification
            else:
                # If LLM returns something unexpected, default to 'document' (safe fallback)
                logger.warning(f"Unexpected classification '{response}', defaulting to 'document'")
                return 'document'
                
        except Exception as e:
            logger.error(f"Query classification failed: {e}, defaulting to 'document'")
            return 'document'
    
    async def _generate_direct_response(self, question: str, response_type: str) -> str:
        """
        Generate a direct response without document retrieval.
        Used for greetings and general queries.
        """
        try:
            if response_type == 'greeting':
                prompt = f"""You are a friendly AI assistant for a document management system.

User said: "{question}"

Respond warmly and briefly (1-2 sentences). Let them know you can help with documents.

Your response:"""
            else:  # general
                prompt = f"""You are an AI assistant for a document management system.

User asked: "{question}"

Answer their question. Your capabilities:
- Search and analyze indexed documents
- Answer questions about specific files
- List and compare documents
- Find information across multiple files

Keep your response concise and helpful (2-3 sentences).

Your response:"""

            # Use generate_simple for direct responses (not the Q&A method)
            response = await self.llm_service.generate_simple(prompt)
            
            return response
            
        except Exception as e:
            logger.error(f"Direct response generation failed: {e}")
            return "Hello! I'm your document assistant. I can help you search and analyze your indexed documents. What would you like to know?"
    
    async def query(self, question: str, max_results: int = 15) -> QueryResult:
        """Query the document index with agentic LLM-based classification and file selection"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Step 0: Classify query to determine if document retrieval is needed
            query_type = await self._classify_query(question)
            
            # Handle non-document queries directly (fast path)
            if query_type in ['greeting', 'general']:
                response_text = await self._generate_direct_response(question, query_type)
                response_time = asyncio.get_event_loop().time() - start_time
                
                logger.info(f"⚡ Fast response (no retrieval): {response_time:.2f}s")
                
                return QueryResult(
                    message=response_text,
                    sources=[],  # No document sources for greetings/general
                    response_time=round(response_time, 3)
                )
            
            # Document query - proceed with RAG pipeline
            logger.info(f"📚 Document query detected, starting RAG pipeline...")
            
            # Step 1: Use LLM to intelligently select relevant files
            selected_files = await self._select_relevant_files(question)
            
            # Step 2: Adjust retrieval parameters based on file selection
            if selected_files is not None:
                # Specific files selected - retrieve more chunks to ensure good coverage
                adjusted_max_results = min(max_results * 2, 30)
            else:
                # General query - retrieve chunks from all files
                adjusted_max_results = min(max_results * 4, 60)
            
            # Step 3: Generate query embedding and search vector store
            query_embedding = self.embedding_service.encode_single_text(question)
            results = await self.vector_store.search_similar(query_embedding, adjusted_max_results)
            
            if not results['documents'] or not results['documents'][0]:
                return QueryResult(
                    message="I don't have information about that in the current documents.",
                    sources=[],
                    response_time=asyncio.get_event_loop().time() - start_time
                )
            
            # Step 4: Process results and prioritize selected files
            documents = results['documents'][0]
            metadatas = results['metadatas'][0] 
            distances = results['distances'][0]
            
            # If LLM selected specific files, prioritize their chunks
            if selected_files:
                prioritized_docs = []
                prioritized_metas = []
                prioritized_dists = []
                other_docs = []
                other_metas = []
                other_dists = []
                
                for doc, meta, dist in zip(documents, metadatas, distances):
                    file_path = meta.get("file_path", "")
                    if any(sf in file_path for sf in selected_files):
                        prioritized_docs.append(doc)
                        prioritized_metas.append(meta)
                        prioritized_dists.append(dist)
                    else:
                        other_docs.append(doc)
                        other_metas.append(meta)
                        other_dists.append(dist)
                
                # Reconstruct with prioritized first
                documents = prioritized_docs + other_docs
                metadatas = prioritized_metas + other_metas
                distances = prioritized_dists + other_dists
                
                logger.info(f"✅ Prioritized {len(prioritized_docs)} chunks from {len(selected_files)} LLM-selected files")
            
            # Group chunks by file for better context
            file_chunks = {}
            for doc, metadata, distance in zip(documents, metadatas, distances):
                file_path = metadata.get("file_path", "Unknown")
                if file_path not in file_chunks:
                    file_chunks[file_path] = []
                file_chunks[file_path].append({
                    "text": doc,
                    "distance": distance,
                    "chunk_id": metadata.get("chunk_id", 0),
                    "metadata": metadata
                })
            
            # Step 5: Create sources and context from selected files
            sources = []
            context_parts = []
            
            # Filter files based on LLM selection
            files_to_process = file_chunks.items()
            if selected_files:
                # Only include LLM-selected files - NO additional context files for specific queries
                selected_file_chunks = {fp: chunks for fp, chunks in file_chunks.items() if any(sf in fp for sf in selected_files)}
                
                files_to_process = list(selected_file_chunks.items())
                logger.info(f"🎯 Focusing exclusively on {len(selected_file_chunks)} LLM-selected file(s)")
            
            for file_path, chunks in files_to_process:
                # Sort chunks by chunk_id for proper order
                chunks.sort(key=lambda x: x["chunk_id"])
                
                # Get just the filename for better readability
                filename = Path(file_path).name
                
                # Combine chunks for this file WITH filename header
                file_text = "\n".join([chunk["text"] for chunk in chunks])
                # Format: [Filename: xyz.pdf]\nContent...
                context_with_filename = f"[Document: {filename}]\n{file_text}"
                context_parts.append(context_with_filename)
                
                # Calculate average relevance (lower distance = higher relevance)
                avg_distance = sum(chunk["distance"] for chunk in chunks) / len(chunks)
                relevance_score = max(0, 1.0 - avg_distance)  # Convert to 0-1 score
                
                sources.append({
                    "file_path": file_path,
                    "relevance_score": round(relevance_score, 3),
                    "content_snippet": file_text[:300] + "..." if len(file_text) > 300 else file_text,
                    "chunks_found": len(chunks),
                    "file_type": chunks[0]["metadata"].get("file_type", "unknown")
                })
            
            # Sort sources by relevance
            sources.sort(key=lambda x: x["relevance_score"], reverse=True)
            
            # Step 6: Smart source limiting
            if selected_files is None:
                # General query - limit to top 10 most relevant sources
                logger.info(f"📊 General query: limiting to top 10 of {len(sources)} sources")
                sources = sources[:10]
            else:
                # Specific files query - show only LLM-selected files (no arbitrary limit)
                logger.info(f"📊 Specific query: showing {len(sources)} LLM-selected file sources")
            
            # Step 7: Generate final response using LLM with document context
            context = "\n\n---\n\n".join(context_parts)
            response_text = await self.llm_service.generate_response(question, context)
            
            response_time = asyncio.get_event_loop().time() - start_time
            
            return QueryResult(
                message=response_text,
                sources=sources,
                response_time=round(response_time, 3)
            )
            
        except Exception as e:
            logger.error(f"Query failed: {e}")
            response_time = asyncio.get_event_loop().time() - start_time
            return QueryResult(
                message=f"Sorry, I encountered an error while processing your query: {str(e)}",
                sources=[],
                response_time=round(response_time, 3)
            )
    
    def get_stats(self) -> Dict:
        """Get comprehensive stats"""
        try:
            collection_count = self.vector_store.get_collection_count()
            # file_metadata entries are dicts already; avoid __dict__ access
            return {
                "total_files": len(self.file_hashes),
                "total_chunks": collection_count,
                "current_directory": self.current_directory,
                "indexed_files": list(self.file_hashes.keys()),
                "file_metadata": {k: v for k, v in self.file_metadata.items()},
                "avg_chunks_per_file": (
                    collection_count / len(self.file_hashes)
                    if self.file_hashes else 0
                ),
                "embedding_model": self.embedding_service.model_name,
                "chunk_size": self.chunker.chunk_size,
                "chunk_overlap": self.chunker.chunk_overlap
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {"error": str(e)}
    
    async def cleanup(self):
        """Proper cleanup method"""
        try:
            # Cleanup all services
            await self.llm_service.cleanup()
            self.vector_store.cleanup()
            self.embedding_service.cleanup()
            
            # Clear in-memory data
            self.file_hashes.clear()
            self.file_metadata.clear()
            
            logger.info("DocumentProcessorOrchestrator cleaned up successfully")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
    async def clear_collection(self):
        """Clear all documents from the vector store and reset tracking"""
        try:
            # Clear vector store
            await self.vector_store.clear_collection()
            
            # Clear in-memory tracking
            self.file_hashes.clear()
            self.file_metadata.clear()
            
            logger.info("Document collection cleared successfully")
        except Exception as e:
            logger.error(f"Error clearing collection: {e}")
            raise
    
    def is_ready(self) -> bool:
        """Check if the orchestrator is ready (basic services initialized)"""
        try:
            # Check if basic services are available
            return (
                self.text_extractor is not None and
                self.chunker is not None and
                self.file_validator is not None
            )
        except Exception:
            return False
