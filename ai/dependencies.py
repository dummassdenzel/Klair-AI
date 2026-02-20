"""Shared singletons and FastAPI dependencies used across routers."""

from fastapi import HTTPException, Request
from pathlib import Path
from typing import Optional

from database import DatabaseService

db_service = DatabaseService()


def require_app_state(request: Request):
    """Dependency: require that a directory has been set (processor initialized)."""
    state = request.app.state
    if not getattr(state, "doc_processor", None) or not getattr(state, "current_directory", None):
        raise HTTPException(status_code=400, detail="No directory set")
    return state


def validate_file_under_directory(file_path: Path, directory: Optional[str]) -> None:
    """
    Ensure the file is under the configured document directory.
    Raises HTTPException(403) if no directory is set or file is outside it.
    """
    if not directory:
        raise HTTPException(
            status_code=403,
            detail="No document directory set. Set a document directory first."
        )
    dir_resolved = Path(directory).resolve()
    if not dir_resolved.exists() or not dir_resolved.is_dir():
        raise HTTPException(status_code=403, detail="Document directory is not valid.")
    try:
        file_path.resolve().relative_to(dir_resolved)
    except ValueError:
        raise HTTPException(
            status_code=403,
            detail="Access denied. File is outside the document directory."
        )
