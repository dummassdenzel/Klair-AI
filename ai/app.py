# ai/app.py
import os
import chromadb
from fastapi import FastAPI, UploadFile, File, HTTPException
from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex, Settings, load_index_from_storage
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.ollama import Ollama
from pydantic import BaseModel
import threading
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import hashlib
import json

# --- setup ---
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_PATH = os.path.join(project_root, "documents") # --- where our docs live ---
DB_PATH = os.path.join(project_root, "chroma_db") # --- where chroma db stores our embeddings ---

# ensure folders exist at startup
os.makedirs(DOCS_PATH, exist_ok=True)
os.makedirs(DB_PATH, exist_ok=True)

# --- settings ---
Settings.llm = Ollama(model="tinyllama", request_timeout=120.0) # --- our language model ---
Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5") # --- our embedding model ---

db = chromadb.PersistentClient(path=DB_PATH)
chroma_collection = db.get_or_create_collection("klair-ai-store")
vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
storage_context = StorageContext.from_defaults(vector_store=vector_store)

# --- helper functions for incremental indexing ---
INDEX_TRACK_FILE = os.path.join(DB_PATH, "indexed_files.json")

def compute_file_hash(file_path):
    """Compute SHA256 hash of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()

def load_indexed_files():
    """Load previously indexed file hashes."""
    if os.path.exists(INDEX_TRACK_FILE):
        with open(INDEX_TRACK_FILE, "r") as f:
            return json.load(f)
    return {}

def save_indexed_files(indexed_files):
    """Save indexed file hashes."""
    with open(INDEX_TRACK_FILE, "w") as f:
        json.dump(indexed_files, f)

def incremental_index(file_path: str):
    """
    Adds/updates a single file in the Chroma index without rebuilding everything.
    """
    global index, query_engine

    if not os.path.exists(file_path):
        print(f"⚠️ Skipping, file does not exist: {file_path}")
        return

    # Load just this file
    documents = SimpleDirectoryReader(input_files=[file_path]).load_data()

    # Insert into the index
    index.insert(documents)

    # Persist changes
    index.storage_context.persist(persist_dir=DB_PATH)

    # Refresh query engine
    query_engine = index.as_query_engine()
    print(f"✅ Incrementally indexed {file_path}")


# --- utility to build/rebuild full index ---
def build_index():
    """
    Rebuilds the full index from all documents in the documents folder.
    Useful for initial setup or manual rebuild.
    """
    # Delete existing collection
    db.delete_collection("klair-ai-store")

    # Create fresh collection
    chroma_collection = db.get_or_create_collection("klair-ai-store")
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    if os.listdir(DOCS_PATH):
        documents = SimpleDirectoryReader(DOCS_PATH).load_data()
        index = VectorStoreIndex.from_documents(documents, storage_context=storage_context)
        index.storage_context.persist(persist_dir=DB_PATH)
        print("✅ Full index rebuilt from documents folder.")
    else:
        index = VectorStoreIndex([], storage_context=storage_context)
        print("✅ Empty index created.")

    # Reset tracked files
    tracked_files = {f: compute_file_hash(os.path.join(DOCS_PATH, f)) for f in os.listdir(DOCS_PATH)}
    save_indexed_files(tracked_files)
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

# --- watchdog handler ---
class DocsChangeHandler(FileSystemEventHandler):
    def __init__(self, debounce_time=5):
        self.debounce_time = debounce_time
        self._last_event = 0
        self._lock = threading.Lock()
        self._rebuild_scheduled = False

    def on_any_event(self, event):
        if event.is_directory:
            return
        with self._lock:
            now = time.time()
            # debounce: only trigger if enough time passed since last event
            if now - self._last_event > self.debounce_time:
                self._last_event = now
                if not self._rebuild_scheduled:
                    self._rebuild_scheduled = True
                    threading.Thread(target=self._rebuild_index_background).start()

    def _rebuild_index_background(self):
        global index, query_engine
        print("🔄 Detected change in documents folder, rebuilding index in background...")
        try:
            index = build_index()  # full rebuild
            query_engine = index.as_query_engine()
            print("✅ Background rebuild complete.")
        finally:
            with self._lock:
                self._rebuild_scheduled = False


# --- start watchdog in background ---
def start_watchdog():
    event_handler = DocsChangeHandler()
    observer = Observer()
    observer.schedule(event_handler, path=DOCS_PATH, recursive=True)
    observer.daemon = True  # stops observer when main thread exits
    observer.start()
    print("👀 Watchdog monitoring documents folder for changes...")

# start it at app startup
start_watchdog()

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
    global query_engine
    response = query_engine.query(req.question)
    return {"answer": str(response)}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        file_path = os.path.join(DOCS_PATH, file.filename)

        # Save uploaded file
        with open(file_path, "wb") as f:
            f.write(await file.read())

        return {"filename": file.filename, "status": "file uploaded (index will update automatically)"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- optional manual rebuild endpoint ---
@app.post("/rebuild_index")
async def rebuild_index_manual():
    global index, query_engine
    index = build_index()
    query_engine = index.as_query_engine()
    return {"status": "full index rebuilt successfully"}
