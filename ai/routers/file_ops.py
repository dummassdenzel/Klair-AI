"""File system operations: rename, delete, move — scoped to the indexed directory."""

import logging
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from dependencies import require_app_state

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_and_guard(file_path: str, current_dir: str) -> Path:
    """Resolve file_path and ensure it lives under current_dir."""
    abs_file = Path(file_path).resolve()
    abs_dir = Path(current_dir).resolve()
    if abs_dir not in abs_file.parents and abs_file != abs_dir:
        raise HTTPException(status_code=403, detail="Path is outside the indexed directory")
    if not abs_file.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return abs_file


def _require_dir(state) -> str:
    current_dir = state.doc_processor.current_directory
    if not current_dir:
        raise HTTPException(status_code=400, detail="No directory loaded")
    return current_dir


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class RenameRequest(BaseModel):
    file_path: str
    new_name: str


class DeleteRequest(BaseModel):
    file_path: str


class MoveRequest(BaseModel):
    file_path: str
    destination_dir: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/files/rename")
async def rename_file(body: RenameRequest, state=Depends(require_app_state)):
    current_dir = _require_dir(state)
    src = _resolve_and_guard(body.file_path, current_dir)

    new_name = body.new_name.strip()
    if not new_name or "/" in new_name or "\\" in new_name:
        raise HTTPException(status_code=400, detail="Invalid filename")

    dst = src.parent / new_name
    if dst.exists():
        raise HTTPException(status_code=409, detail=f"'{new_name}' already exists in this folder")

    src.rename(dst)
    logger.info("Renamed %s → %s", src, dst)

    await state.doc_processor.remove_document(str(src))
    try:
        await state.doc_processor.add_document(str(dst), use_queue=False)
    except Exception as exc:
        logger.warning("Re-indexing after rename failed (non-fatal): %s", exc)

    return {"status": "ok", "new_path": str(dst)}


@router.post("/files/delete")
async def delete_file(body: DeleteRequest, state=Depends(require_app_state)):
    current_dir = _require_dir(state)
    src = _resolve_and_guard(body.file_path, current_dir)

    await state.doc_processor.remove_document(str(src))
    src.unlink()
    logger.info("Deleted %s", src)

    return {"status": "ok"}


@router.post("/files/move")
async def move_file(body: MoveRequest, state=Depends(require_app_state)):
    current_dir = _require_dir(state)
    src = _resolve_and_guard(body.file_path, current_dir)

    abs_dst_dir = Path(body.destination_dir).resolve()
    abs_dir = Path(current_dir).resolve()
    if abs_dir != abs_dst_dir and abs_dir not in abs_dst_dir.parents:
        raise HTTPException(status_code=403, detail="Destination is outside the indexed directory")
    if not abs_dst_dir.is_dir():
        raise HTTPException(status_code=404, detail="Destination folder not found")

    dst = abs_dst_dir / src.name
    if dst.exists():
        raise HTTPException(status_code=409, detail=f"'{src.name}' already exists in the destination folder")

    shutil.move(str(src), str(dst))
    logger.info("Moved %s → %s", src, dst)

    await state.doc_processor.remove_document(str(src))
    try:
        await state.doc_processor.add_document(str(dst), use_queue=False)
    except Exception as exc:
        logger.warning("Re-indexing after move failed (non-fatal): %s", exc)

    return {"status": "ok", "new_path": str(dst)}


@router.get("/files/folders")
async def get_folders(state=Depends(require_app_state)):
    """Return the full folder tree under the indexed directory (folders only)."""
    current_dir = _require_dir(state)
    root = Path(current_dir).resolve()

    def walk(path: Path) -> dict:
        children = []
        try:
            for child in sorted(path.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    children.append(walk(child))
        except PermissionError:
            pass
        return {"name": path.name or str(path), "path": str(path), "children": children}

    return {"root": str(root), "tree": walk(root)}
