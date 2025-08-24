import chromadb
import hashlib
import logging
import os
from typing import Optional, Dict, List, Tuple
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
import asyncio
from sentence_transformers import SentenceTransformer
import httpx

logger = logging.getLogger(__name__)

@dataclass
class DocumentChunk:
    text: str
    chunk_id: int
    total_chunks: int
    file_path: str
    start_pos: int
    end_pos: int

@dataclass 
class QueryResult:
    message: str
    sources: List[Dict]
    response_time: float

class DocumentProcessor:
    def __init__(self, 
                 persist_dir: str = "./chroma_db",
                 embed_model_name: str = "BAAI/bge-small-en-v1.5",
                 max_file_size_mb: int = 50,
                 chunk_size: int = 1000,
                 chunk_overlap: int = 200):
        
        # Initialize ChromaDB with better settings
        self.chroma_client = chromadb.PersistentClient(
            path=persist_dir,
            settings=chromadb.config.Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        self.collection = self.chroma_client.get_or_create_collection(
            name="documents",
            metadata={
                "hnsw:space": "cosine"
            }
        )
        
        # Initialize embedding model
        self.embed_model = SentenceTransformer(embed_model_name)
        
        # Configuration
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.supported_extensions = {".pdf", ".docx", ".txt"}
        
        # State tracking
        self.file_hashes: Dict[str, str] = {}
        self.file_metadata: Dict[str, Dict] = {}
        self.current_directory: Optional[str] = None
        
        # HTTP client for Ollama (reuse connection)
        self.http_client = httpx.AsyncClient(timeout=30.0)
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.http_client.aclose()
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA-256 hash of file content efficiently"""
        try:
            hash_sha256 = hashlib.sha256()
            with open(file_path, "rb") as f:
                # Read in larger chunks for better performance
                for chunk in iter(lambda: f.read(65536), b""):
                    hash_sha256.update(chunk)
            return hash_sha256.hexdigest()
        except Exception as e:
            logger.error(f"Error calculating hash for {file_path}: {e}")
            return ""
    
    def _validate_file(self, file_path: str) -> Tuple[bool, str]:
        """Validate file and return (is_valid, error_message)"""
        try:
            path_obj = Path(file_path)
            
            if not path_obj.exists():
                return False, "File does not exist"
            
            if not path_obj.is_file():
                return False, "Path is not a file"
            
            if path_obj.suffix.lower() not in self.supported_extensions:
                return False, f"Unsupported file type: {path_obj.suffix}"
            
            file_size = path_obj.stat().st_size
            if file_size > self.max_file_size_bytes:
                return False, f"File too large ({file_size / 1024 / 1024:.1f}MB)"
            
            if file_size == 0:
                return False, "File is empty"
            
            if not os.access(file_path, os.R_OK):
                return False, "File not readable"
            
            return True, ""
            
        except Exception as e:
            return False, f"Validation error: {e}"
    
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
            
            # Clear existing data
            await self._clear_collection()
            self.file_hashes.clear()
            self.file_metadata.clear()
            
            # Find all supported files
            supported_files = []
            for file_path in dir_path.rglob("*"):
                if file_path.is_file():
                    is_valid, error = self._validate_file(str(file_path))
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
    
    async def _process_single_file(self, file_path: str):
        """Process a single file (used in batch processing)"""
        try:
            await self.add_document(file_path)
        except Exception as e:
            logger.error(f"Failed to process {file_path}: {e}")
            raise
    
    async def add_document(self, file_path: str):
        """Add or update a document"""
        try:
            is_valid, error = self._validate_file(file_path)
            if not is_valid:
                logger.warning(f"Skipping invalid file {file_path}: {error}")
                return
            
            # Check if file actually changed
            current_hash = self._calculate_file_hash(file_path)
            if not current_hash:
                logger.error(f"Could not calculate hash for {file_path}")
                return
            
            if (file_path in self.file_hashes and 
                self.file_hashes[file_path] == current_hash):
                logger.debug(f"File unchanged, skipping: {file_path}")
                return
            
            # Remove existing chunks first
            await self._remove_document_chunks(file_path)
            
            # Extract text
            text = await self._extract_text_async(file_path)
            if not text or not text.strip():
                logger.warning(f"No text extracted from {file_path}")
                return
            
            # Create chunks
            chunks = self._create_chunks(text, file_path)
            if not chunks:
                logger.warning(f"No chunks created for {file_path}")
                return
            
            logger.info(f"Processing {len(chunks)} chunks for {file_path}")
            
            # Batch process chunks
            await self._batch_insert_chunks(chunks)
            
            # Update tracking
            self.file_hashes[file_path] = current_hash
            self.file_metadata[file_path] = {
                "size": Path(file_path).stat().st_size,
                "modified": datetime.now().isoformat(),
                "chunks": len(chunks)
            }
            
            logger.info(f"Successfully processed {file_path} ({len(chunks)} chunks)")
            
        except Exception as e:
            logger.error(f"Error processing document {file_path}: {e}")
            raise
    
    async def _extract_text_async(self, file_path: str) -> str:
        """Extract text asynchronously to avoid blocking"""
        def sync_extract():
            return self._extract_text_sync(file_path)
        
        # Run in thread pool for CPU-intensive operations
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, sync_extract)
    
    def _extract_text_sync(self, file_path: str) -> str:
        """Synchronous text extraction with better error handling"""
        path_obj = Path(file_path)
        ext = path_obj.suffix.lower()
        
        try:
            if ext == ".pdf":
                return self._extract_pdf(file_path)
            elif ext == ".docx":
                return self._extract_docx(file_path)
            elif ext == ".txt":
                return self._extract_txt(file_path)
            else:
                raise ValueError(f"Unsupported file type: {ext}")
        except Exception as e:
            logger.error(f"Text extraction failed for {file_path}: {e}")
            raise
    
    def _create_chunks(self, text: str, file_path: str) -> List[DocumentChunk]:
        """Create semantic chunks with better boundary detection"""
        if len(text) <= self.chunk_size:
            return [DocumentChunk(
                text=text,
                chunk_id=0,
                total_chunks=1,
                file_path=file_path,
                start_pos=0,
                end_pos=len(text)
            )]
        
        chunks = []
        start = 0
        chunk_id = 0
        
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            
            # Find semantic boundary
            if end < len(text):
                end = self._find_chunk_boundary(text, start, end)
            
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(DocumentChunk(
                    text=chunk_text,
                    chunk_id=chunk_id,
                    total_chunks=0,  # Will be updated later
                    file_path=file_path,
                    start_pos=start,
                    end_pos=end
                ))
                chunk_id += 1
            
            # Next start with overlap
            start = max(start + 1, end - self.chunk_overlap)
            if start >= len(text):
                break
        
        # Update total_chunks
        for chunk in chunks:
            chunk.total_chunks = len(chunks)
        
        return chunks
    
    def _find_chunk_boundary(self, text: str, start: int, end: int) -> int:
        """Find optimal chunk boundary"""
        # Look for sentence endings
        for i in range(end - 1, max(start + self.chunk_size - 100, start), -1):
            if text[i] in '.!?':
                # Check if it's not an abbreviation
                if i + 1 < len(text) and text[i + 1].isspace():
                    return i + 1
        
        # Look for paragraph breaks
        for i in range(end - 1, max(start + self.chunk_size - 50, start), -1):
            if text[i] == '\n' and (i + 1 >= len(text) or text[i + 1] == '\n'):
                return i + 1
        
        # Look for any whitespace
        for i in range(end - 1, max(start + self.chunk_size - 20, start), -1):
            if text[i].isspace():
                return i + 1
        
        return end
    
    async def _batch_insert_chunks(self, chunks: List[DocumentChunk]):
        """Batch insert chunks efficiently"""
        if not chunks:
            return
        
        # Prepare batch data
        ids = []
        embeddings = []
        documents = []
        metadatas = []
        
        # Generate embeddings in batch for efficiency
        texts = [chunk.text for chunk in chunks]
        batch_embeddings = self.embed_model.encode(texts).tolist()
        
        for chunk, embedding in zip(chunks, batch_embeddings):
            chunk_id = f"{chunk.file_path}_chunk_{chunk.chunk_id}"
            
            metadata = {
                "file_path": chunk.file_path,
                "file_type": Path(chunk.file_path).suffix.lower(),
                "chunk_id": chunk.chunk_id,
                "total_chunks": chunk.total_chunks,
                "start_pos": chunk.start_pos,
                "end_pos": chunk.end_pos,
                "processed_at": datetime.now().isoformat(),
                "text_length": len(chunk.text)
            }
            
            ids.append(chunk_id)
            embeddings.append(embedding)
            documents.append(chunk.text)
            metadatas.append(metadata)
        
        # Batch upsert
        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )
    
    async def _clear_collection(self):
        """Clear all documents from collection"""
        try:
            all_results = self.collection.get()
            if all_results['ids']:
                self.collection.delete(ids=all_results['ids'])
                logger.info(f"Cleared {len(all_results['ids'])} existing documents")
        except Exception as e:
            logger.warning(f"Error clearing collection: {e}")
    
    async def remove_document(self, file_path: str):
        """Remove document and clean up tracking"""
        try:
            await self._remove_document_chunks(file_path)
            
            # Clean up tracking
            self.file_hashes.pop(file_path, None)
            self.file_metadata.pop(file_path, None)
            
            logger.info(f"Removed document: {file_path}")
            
        except Exception as e:
            logger.error(f"Error removing document {file_path}: {e}")
    
    async def _remove_document_chunks(self, file_path: str):
        """Remove all chunks for a document"""
        try:
            results = self.collection.get(where={"file_path": file_path})
            if results['ids']:
                self.collection.delete(ids=results['ids'])
                logger.debug(f"Removed {len(results['ids'])} chunks for {file_path}")
        except Exception as e:
            logger.error(f"Error removing chunks for {file_path}: {e}")
    
    # Text extraction methods remain the same...
    def _extract_pdf(self, file_path: str) -> str:
        """Extract text from PDF"""
        try:
            import fitz
            doc = fitz.open(file_path)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            return text
        except Exception as e:
            logger.error(f"PDF extraction failed for {file_path}: {e}")
            raise
    
    def _extract_docx(self, file_path: str) -> str:
        """Extract text from DOCX"""
        try:
            import docx
            doc = docx.Document(file_path)
            return "\n".join([para.text for para in doc.paragraphs])
        except Exception as e:
            logger.error(f"DOCX extraction failed for {file_path}: {e}")
            raise
    
    def _extract_txt(self, file_path: str) -> str:
        """Extract text from TXT with encoding detection"""
        try:
            encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
            for encoding in encodings:
                try:
                    with open(file_path, "r", encoding=encoding) as f:
                        return f.read()
                except UnicodeDecodeError:
                    continue
            
            # Fallback with error handling
            with open(file_path, "r", encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception as e:
            logger.error(f"TXT extraction failed for {file_path}: {e}")
            raise
    
    
    async def query(self, question: str, max_results: int = 5) -> QueryResult:
        """Query the document index with LLM integration"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Generate query embedding
            query_embedding = self.embed_model.encode(question).tolist()
            
            # Search ChromaDB with embedding
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=max_results,
                include=['documents', 'metadatas', 'distances']
            )
            
            if not results['documents'] or not results['documents'][0]:
                return QueryResult(
                    message="I don't have information about that in the current documents.",
                    sources=[],
                    response_time=asyncio.get_event_loop().time() - start_time
                )
            
            # Process results
            documents = results['documents'][0]
            metadatas = results['metadatas'][0] 
            distances = results['distances'][0]
            
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
            
            # Create sources and context
            sources = []
            context_parts = []
            
            for file_path, chunks in file_chunks.items():
                # Sort chunks by chunk_id for proper order
                chunks.sort(key=lambda x: x["chunk_id"])
                
                # Combine chunks for this file
                file_text = "\n".join([chunk["text"] for chunk in chunks])
                context_parts.append(file_text)
                
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
            
            # Generate response using LLM
            context = "\n\n---\n\n".join(context_parts)
            response_text = await self._generate_llm_response(question, context)
            
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


    async def _generate_llm_response(self, query: str, context: str) -> str:
        """Generate response using Ollama LLM"""
        try:
            # Import settings here to avoid circular imports
            from config import settings
            
            prompt = f"""You are a helpful AI assistant that answers questions based on the provided document context.

    Context information:
    {context}

    Question: {query}

    Instructions:
    - Answer the question directly and clearly based on the provided context
    - If the information is not in the context, say "I don't have information about that in the current documents"
    - Be concise but comprehensive
    - Use specific details from the context when relevant
    - If you're uncertain, acknowledge it

    Answer:"""

            response = await self.http_client.post(
                f"{settings.OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": settings.OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "max_tokens": 1000
                    }
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "I couldn't generate a response.")
            else:
                logger.error(f"Ollama API error: {response.status_code} - {response.text}")
                return "I couldn't generate a response due to an API error."
                
        except Exception as e:
            logger.error(f"Error generating LLM response: {e}")
            return "I couldn't generate a response due to an error."
        
    def get_stats(self) -> Dict:
        """Get comprehensive stats"""
        try:
            collection_count = self.collection.count()
            return {
                "total_files": len(self.file_hashes),
                "total_chunks": collection_count,
                "current_directory": self.current_directory,
                "indexed_files": list(self.file_hashes.keys()),
                "file_metadata": self.file_metadata,
                "avg_chunks_per_file": (
                    collection_count / len(self.file_hashes) 
                    if self.file_hashes else 0
                )
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {"error": str(e)}


    async def cleanup(self):
        """Proper cleanup method"""
        try:
            if hasattr(self, 'http_client') and self.http_client:
                await self.http_client.aclose()
            
            # Clear in-memory data
            self.file_hashes.clear()
            self.file_metadata.clear()
            
            logger.info("DocumentProcessor cleaned up successfully")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")