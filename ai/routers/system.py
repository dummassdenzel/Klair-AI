"""System status and configuration endpoints."""

from fastapi import APIRouter, HTTPException, Request
import logging

from dependencies import db_service
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["system"])


@router.get("/status")
async def get_status(request: Request):
    """Get current system status and configuration."""
    try:
        proc = getattr(request.app.state, "doc_processor", None)
        mon = getattr(request.app.state, "file_monitor", None)
        cur_dir = getattr(request.app.state, "current_directory", None)
        info: dict = {
            "directory_set": cur_dir is not None,
            "current_directory": cur_dir,
            "processor_ready": proc.is_ready() if proc else False,
            "monitor_running": mon.is_running if mon else False,
        }

        try:
            info["configuration"] = settings.to_dict()
        except Exception as e:
            logger.warning(f"Could not get configuration: {e}")
            info["configuration"] = {"error": "Configuration not available"}

        try:
            provider = (settings.LLM_PROVIDER or "ollama").lower()
            model_map = {
                "gemini": settings.GEMINI_MODEL or "gemini-2.5-pro",
                "groq": settings.GROQ_MODEL or "meta-llama/llama-4-scout-17b-16e-instruct",
            }
            info["llm"] = {
                "provider": provider,
                "model": model_map.get(provider, settings.OLLAMA_MODEL),
            }
        except Exception as e:
            logger.warning(f"Could not determine LLM provider/model: {e}")

        if proc:
            try:
                info["index_stats"] = await proc.get_stats()
            except Exception as e:
                logger.warning(f"Could not get index stats: {e}")
                info["index_stats"] = {"error": "Stats not available"}

        try:
            info["database_stats"] = await db_service.get_document_stats()
        except Exception as e:
            logger.warning(f"Could not get database stats: {e}")
            info["database_stats"] = {"error": "Database stats not available"}

        return info
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return {"error": str(e)}


@router.get("/configuration")
async def get_configuration():
    return {
        "current_config": settings.to_dict(),
        "environment_variables": {
            "CHROMA_PERSIST_DIR": settings.CHROMA_PERSIST_DIR,
            "EMBED_MODEL_NAME": settings.EMBED_MODEL_NAME,
            "MAX_FILE_SIZE_MB": settings.MAX_FILE_SIZE_MB,
            "CHUNK_SIZE": settings.CHUNK_SIZE,
            "CHUNK_OVERLAP": settings.CHUNK_OVERLAP,
            "OLLAMA_BASE_URL": settings.OLLAMA_BASE_URL,
            "OLLAMA_MODEL": settings.OLLAMA_MODEL,
        },
    }


@router.post("/update-configuration")
async def update_configuration(request: dict):
    try:
        updates = {k: v for k, v in request.items() if k in settings._UPDATABLE}
        if not updates:
            raise HTTPException(status_code=400, detail="No valid configuration updates provided")
        settings.update(**updates)
        logger.info(f"Configuration updated: {updates}")
        return {"status": "success", "message": "Configuration updated", "updated_values": updates, "current_config": settings.to_dict()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Configuration update failed: {e}")
        raise HTTPException(status_code=500, detail=f"Configuration update failed: {str(e)}")
