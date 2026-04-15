"""System status and configuration endpoints."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
import logging

from dependencies import db_service
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["system"])


class LLMConfigUpdate(BaseModel):
    provider: str
    ollama_model: Optional[str] = None
    ollama_base_url: Optional[str] = None
    gemini_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    groq_model: Optional[str] = None
    groq_api_key: Optional[str] = None


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
            # Best-effort LLM token usage (mainly for Groq). Useful for monitoring TPM usage.
            try:
                info["llm_token_usage"] = proc.get_llm_token_usage()
            except Exception as e:
                logger.warning(f"Could not get LLM token usage: {e}")

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


@router.get("/llm/config")
async def get_llm_config():
    """Return current LLM provider configuration. API keys are masked."""
    provider = (settings.LLM_PROVIDER or "ollama").lower()
    return {
        "provider": provider,
        "ollama_model": settings.OLLAMA_MODEL,
        "ollama_base_url": settings.OLLAMA_BASE_URL,
        "gemini_model": settings.GEMINI_MODEL,
        "gemini_api_key_set": bool(settings.GEMINI_API_KEY),
        "groq_model": settings.GROQ_MODEL,
        "groq_api_key_set": bool(settings.GROQ_API_KEY),
    }


@router.post("/llm/config")
async def update_llm_config(body: LLMConfigUpdate, request: Request):
    """Switch the active LLM provider and update model / API key at runtime."""
    provider = body.provider.lower().strip()
    if provider not in ("ollama", "gemini", "groq"):
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider!r}. Must be ollama, gemini, or groq.")

    # Build kwargs for Settings.update()
    setting_updates: dict = {"llm_provider": provider}
    if provider == "ollama":
        if body.ollama_model:
            setting_updates["ollama_model"] = body.ollama_model
        if body.ollama_base_url:
            setting_updates["ollama_base_url"] = body.ollama_base_url
    elif provider == "gemini":
        if body.gemini_model:
            setting_updates["gemini_model"] = body.gemini_model
        if body.gemini_api_key:
            setting_updates["gemini_api_key"] = body.gemini_api_key
    elif provider == "groq":
        if body.groq_model:
            setting_updates["groq_model"] = body.groq_model
        if body.groq_api_key:
            setting_updates["groq_api_key"] = body.groq_api_key

    settings.update(**setting_updates)

    # Propagate to the live LLMService if a processor is running
    proc = getattr(request.app.state, "doc_processor", None)
    if proc is not None:
        try:
            llm_svc = getattr(proc, "llm_service", None)
            if llm_svc is not None:
                switch_kwargs: dict = {}
                if provider == "ollama":
                    switch_kwargs["model"] = settings.OLLAMA_MODEL
                    switch_kwargs["base_url"] = settings.OLLAMA_BASE_URL
                elif provider == "gemini":
                    switch_kwargs["model"] = settings.GEMINI_MODEL
                    if settings.GEMINI_API_KEY:
                        switch_kwargs["api_key"] = settings.GEMINI_API_KEY
                elif provider == "groq":
                    switch_kwargs["model"] = settings.GROQ_MODEL
                    if settings.GROQ_API_KEY:
                        switch_kwargs["api_key"] = settings.GROQ_API_KEY
                llm_svc.switch_provider(provider, **switch_kwargs)
        except Exception as e:
            logger.warning("Could not switch live LLMService provider: %s", e)

    logger.info("LLM config updated: provider=%s", provider)
    return {
        "status": "success",
        "provider": provider,
        "ollama_model": settings.OLLAMA_MODEL,
        "ollama_base_url": settings.OLLAMA_BASE_URL,
        "gemini_model": settings.GEMINI_MODEL,
        "gemini_api_key_set": bool(settings.GEMINI_API_KEY),
        "groq_model": settings.GROQ_MODEL,
        "groq_api_key_set": bool(settings.GROQ_API_KEY),
    }
