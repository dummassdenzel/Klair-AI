# app/services/document_processor.py
from llama_index.core import Document, VectorStoreIndex, SimpleDirectoryReader
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
import chromadb
from pathlib import Path
import os
import hashlib
import logging
from typing import Optional, Dict, Set
from config import settings
from datetime import datetime

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
        
        # Initialize LlamaIndex components with Ollama
        self.vector_store = ChromaVectorStore(chroma_collection=self.collection)
        self.llm = Ollama(model="tinyllama", request_timeout=120.0)
        self.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")
        
        self.index = None
        self.query_engine = None
        
        # Track file hashes to detect actual changes
        self.file_hashes: Dict[str, str] = {}
        self.supported_extensions = {".pdf", ".docx", ".txt"}
        
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
            # Check if file exists
            if not os.path.exists(file_path):
                logger.warning(f"File does not exist: {file_path}")
                return False
            
            # Check file extension
            ext = os.path.splitext(file_path)[1].lower()
            if ext not in self.supported_extensions:
                logger.warning(f"Unsupported file type: {ext} for {file_path}")
                return False
            
            # Check file size
            file_size = os.path.getsize(file_path)
            if file_size > self.max_file_size_bytes:
                logger.warning(f"File too large ({file_size / 1024 / 1024:.1f}MB): {file_path}")
                return False
            
            # Check if file is readable
            if not os.access(file_path, os.R_OK):
                logger.warning(f"File not readable: {file_path}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating file {file_path}: {e}")
            return False
    
    async def initialize_from_directory(self, directory_path: str):
        """Load all documents from directory and create initial index"""
        try:
            logger.info(f"Initializing document processor for directory: {directory_path}")
            
            # Validate directory
            if not os.path.exists(directory_path):
                raise ValueError(f"Directory does not exist: {directory_path}")
            
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
            
            # Process files with error handling
            documents = []
            for file_path in supported_files:
                try:
                    doc = await self._process_single_file(file_path)
                    if doc:
                        documents.append(doc)
                        # Store file hash
                        self.file_hashes[file_path] = self._calculate_file_hash(file_path)
                except Exception as e:
                    logger.error(f"Failed to process file {file_path}: {e}")
                    continue
            
            if documents:
                self.index = VectorStoreIndex.from_documents(
                    documents,
                    vector_store=self.vector_store,
                    embed_model=self.embed_model
                )
                self._setup_query_engine()
                logger.info(f"Successfully indexed {len(documents)} documents from {directory_path}")
            else:
                logger.warning("No documents were successfully processed")
                
        except Exception as e:
            logger.error(f"Failed to initialize from directory: {e}")
            raise
    
    async def _process_single_file(self, file_path: str) -> Optional[Document]:
        """Process a single file with comprehensive error handling"""
        try:
            # Validate file
            if not self._validate_file(file_path):
                return None
            
            # Extract text based on file type
            ext = os.path.splitext(file_path)[1].lower()
            
            if ext == ".pdf":
                text = self._extract_pdf(file_path)
            elif ext == ".docx":
                text = self._extract_docx(file_path)
            elif ext == ".txt":
                text = self._extract_txt(file_path)
            else:
                logger.warning(f"Unsupported file type: {ext}")
                return None
            
            # Validate extracted text
            if not text or not text.strip():
                logger.warning(f"No text extracted from {file_path}")
                return None
            
            # Create document with metadata
            metadata = {
                "file_path": file_path,
                "file_size": os.path.getsize(file_path),
                "file_type": ext,
                "extracted_at": str(datetime.now())
            }
            
            return Document(text=text, metadata=metadata)
            
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
            return None
    
    def _setup_query_engine(self):
        """Configure RAG query engine with custom prompts"""
        from llama_index.core.prompts import PromptTemplate
        
        qa_prompt = PromptTemplate(
            "Context information is below.\n"
            "---------------------\n"
            "{context_str}\n"
            "---------------------\n"
            "Given the context information about documents in the monitored folder, "
            "answer the query. If the information is not contained in the documents, "
            "say 'I don't have information about that in the current documents.'\n"
            "Query: {query_str}\n"
            "Answer: "
        )
        
        self.query_engine = self.index.as_query_engine(
            llm=self.llm,
            similarity_top_k=5,
            text_qa_template=qa_prompt,
            response_mode="tree_summarize"
        )
    
    # Document extraction methods with error handling
    def _extract_pdf(self, file_path: str) -> str:
        """Extract text from PDF files with error handling"""
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
        """Extract text from DOCX files with error handling"""
        try:
            import docx
            
            doc = docx.Document(file_path)
            return "\n".join([para.text for para in doc.paragraphs])
        except Exception as e:
            logger.error(f"Error extracting DOCX {file_path}: {e}")
            raise
    
    def _extract_txt(self, file_path: str) -> str:
        """Extract text from TXT files with error handling"""
        try:
            # Try multiple encodings
            encodings = ['utf-8', 'latin-1', 'cp1252']
            for encoding in encodings:
                try:
                    with open(file_path, "r", encoding=encoding) as f:
                        return f.read()
                except UnicodeDecodeError:
                    continue
            
            # If all encodings fail, try with error handling
            with open(file_path, "r", encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error extracting TXT {file_path}: {e}")
            raise
    
    async def query(self, query_text: str):
        """Query the document index with error handling"""
        if not self.query_engine:
            raise ValueError("Query engine not initialized. Please load documents first.")
        
        try:
            return self.query_engine.query(query_text)
        except Exception as e:
            logger.error(f"Error during query: {e}")
            raise
    
    async def update_document(self, file_path: str):
        """Update a single document in the index with change detection"""
        try:
            # Check if file has actually changed
            current_hash = self._calculate_file_hash(file_path)
            if file_path in self.file_hashes and self.file_hashes[file_path] == current_hash:
                logger.info(f"File unchanged, skipping update: {file_path}")
                return
            
            # Process the file
            doc = await self._process_single_file(file_path)
            if not doc:
                logger.warning(f"Failed to process file for update: {file_path}")
                return
            
            # Update index
            if self.index:
                # Remove old version if it exists
                await self._remove_document_from_index(file_path)
                
                # Insert new version
                self.index.insert(doc)
                
                # Update file hash
                self.file_hashes[file_path] = current_hash
                
                logger.info(f"Successfully updated document: {file_path}")
            else:
                logger.warning("Index not initialized, cannot update document")
                
        except Exception as e:
            logger.error(f"Error updating document {file_path}: {e}")
    
    async def remove_document(self, file_path: str):
        """Remove a document from the index when file is deleted"""
        try:
            await self._remove_document_from_index(file_path)
            
            # Remove from file hashes
            if file_path in self.file_hashes:
                del self.file_hashes[file_path]
            
            logger.info(f"Successfully removed document: {file_path}")
            
        except Exception as e:
            logger.error(f"Error removing document {file_path}: {e}")
    
    async def _remove_document_from_index(self, file_path: str):
        """Remove document from ChromaDB index"""
        try:
            # Get document IDs that match the file path
            results = self.collection.get(
                where={"file_path": file_path}
            )
            
            if results['ids']:
                # Delete from ChromaDB
                self.collection.delete(ids=results['ids'])
                logger.info(f"Removed {len(results['ids'])} document chunks for {file_path}")
            
        except Exception as e:
            logger.error(f"Error removing document from index {file_path}: {e}")
    
    def get_indexed_files(self) -> list:
        """Get list of indexed files"""
        return list(self.file_hashes.keys())
    
    def get_index_stats(self) -> dict:
        """Get statistics about the index"""
        try:
            return {
                "total_files": len(self.file_hashes),
                "indexed_files": list(self.file_hashes.keys()),
                "collection_count": self.collection.count() if self.collection else 0,
                "index_initialized": self.index is not None,
                "query_engine_ready": self.query_engine is not None
            }
        except Exception as e:
            logger.error(f"Error getting index stats: {e}")
            return {"error": str(e)}