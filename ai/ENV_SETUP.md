# Environment Configuration Guide

This document describes all environment variables for the RAG AI Assistant backend.

## Required Setup

Create a `.env` file in the `ai/` directory with the following variables:

## Database Configuration

```env
# PostgreSQL Connection
DATABASE_URL=postgresql://username:password@localhost:5432/klair_ai

# SQLAlchemy Debugging (set to true for SQL query logging)
SQLALCHEMY_ECHO=false
```

## LLM Provider Configuration

### Option 1: Using Ollama (Local)

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=tinyllama
OLLAMA_TIMEOUT=120
```

### Option 2: Using Google Gemini (Cloud)

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-pro
```

**Note:** You must have either Ollama running locally OR a valid Gemini API key depending on your `LLM_PROVIDER` setting.

## Embedding & Vector Store Configuration

```env
# ChromaDB persistence directory
CHROMA_PERSIST_DIR=./chroma_db

# Sentence Transformer embedding model
EMBED_MODEL_NAME=BAAI/bge-small-en-v1.5

# Document processing settings
MAX_FILE_SIZE_MB=50
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
```

## Optional Performance Settings

```env
# Concurrent processing limits
BATCH_SIZE=10
MAX_CONCURRENT_FILES=5
```

## Complete Example `.env` File

### For Gemini (Recommended for faster inference)

```env
# Database
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/klair_ai
SQLALCHEMY_ECHO=false

# LLM Provider - Gemini
LLM_PROVIDER=gemini
GEMINI_API_KEY=AIzaSyAbc123...your_actual_key
GEMINI_MODEL=gemini-2.5-pro

# Embedding & Vector Store
CHROMA_PERSIST_DIR=./chroma_db
EMBED_MODEL_NAME=BAAI/bge-small-en-v1.5

# Document Processing
MAX_FILE_SIZE_MB=50
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
BATCH_SIZE=10
MAX_CONCURRENT_FILES=5
```

### For Ollama (Local)

```env
# Database
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/klair_ai
SQLALCHEMY_ECHO=false

# LLM Provider - Ollama
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=tinyllama
OLLAMA_TIMEOUT=120

# Embedding & Vector Store
CHROMA_PERSIST_DIR=./chroma_db
EMBED_MODEL_NAME=BAAI/bge-small-en-v1.5

# Document Processing
MAX_FILE_SIZE_MB=50
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
BATCH_SIZE=10
MAX_CONCURRENT_FILES=5
```

## Getting API Keys

### Google Gemini API Key

1. Visit [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Sign in with your Google account
3. Click "Create API Key"
4. Copy the key and paste it into your `.env` file as `GEMINI_API_KEY`

## Switching Between Providers

To switch from Ollama to Gemini (or vice versa):

1. Update `LLM_PROVIDER` in your `.env` file
2. Ensure the corresponding API key (for Gemini) or service (for Ollama) is available
3. Restart the FastAPI backend

No code changes are needed - the system automatically uses the configured provider.

## Validation

After setting up your `.env` file, start the backend:

```bash
cd ai
source venv/bin/activate  # Linux/Mac
# OR
venv\Scripts\activate      # Windows

python -m uvicorn main:app --reload
```

Check the startup logs for:
- `LLMService initialized with provider: gemini` (or `ollama`)
- No errors about missing API keys or connection failures

Visit `http://localhost:8000/api/status` to verify the system is running with your configured LLM provider.

## Troubleshooting

### "GEMINI_API_KEY is not set"
- Ensure `LLM_PROVIDER=gemini` is set
- Add `GEMINI_API_KEY=...` with your actual key
- Restart the backend

### "Connection refused" with Ollama
- Start Ollama: `ollama serve`
- Verify it's running: `curl http://localhost:11434/api/tags`
- Check `OLLAMA_BASE_URL` matches your Ollama installation

### Database connection errors
- Ensure PostgreSQL is running
- Verify `DATABASE_URL` credentials are correct
- Run migrations: `alembic upgrade head`

### SQLAlchemy logs too verbose
- Set `SQLALCHEMY_ECHO=false` in `.env`
- Restart the backend

