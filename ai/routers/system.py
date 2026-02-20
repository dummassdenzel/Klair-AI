"""System status, configuration, metrics, and analytics endpoints."""

from fastapi import APIRouter, HTTPException, Request
import logging

from dependencies import db_service, metrics_service, rag_analytics
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["system"])


# ---------------------------------------------------------------------------
# Status & configuration
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@router.get("/metrics/summary")
async def get_metrics_summary(time_window_minutes: int = 60):
    try:
        return {"status": "success", "metrics": metrics_service.get_metrics_summary(time_window_minutes=time_window_minutes)}
    except Exception as e:
        logger.error(f"Failed to get metrics summary: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get metrics summary: {str(e)}")


@router.get("/metrics/retrieval-stats")
async def get_retrieval_stats(time_window_minutes: int = 60):
    try:
        return {"status": "success", "stats": metrics_service.get_retrieval_stats(time_window_minutes=time_window_minutes)}
    except Exception as e:
        logger.error(f"Failed to get retrieval stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get retrieval stats: {str(e)}")


@router.get("/metrics/time-series")
async def get_time_series(metric_type: str = "response_time", time_window_minutes: int = 60, bucket_minutes: int = 5):
    try:
        return {
            "status": "success", "metric_type": metric_type,
            "time_series": metrics_service.get_time_series(
                metric_type=metric_type, time_window_minutes=time_window_minutes, bucket_minutes=bucket_minutes,
            ),
        }
    except Exception as e:
        logger.error(f"Failed to get time series: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get time series: {str(e)}")


@router.get("/metrics/recent-queries")
async def get_recent_queries(limit: int = 20):
    try:
        return {"status": "success", "queries": metrics_service.get_recent_queries(limit=limit)}
    except Exception as e:
        logger.error(f"Failed to get recent queries: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get recent queries: {str(e)}")


@router.get("/metrics/counters")
async def get_counters():
    try:
        return {"status": "success", "counters": metrics_service.get_counters()}
    except Exception as e:
        logger.error(f"Failed to get counters: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get counters: {str(e)}")


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@router.get("/analytics/query-patterns")
async def get_query_patterns(time_window_minutes: int = 60):
    try:
        return {"status": "success", "patterns": rag_analytics.get_query_patterns(time_window_minutes=time_window_minutes)}
    except Exception as e:
        logger.error(f"Failed to get query patterns: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get query patterns: {str(e)}")


@router.get("/analytics/document-usage")
async def get_document_usage():
    try:
        return {"status": "success", "usage": rag_analytics.get_document_usage_stats()}
    except Exception as e:
        logger.error(f"Failed to get document usage: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get document usage: {str(e)}")


@router.get("/analytics/retrieval-effectiveness")
async def get_retrieval_effectiveness(time_window_minutes: int = 60):
    try:
        return {"status": "success", "effectiveness": rag_analytics.get_retrieval_effectiveness(time_window_minutes=time_window_minutes)}
    except Exception as e:
        logger.error(f"Failed to get retrieval effectiveness: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get retrieval effectiveness: {str(e)}")


@router.get("/analytics/performance-trends")
async def get_performance_trends(time_window_minutes: int = 60, buckets: int = 6):
    try:
        return {"status": "success", "trends": rag_analytics.get_performance_trends(time_window_minutes=time_window_minutes, buckets=buckets)}
    except Exception as e:
        logger.error(f"Failed to get performance trends: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get performance trends: {str(e)}")


@router.get("/analytics/query-success")
async def get_query_success(time_window_minutes: int = 60):
    try:
        return {"status": "success", "success": rag_analytics.get_query_success_analysis(time_window_minutes=time_window_minutes)}
    except Exception as e:
        logger.error(f"Failed to get query success: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get query success: {str(e)}")


@router.get("/analytics/usage")
async def get_usage_analytics():
    try:
        return {"status": "success", "analytics": await db_service.get_usage_analytics()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
