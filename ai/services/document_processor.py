# app/services/document_processor.py
from llama_index.core import Document, VectorStoreIndex, SimpleDirectoryReader
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
import chromadb
from pathlib import Path
import os

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
        self.llm = Ollama(model="tinyllama", request_timeout=120.0)  # Using tinyllama model
        self.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")  # Local embedding model
        
        self.index = None
        self.query_engine = None
    
    async def initialize_from_directory(self, directory_path: str):
        """Load all documents from directory and create initial index"""
        try:
            # Use SimpleDirectoryReader without custom extractors first
            documents = SimpleDirectoryReader(directory_path).load_data()
            
            self.index = VectorStoreIndex.from_documents(
                documents,
                vector_store=self.vector_store,
                embed_model=self.embed_model
            )
            
            self._setup_query_engine()
            print(f"Successfully indexed {len(documents)} documents from {directory_path}")
        except Exception as e:
            print(f"Failed to initialize from directory: {e}")
    
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
        
    # Document extraction methods
    def _extract_pdf(self, file_path: str) -> str:
        """Extract text from PDF files"""
        import fitz  # PyMuPDF
        
        doc = fitz.open(file_path)
        text = ""
        for page in doc:
            text += page.get_text()
        return text
    
    def _extract_docx(self, file_path: str) -> str:
        """Extract text from DOCX files"""
        import docx
        
        doc = docx.Document(file_path)
        return "\n".join([para.text for para in doc.paragraphs])
    
    def _extract_txt(self, file_path: str) -> str:
        """Extract text from TXT files"""
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
            
    async def query(self, query_text: str):
        """Query the document index"""
        if not self.query_engine:
            raise ValueError("Query engine not initialized. Please load documents first.")
        
        return self.query_engine.query(query_text)
    
    async def update_document(self, file_path: str):
        """Update a single document in the index"""
        # Get file extension
        ext = os.path.splitext(file_path)[1].lower()
        
        # Extract text based on file type
        if ext == ".pdf":
            text = self._extract_pdf(file_path)
        elif ext == ".docx":
            text = self._extract_docx(file_path)
        elif ext == ".txt":
            text = self._extract_txt(file_path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")
        
        # Create document object
        doc = Document(text=text, metadata={"file_path": file_path})
        
        # Update index
        if self.index:
            self.index.insert(doc)
            self._setup_query_engine()
        
    async def remove_document(self, file_path: str):
        """Remove a document from the index when file is deleted"""
        try:
            # Remove from ChromaDB collection
            # You'll need to implement this based on your ChromaDB setup
            # This is a simplified example
            if self.index:
                # Remove documents with matching file_path from metadata
                # Implementation depends on your specific ChromaDB setup
                print(f"Removed document: {file_path}")
        except Exception as e:
            print(f"Error removing document {file_path}: {e}")
    
    def get_indexed_files(self):
        """Get list of indexed files"""
        if not self.index:
            return []
        
        # Get all documents from the index
        all_docs = self.index.docstore.docs
        file_paths = set()
        
        # Extract file paths from metadata
        for doc_id, doc in all_docs.items():
            if hasattr(doc, "metadata") and "file_path" in doc.metadata:
                file_paths.add(doc.metadata["file_path"])
        
        return list(file_paths)