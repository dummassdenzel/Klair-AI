# app/services/document_processor.py
from llama_index.core import Document, VectorStoreIndex, SimpleDirectoryReader
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.llms.openai import OpenAI
from llama_index.embeddings.openai import OpenAIEmbedding
import chromadb
from pathlib import Path

class DocumentManager:
    def __init__(self, persist_dir: str = "./chroma_db"):
        # Initialize ChromaDB
        self.chroma_client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.chroma_client.get_or_create_collection(
            name="documents",
            metadata={"hnsw:space": "cosine"}
        )
        
        # Initialize LlamaIndex components
        self.vector_store = ChromaVectorStore(chroma_collection=self.collection)
        self.llm = OpenAI(model="gpt-4-1106-preview", temperature=0.1)
        self.embed_model = OpenAIEmbedding()
        
        self.index = None
        self.query_engine = None
    
    async def initialize_from_directory(self, directory_path: str):
        """Load all documents from directory and create initial index"""
        documents = SimpleDirectoryReader(
            directory_path,
            file_extractor={
                ".pdf": self._extract_pdf,
                ".docx": self._extract_docx,
                ".txt": self._extract_txt
            }
        ).load_data()
        
        self.index = VectorStoreIndex.from_documents(
            documents,
            vector_store=self.vector_store,
            embed_model=self.embed_model
        )
        
        self._setup_query_engine()
    
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