# ai/app.py
import os
import chromadb
from fastapi import FastAPI, UploadFile, Form
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings, StorageContext
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.ollama import Ollama
from pydantic import BaseModel

# --- setup ---
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_PATH = os.path.join(project_root, "documents") # --- where our docs live ---
DB_PATH = os.path.join(project_root, "chroma_db") # --- where chroma db stores our embeddings ---

# --- settings ---
Settings.llm = Ollama(model="mistral", request_timeout=120.0) # --- our language model ---
Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5") # --- our embedding model ---

db = chromadb.PersistentClient(path=DB_PATH)
chroma_collection = db.get_or_create_collection("klair-ai-store")
vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
storage_context = StorageContext.from_defaults(vector_store=vector_store)

# Load documents once at startup (optional: you can add endpoints to upload more docs later)
if os.path.exists(DOCS_PATH) and os.listdir(DOCS_PATH):
    documents = SimpleDirectoryReader(DOCS_PATH).load_data()
    index = VectorStoreIndex.from_documents(documents, storage_context=storage_context)
    index.storage_context.persist(persist_dir=DB_PATH)
else:
    print("⚠️ No documents found. Starting without index.")
    documents = []
    index = VectorStoreIndex([], storage_context=storage_context)


query_engine = index.as_query_engine()

# --- classes ---
class QueryRequest(BaseModel):
    question: str


# --- api ---
app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "ok"}

@app.post("/query")
async def query_ai(req: QueryRequest):
    response = query_engine.query(req.question)
    return {"answer": str(response)}

@app.post("/upload")
async def upload_file(file: UploadFile):
    file_path = os.path.join(DOCS_PATH, file.filename)
    with open(file_path, "wb") as f:
        f.write(await file.read())

    # Ingest new document into index
    new_docs = SimpleDirectoryReader(DOCS_PATH, input_files=[file_path]).load_data()
    index.insert_documents(new_docs)
    index.storage_context.persist(persist_dir=DB_PATH)


    return {"status": "file uploaded and indexed"}
