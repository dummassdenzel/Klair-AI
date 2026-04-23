from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional
import asyncio
import logging

from services.document_processor.extraction import PPTXConverter
from services.document_processor.extraction.embedding_service import EmbeddingService
from config import settings
from database import create_tables

from services.logging_config import setup_logging

setup_logging(
    json_format=(settings.LOG_FORMAT.lower() == "json"),
    log_level=settings.LOG_LEVEL,
    log_file=settings.LOG_FILE if settings.LOG_FILE else None,
)
logger = logging.getLogger(__name__)

_prewarming_task: Optional[asyncio.Task] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _prewarming_task

    logger.info("Starting AI Document Assistant...")
    await create_tables()

    app.state.doc_processor = None
    app.state.file_monitor = None
    app.state.current_directory = None

    embedding_service = EmbeddingService(model_name=settings.EMBED_MODEL_NAME)
    app.state.embedding_service = embedding_service

    pptx_converter = PPTXConverter(
        libreoffice_path=settings.LIBREOFFICE_PATH or None,
        cache_dir=settings.PPTX_CACHE_DIR,
    )
    app.state.pptx_converter = pptx_converter
    if pptx_converter.is_available():
        logger.info("PPTX preview functionality enabled")
    else:
        logger.warning("PPTX preview disabled: LibreOffice not found")

    _prewarming_task = asyncio.create_task(_prewarm_services(embedding_service))

    yield

    logger.info("Shutting down AI Document Assistant...")
    monitor = getattr(app.state, "file_monitor", None)
    if monitor:
        await monitor.stop_monitoring()
    processor = getattr(app.state, "doc_processor", None)
    if processor:
        await processor.cleanup()
    if _prewarming_task and not _prewarming_task.done():
        _prewarming_task.cancel()


async def _prewarm_services(embedding_service: EmbeddingService):
    """Load the embedding model into memory so the first real query is fast."""
    try:
        await asyncio.to_thread(embedding_service.encode_texts, ["warm-up"])
        logger.info("Embedding model warmed up")
    except Exception as e:
        logger.warning(f"Embedding warm-up failed (non-fatal): {e}")


app = FastAPI(
    title="AI Document Assistant",
    description="RAG-powered document chat assistant with modular architecture",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "tauri://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from routers import chat, debug_retrieval, documents, edit, file_ops, system  # noqa: E402

app.include_router(chat.router)
app.include_router(documents.router)
app.include_router(edit.router)
app.include_router(file_ops.router)
app.include_router(system.router)
app.include_router(debug_retrieval.router)