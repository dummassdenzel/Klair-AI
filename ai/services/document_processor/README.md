# Document Processor Service Package

This package provides a modular, service-oriented architecture for processing documents and building a RAG (Retrieval-Augmented Generation) system.

## Architecture Overview

The document processor has been refactored from a monolithic class into focused, single-responsibility services:

```
document_processor/
├── __init__.py              # Package initialization and exports
├── config.py                # Centralized configuration
├── models.py                # Data models and types
├── text_extractor.py        # Text extraction from various file formats
├── chunker.py               # Semantic text chunking
├── embedding_service.py     # Document embedding management
├── vector_store.py          # ChromaDB vector store operations
├── llm_service.py           # LLM interactions via Ollama
├── file_validator.py        # File validation and metadata
├── orchestrator.py          # Main orchestrator coordinating all services
└── README.md                # This file
```

## Services

### 1. TextExtractor (`text_extractor.py`)
Handles text extraction from various document formats:
- **PDF**: Using PyMuPDF (fitz)
- **DOCX**: Using python-docx
- **TXT**: With encoding detection and fallback

**Key Features:**
- Async text extraction to avoid blocking
- Comprehensive error handling
- Support for multiple encodings

### 2. DocumentChunker (`chunker.py`)
Creates semantic chunks from document text:
- **Configurable chunk size and overlap**
- **Smart boundary detection** (sentences, paragraphs, whitespace)
- **Maintains document structure**

### 3. EmbeddingService (`embedding_service.py`)
Manages document embeddings:
- **Sentence transformer model management**
- **Batch processing for efficiency**
- **Model reloading and cleanup**

### 4. VectorStoreService (`vector_store.py`)
Handles ChromaDB operations:
- **Collection management**
- **Batch chunk insertion**
- **Similarity search**
- **Document removal and cleanup**

### 5. LLMService (`llm_service.py`)
Manages LLM interactions:
- **Ollama API integration**
- **Prompt building and management**
- **Response generation**
- **HTTP client management**

### 6. FileValidator (`file_validator.py`)
File validation and metadata:
- **File type validation**
- **Size and permission checks**
- **Hash calculation for change detection**
- **Comprehensive metadata extraction**

### 7. DocumentProcessorOrchestrator (`orchestrator.py`)
Main orchestrator that coordinates all services:
- **Service initialization and coordination**
- **Document processing workflow**
- **Batch processing management**
- **Query processing and RAG responses**

## Usage

### Basic Usage

```python
from services.document_processor import DocumentProcessorOrchestrator

# Initialize the processor
processor = DocumentProcessorOrchestrator(
    persist_dir="./chroma_db",
    embed_model_name="BAAI/bge-small-en-v1.5",
    chunk_size=1000,
    chunk_overlap=200
)

# Process documents from a directory
await processor.initialize_from_directory("/path/to/documents")

# Query the documents
result = await processor.query("What is this document about?")
print(result.message)
```

### Advanced Usage with Custom Configuration

```python
from services.document_processor import DocumentProcessorOrchestrator, config

# Update configuration
config.update(
    chunk_size=1500,
    chunk_overlap=300,
    ollama_model="llama2:13b"
)

# Initialize with custom config
processor = DocumentProcessorOrchestrator(
    chunk_size=config.chunk_size,
    chunk_overlap=config.chunk_overlap,
    ollama_model=config.ollama_model
)
```

### Using Individual Services

```python
from services.document_processor import TextExtractor, DocumentChunker

# Extract text from a file
extractor = TextExtractor()
text = await extractor.extract_text_async("document.pdf")

# Create chunks
chunker = DocumentChunker(chunk_size=1000, chunk_overlap=200)
chunks = chunker.create_chunks(text, "document.pdf")
```

## Configuration

Configuration can be set via environment variables:

```bash
export CHROMA_PERSIST_DIR="./my_chroma_db"
export EMBED_MODEL_NAME="BAAI/bge-large-en-v1.5"
export MAX_FILE_SIZE_MB=100
export CHUNK_SIZE=1500
export CHUNK_OVERLAP=300
export OLLAMA_BASE_URL="http://localhost:11434"
export OLLAMA_MODEL="llama2:13b"
export BATCH_SIZE=20
export MAX_CONCURRENT_FILES=10
```

## Benefits of the New Architecture

1. **Separation of Concerns**: Each service has a single responsibility
2. **Testability**: Individual services can be tested in isolation
3. **Maintainability**: Easier to modify and extend specific functionality
4. **Reusability**: Services can be used independently
5. **Configuration**: Centralized configuration management
6. **Error Handling**: Better error isolation and handling
7. **Resource Management**: Proper cleanup and resource management

## Usage

Use the `DocumentProcessorOrchestrator` class for all document processing:

```python
from services.document_processor import DocumentProcessorOrchestrator

processor = DocumentProcessorOrchestrator()
await processor.initialize_from_directory("/path/to/documents")
result = await processor.query("What is this document about?")
```

## Testing

Each service can be tested independently:

```python
import pytest
from services.document_processor import TextExtractor, DocumentChunker

def test_text_extractor():
    extractor = TextExtractor()
    # Test text extraction logic

def test_chunker():
    chunker = DocumentChunker(chunk_size=1000, chunk_overlap=200)
    # Test chunking logic
```

## Future Enhancements

- Database persistence for file metadata
- Caching layer for embeddings
- Plugin system for additional file formats
- Metrics and monitoring
- Distributed processing support
- Advanced chunking strategies
