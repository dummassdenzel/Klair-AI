# ai/app.py
import os
import chromadb
from fastapi import FastAPI, UploadFile, File, HTTPException
from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex, Settings, load_index_from_storage
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.ollama import Ollama
from pydantic import BaseModel


# --- setup ---
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_PATH = os.path.join(project_root, "documents") # --- where our docs live ---
DB_PATH = os.path.join(project_root, "chroma_db") # --- where chroma db stores our embeddings ---

# ensure folders exist at startup
os.makedirs(DOCS_PATH, exist_ok=True)
os.makedirs(DB_PATH, exist_ok=True)

# --- settings ---
Settings.llm = Ollama(model="mistral", request_timeout=120.0) # --- our language model ---
Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5") # --- our embedding model ---

db = chromadb.PersistentClient(path=DB_PATH)
chroma_collection = db.get_or_create_collection("klair-ai-store")
vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
storage_context = StorageContext.from_defaults(vector_store=vector_store)

# --- utility to build/rebuild index ---
def build_index():
    
    # Rebuilds the index from all documents in the documents folder.
    # Supports manual file add/remove as well as API uploads.
    
    if os.listdir(DOCS_PATH):
        documents = SimpleDirectoryReader(DOCS_PATH).load_data()
        index = VectorStoreIndex.from_documents(documents, storage_context=storage_context)
        index.storage_context.persist(persist_dir=DB_PATH)
        print("✅ Index rebuilt from documents folder.")
    else:
        index = VectorStoreIndex([], storage_context=storage_context)
        print("✅ Empty index created.")
    return index

# --- load index at startup ---
try:
    print("🔄 Attempting to load index from storage...")
    index = load_index_from_storage(storage_context)
    print("✅ Index loaded successfully.")
except Exception as e:
    print(f"⚠️ No existing index found. Rebuilding... ({e})")
    index = build_index()

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
    global index, query_engine
    # Rebuild index in case someone manually added/removed files
    index = build_index()
    query_engine = index.as_query_engine()

    response = query_engine.query(req.question)
    return {"answer": str(response)}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        file_path = os.path.join(DOCS_PATH, file.filename)

        # Save uploaded file
        with open(file_path, "wb") as f:
            f.write(await file.read())

        # Rebuild index after upload
        global index, query_engine
        index = build_index()
        query_engine = index.as_query_engine()

        return {"filename": file.filename, "status": "file uploaded and indexed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))