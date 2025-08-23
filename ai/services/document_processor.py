import chromadb
import os
import hashlib
import logging
from typing import Optional, Dict, List
from datetime import datetime
from config import settings
from sentence_transformers import SentenceTransformer
import asyncio

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DocumentProcessor:
    def __init__(self, persist_dir: str = "./chroma_db"):
        # Initialize ChromaDB
        self.chroma_client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.chroma_client.get_or_create_collection(
            name="documents",
            metadata={"hnsw:space": "cosine"}
        )
        
        # Initialize embedding model
        self.embed_model = SentenceTransformer("BAAI/bge-small-en-v1.5")
        
        # Track file hashes to detect actual changes
        self.file_hashes: Dict[str, str] = {}
        self.supported_extensions = {".pdf", ".docx", ".txt"}
        self.current_directory: Optional[str] = None
        
        # File processing limits
        self.max_file_size_mb = getattr(settings, 'MAX_FILE_SIZE_MB', 50)
        self.max_file_size_bytes = self.max_file_size_mb * 1024 * 1024
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA-256 hash of file content"""
        try:
            hash_sha256 = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
            return hash_sha256.hexdigest()
        except Exception as e:
            logger.error(f"Error calculating hash for {file_path}: {e}")
            return ""
    
    def _validate_file(self, file_path: str) -> bool:
        """Validate file before processing"""
        try:
            if not os.path.exists(file_path):
                logger.warning(f"File does not exist: {file_path}")
                return False
            
            ext = os.path.splitext(file_path)[1].lower()
            if ext not in self.supported_extensions:
                logger.warning(f"Unsupported file type: {ext} for {file_path}")
                return False
            
            file_size = os.path.getsize(file_path)
            if file_size > self.max_file_size_bytes:
                logger.warning(f"File too large ({file_size / 1024 / 1024:.1f}MB): {file_path}")
                return False
            
            if not os.access(file_path, os.R_OK):
                logger.warning(f"File not readable: {file_path}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating file {file_path}: {e}")
            return False
    
    async def initialize_from_directory(self, directory_path: str):
        """Load all documents from directory"""
        try:
            logger.info(f"Initializing document processor for directory: {directory_path}")
            
            if not os.path.exists(directory_path):
                raise ValueError(f"Directory does not exist: {directory_path}")
            
            self.current_directory = directory_path
            
            # Clear existing collection - Fix the delete operation
            try:
                # Get all existing documents first
                all_results = self.collection.get()
                if all_results['ids']:
                    # Delete by IDs instead of empty where clause
                    self.collection.delete(ids=all_results['ids'])
                    logger.info(f"Cleared {len(all_results['ids'])} existing documents")
            except Exception as e:
                logger.warning(f"Error clearing collection: {e}")
            
            self.file_hashes.clear()
            
            # Get all supported files
            supported_files = []
            for root, dirs, files in os.walk(directory_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    if self._validate_file(file_path):
                        supported_files.append(file_path)
            
            if not supported_files:
                logger.warning(f"No supported files found in {directory_path}")
                return
            
            # Process files
            for file_path in supported_files:
                try:
                    await self.add_document(file_path)
                except Exception as e:
                    logger.error(f"Failed to process file {file_path}: {e}")
                    continue
            
            logger.info(f"Successfully indexed {len(self.file_hashes)} documents from {directory_path}")
                
        except Exception as e:
            logger.error(f"Failed to initialize from directory: {e}")
            raise
    
    async def add_document(self, file_path: str):
        """Add or update a document"""
        try:
            if not self._validate_file(file_path):
                return
            
            # Check if file has actually changed
            current_hash = self._calculate_file_hash(file_path)
            if file_path in self.file_hashes and self.file_hashes[file_path] == current_hash:
                logger.info(f"File unchanged, skipping: {file_path}")
                return
            
            # Extract text
            text = self._extract_text(file_path)
            if not text or not text.strip():
                logger.warning(f"No text extracted from {file_path}")
                return
            
            # Remove old document chunks first
            await self._remove_document_chunks(file_path)
            
            # Chunk the text
            chunks = self._chunk_text(text)
            logger.info(f"Created {len(chunks)} chunks for {file_path}")
            
            # Process each chunk
            chunk_embeddings = []
            chunk_texts = []
            chunk_metadatas = []
            chunk_ids = []
            
            for chunk in chunks:
                # Generate embedding for this chunk
                embedding = self.embed_model.encode(chunk["text"]).tolist()
                
                # Create metadata for this chunk
                metadata = {
                    "file_path": file_path,
                    "file_size": os.path.getsize(file_path),
                    "file_type": os.path.splitext(file_path)[1].lower(),
                    "extracted_at": str(datetime.now()),
                    "chunk_id": chunk["chunk_id"],
                    "total_chunks": chunk["total_chunks"]
                }
                
                # Create unique ID for this chunk
                chunk_id = f"{file_path}_chunk_{chunk['chunk_id']}"
                
                chunk_embeddings.append(embedding)
                chunk_texts.append(chunk["text"])
                chunk_metadatas.append(metadata)
                chunk_ids.append(chunk_id)
            
            # Batch insert all chunks
            if chunk_embeddings:
                self.collection.upsert(
                    ids=chunk_ids,
                    embeddings=chunk_embeddings,
                    documents=chunk_texts,
                    metadatas=chunk_metadatas
                )
            
            # Update file hash
            self.file_hashes[file_path] = current_hash
            
            logger.info(f"Successfully added/updated document: {file_path} ({len(chunks)} chunks)")
            
        except Exception as e:
            logger.error(f"Error adding document {file_path}: {e}")
            raise

    async def remove_document(self, file_path: str):
        """Remove a document from the index when file is deleted"""
        try:
            await self._remove_document_chunks(file_path)
            
            # Remove from file hashes
            if file_path in self.file_hashes:
                del self.file_hashes[file_path]
            
            logger.info(f"Successfully removed document: {file_path}")
            
        except Exception as e:
            logger.error(f"Error removing document {file_path}: {e}")

    async def _remove_document_chunks(self, file_path: str):
        """Remove all chunks for a specific document"""
        try:
            # Get all chunks for this file
            results = self.collection.get(
                where={"file_path": file_path}
            )
            
            if results['ids']:
                self.collection.delete(ids=results['ids'])
                logger.info(f"Removed {len(results['ids'])} chunks for {file_path}")
                
        except Exception as e:
            logger.error(f"Error removing document chunks {file_path}: {e}")
    
    async def query(self, query_text: str):
        """Query documents"""
        try:
            # Generate query embedding
            query_embedding = self.embed_model.encode(query_text).tolist()
            
            # Search ChromaDB
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=5,
                include=['documents', 'metadatas', 'distances']
            )
            
            if not results['documents'] or not results['documents'][0]:
                return QueryResponse(
                    message="I don't have information about that in the current documents.",
                    sources=[]
                )
            
            # Prepare context and sources
            documents = results['documents'][0]
            metadatas = results['metadatas'][0]
            distances = results['distances'][0]
            
            # Group chunks by file for better context
            file_chunks = {}
            for doc, metadata, distance in zip(documents, metadatas, distances):
                file_path = metadata.get("file_path", "")
                if file_path not in file_chunks:
                    file_chunks[file_path] = []
                file_chunks[file_path].append({
                    "text": doc,
                    "distance": distance,
                    "chunk_id": metadata.get("chunk_id", 0)
                })
            
            # Create sources with grouped context
            sources = []
            context_parts = []
            
            for file_path, chunks in file_chunks.items():
                # Sort chunks by chunk_id for proper order
                chunks.sort(key=lambda x: x["chunk_id"])
                
                # Combine chunks for this file
                file_text = "\n".join([chunk["text"] for chunk in chunks])
                
                # Calculate average relevance score
                avg_distance = sum(chunk["distance"] for chunk in chunks) / len(chunks)
                relevance_score = 1.0 - avg_distance
                
                sources.append({
                    "file_path": file_path,
                    "relevance_score": relevance_score,
                    "content_snippet": file_text[:300] + "..." if len(file_text) > 300 else file_text,
                    "chunks_found": len(chunks)
                })
                
                context_parts.append(file_text)
            
            # Generate response using Ollama
            context = "\n\n---\n\n".join(context_parts)
            response = await self._generate_response(query_text, context)
            
            return QueryResponse(message=response, sources=sources)
            
        except Exception as e:
            logger.error(f"Error during query: {e}")
            raise
    
    async def _generate_response(self, query: str, context: str) -> str:
        """Generate response using Ollama"""
        try:
            import httpx
            
            prompt = f"""You are a helpful AI assistant that answers questions based on the provided document context.

Context information:
{context}

Question: {query}

Instructions:
- Answer the question directly and clearly
- Use information from the provided context
- If the information is not in the context, say 'I don't have information about that in the current documents'
- Be concise and helpful

Answer:"""

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model": settings.OLLAMA_MODEL,
                        "prompt": prompt,
                        "stream": False
                    },
                    timeout=settings.OLLAMA_TIMEOUT
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result.get("response", "I couldn't generate a response.")
                else:
                    logger.error(f"Ollama API error: {response.status_code}")
                    return "I couldn't generate a response due to an error."
                    
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return "I couldn't generate a response due to an error."
    
    def _extract_text(self, file_path: str) -> str:
        """Extract text from file based on type"""
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext == ".pdf":
            return self._extract_pdf(file_path)
        elif ext == ".docx":
            return self._extract_docx(file_path)
        elif ext == ".txt":
            return self._extract_txt(file_path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")
    
    def _extract_pdf(self, file_path: str) -> str:
        """Extract text from PDF files"""
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            return text
        except Exception as e:
            logger.error(f"Error extracting PDF {file_path}: {e}")
            raise

    def _extract_docx(self, file_path: str) -> str:
        """Extract text from DOCX files"""
        try:
            import docx
            doc = docx.Document(file_path)
            return "\n".join([para.text for para in doc.paragraphs])
        except Exception as e:
            logger.error(f"Error extracting DOCX {file_path}: {e}")
            raise

    def _extract_txt(self, file_path: str) -> str:
        """Extract text from TXT files"""
        try:
            encodings = ['utf-8', 'latin-1', 'cp1252']
            for encoding in encodings:
                try:
                    with open(file_path, "r", encoding=encoding) as f:
                        return f.read()
                except UnicodeDecodeError:
                    continue
            
            with open(file_path, "r", encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error extracting TXT {file_path}: {e}")
            raise
    
    def get_indexed_files(self) -> List[str]:
        """Get list of indexed files"""
        return list(self.file_hashes.keys())
    
    def get_index_stats(self) -> dict:
        """Get statistics about the index"""
        try:
            return {
                "total_files": len(self.file_hashes),
                "indexed_files": list(self.file_hashes.keys()),
                "collection_count": self.collection.count(),
                "current_directory": self.current_directory
            }
        except Exception as e:
            logger.error(f"Error getting index stats: {e}")
            return {"error": str(e)}

    
    def _chunk_text(self, text: str, chunk_size: int = 1000, overlap: int = 200) -> List[dict]:
        """Split text into overlapping chunks with semantic boundaries"""
        if len(text) <= chunk_size:
            # No need to chunk small texts
            return [{"text": text, "chunk_id": 0, "total_chunks": 1}]
        
        chunks = []
        start = 0
        chunk_id = 0
        
        while start < len(text):
            end = start + chunk_size
            
            # Try to find a good break point (sentence or paragraph end)
            if end < len(text):
                # Look for sentence endings first
                for i in range(end, max(start + chunk_size - 100, start), -1):
                    if text[i] in '.!?':
                        end = i + 1
                        break
                else:
                    # If no sentence ending, look for paragraph breaks
                    for i in range(end, max(start + chunk_size - 50, start), -1):
                        if text[i] == '\n' and (i + 1 >= len(text) or text[i + 1] == '\n'):
                            end = i + 1
                            break
            
            chunk_text = text[start:end].strip()
            if chunk_text:  # Only add non-empty chunks
                chunks.append({
                    "text": chunk_text,
                    "chunk_id": chunk_id,
                    "total_chunks": None  # Will be set after all chunks are created
                })
                chunk_id += 1
            
            # Calculate next start position with overlap
            start = max(start + 1, end - overlap)
            
            # Prevent infinite loops
            if start >= len(text):
                break
        
        # Set total_chunks for all chunks
        total_chunks = len(chunks)
        for chunk in chunks:
            chunk["total_chunks"] = total_chunks
        
        return chunks

class QueryResponse:
    def __init__(self, message: str, sources: List[dict]):
        self.message = message
        self.sources = sources
