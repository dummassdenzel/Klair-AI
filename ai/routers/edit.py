"""Edit endpoints — apply or discard an AI-proposed document edit."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents/edit", tags=["edit"])


class ApplyRequest(BaseModel):
    proposal_id: str


class DiscardRequest(BaseModel):
    proposal_id: str


@router.post("/apply")
async def apply_edit(body: ApplyRequest, request: Request):
    """
    Apply a confirmed edit proposal: back up the file, write the changes, trigger re-index.
    The proposal expires after 30 minutes; applying it removes it from the store.
    """
    doc_processor = getattr(request.app.state, "doc_processor", None)
    if doc_processor is None:
        raise HTTPException(status_code=503, detail="Document processor not ready")

    proposal_id = body.proposal_id.strip()
    if not proposal_id:
        raise HTTPException(status_code=400, detail="proposal_id is required")

    try:
        result = doc_processor.apply_edit_proposal(proposal_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("apply_edit failed for proposal %s: %s", proposal_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to apply edit: {exc}")

    if result.get("applied_changes", 0) == 0:
        raise HTTPException(
            status_code=422,
            detail=(
                "The edit could not be applied — the target text was not found in the current "
                "file content. The file may have been modified since the proposal was generated. "
                "Please ask the AI to propose the edit again."
            ),
        )

    # Trigger re-index of the modified file so the vector store stays fresh
    file_path = result.get("file_path")

    if file_path:
        try:
            await doc_processor.enqueue_update(file_path, update_type="modified", user_requested=True)
            logger.info("Re-index triggered for edited file: %s", file_path)
        except Exception as exc:
            logger.warning("Re-index trigger failed (non-fatal): %s", exc)

    return {
        "status": "success",
        "message": f"Edit applied ({result.get('applied_changes', 0)} change(s)). "
                   f"Backup saved at: {result.get('backup_path', 'unknown')}",
        "applied_changes": result.get("applied_changes", 0),
        "backup_path": result.get("backup_path"),
    }


@router.post("/discard")
async def discard_edit(body: DiscardRequest, request: Request):
    """Discard a pending edit proposal without touching the file."""
    doc_processor = getattr(request.app.state, "doc_processor", None)
    if doc_processor is None:
        raise HTTPException(status_code=503, detail="Document processor not ready")

    proposal_id = body.proposal_id.strip()
    if not proposal_id:
        raise HTTPException(status_code=400, detail="proposal_id is required")

    try:
        doc_processor.edit_service.remove_proposal(proposal_id)
    except Exception as exc:
        logger.warning("discard_edit: could not remove proposal %s: %s", proposal_id, exc)

    return {"status": "success", "message": "Edit proposal discarded"}
