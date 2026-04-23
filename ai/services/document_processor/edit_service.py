"""
EditService — document read, LLM-based edit proposal generation, and safe file write.

Phase 1 supports .txt and .docx files only.
Every write is preceded by a timestamped .bak copy; no file is touched until
the user explicitly confirms the proposal via the /api/documents/edit/apply endpoint.
"""

import json
import logging
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_READ_CHARS = 12_000   # truncate very large files before LLM call
PROPOSAL_TTL_SECONDS = 1800  # proposals expire after 30 minutes
SUPPORTED_EDIT_EXTENSIONS = {".txt", ".docx"}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class EditChange:
    find: str     # exact verbatim text to locate in document
    replace: str  # replacement text


@dataclass
class EditProposal:
    proposal_id: str
    document_name: str
    file_path: str
    file_type: str          # "txt" or "docx"
    changes: List[EditChange]
    summary: str
    expires_at: datetime = field(
        default_factory=lambda: datetime.utcnow() + timedelta(seconds=PROPOSAL_TTL_SECONDS)
    )

    def to_client_dict(self) -> Dict[str, Any]:
        """Serialise for the frontend — no internal state included."""
        return {
            "proposal_id": self.proposal_id,
            "document_name": self.document_name,
            "file_type": self.file_type,
            "changes": [{"find": c.find, "replace": c.replace} for c in self.changes],
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class EditService:
    """
    Handles the full edit lifecycle:
      1. read_for_edit   — extract plain text from file for the LLM
      2. generate_proposal — LLM produces structured find/replace diff
      3. apply_proposal  — validate, back up, write, return result

    `current_directory` must be set by the orchestrator whenever a new
    directory is loaded; it is used as a scope guard before every write.
    """

    def __init__(self) -> None:
        self.current_directory: Optional[str] = None
        self._pending: Dict[str, EditProposal] = {}

    # ------------------------------------------------------------------
    # Proposal store
    # ------------------------------------------------------------------

    def store_proposal(self, proposal: EditProposal) -> None:
        self._purge_expired()
        self._pending[proposal.proposal_id] = proposal

    def get_proposal(self, proposal_id: str) -> Optional[EditProposal]:
        self._purge_expired()
        return self._pending.get(proposal_id)

    def remove_proposal(self, proposal_id: str) -> None:
        self._pending.pop(proposal_id, None)

    def _purge_expired(self) -> None:
        now = datetime.utcnow()
        expired = [pid for pid, p in self._pending.items() if p.expires_at < now]
        for pid in expired:
            del self._pending[pid]

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def can_edit(self, file_path: str) -> bool:
        return Path(file_path).suffix.lower() in SUPPORTED_EDIT_EXTENSIONS

    def read_for_edit(self, file_path: str) -> Optional[str]:
        """Return a plain-text snapshot of the file for LLM consumption."""
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            logger.warning("read_for_edit: not found: %s", file_path)
            return None
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_EDIT_EXTENSIONS:
            logger.warning("read_for_edit: unsupported type %s for %s", suffix, file_path)
            return None
        try:
            if suffix == ".txt":
                content = path.read_text(encoding="utf-8", errors="replace")
            else:
                content = self._read_docx(str(path))
            if len(content) > MAX_READ_CHARS:
                content = content[:MAX_READ_CHARS] + "\n\n[... document truncated for length ...]"
            return content
        except Exception as exc:
            logger.error("read_for_edit failed for %s: %s", file_path, exc)
            return None

    def _read_docx(self, file_path: str) -> str:
        from docx import Document
        doc = Document(file_path)
        parts: List[str] = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                parts.append(text)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        text = para.text.strip()
                        if text:
                            parts.append(text)
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Generate proposal
    # ------------------------------------------------------------------

    async def generate_proposal(
        self,
        file_path: str,
        content: str,
        instruction: str,
        llm_service: Any,
    ) -> Optional[EditProposal]:
        """Ask the LLM to produce a structured find/replace diff, then validate it."""
        prompt = (
            "You are a precise document editor. Given a document and an edit instruction, "
            "output a JSON array of find/replace changes.\n\n"
            "Rules:\n"
            '  - Each "find" MUST be an EXACT verbatim substring of the document '
            "(copy character-for-character, including punctuation and spacing)\n"
            "  - Make only the minimum changes to fulfill the instruction\n"
            '  - To REMOVE text: set "replace" to an empty string ""\n'
            "  - If you cannot find the exact text, output an empty array []\n"
            "  - Output ONLY the JSON array — no explanation, no markdown fences\n\n"
            f"Document:\n---\n{content}\n---\n\n"
            f"Instruction: {instruction}\n\n"
            "JSON array examples:\n"
            '  Replace: [{"find": "old text", "replace": "new text"}]\n'
            '  Remove:  [{"find": "text to delete", "replace": ""}]\n\n'
            "JSON array:\n"
        )
        try:
            raw = await llm_service.generate_simple(
                prompt,
                prompt_type="short_direct",
                max_completion_tokens=512,
            )
        except Exception as exc:
            logger.error("generate_proposal LLM call failed: %s", exc)
            return None

        changes = self._parse_and_validate_changes(raw, content)
        if not changes:
            logger.info("generate_proposal: no valid changes produced for %s", file_path)
            return None

        proposal = EditProposal(
            proposal_id=str(uuid.uuid4()),
            document_name=Path(file_path).name,
            file_path=file_path,
            file_type=Path(file_path).suffix.lower().lstrip("."),
            changes=changes,
            summary=self._make_summary(changes),
        )
        self.store_proposal(proposal)
        return proposal

    def _parse_and_validate_changes(
        self, raw: str, content: str
    ) -> List[EditChange]:
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            logger.warning("edit proposal: no JSON array in LLM output")
            return []
        try:
            items = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            logger.warning("edit proposal: JSON parse error: %s", exc)
            return []
        changes: List[EditChange] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            find = str(item.get("find", "")).strip()
            replace = str(item.get("replace") or "")
            if not find:
                continue
            if find not in content:
                logger.warning(
                    "edit proposal: 'find' text absent from document, skipping: %r",
                    find[:80],
                )
                continue
            changes.append(EditChange(find=find, replace=replace))
        return changes

    @staticmethod
    def _make_summary(changes: List[EditChange]) -> str:
        n = len(changes)
        if n == 0:
            return "No changes proposed"
        if n == 1:
            preview = changes[0].find[:50].replace("\n", " ")
            ellipsis = "…" if len(changes[0].find) > 50 else ""
            return f'1 change: "{preview}{ellipsis}"'
        return f"{n} changes proposed"

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def apply_proposal(self, proposal: EditProposal) -> Dict[str, Any]:
        """
        Validate, back up, write the file.

        Returns dict with keys: applied_changes (int), backup_path (str).
        Raises ValueError on safety / IO errors — caller should catch and 500.
        """
        current_dir = self.current_directory
        if not current_dir:
            raise ValueError("No directory is currently loaded")

        file_path = proposal.file_path

        # Scope guard: file must be under the indexed directory
        try:
            abs_file = os.path.abspath(file_path)
            abs_dir = os.path.abspath(current_dir)
            if not abs_file.startswith(abs_dir + os.sep) and abs_file != abs_dir:
                raise ValueError("File is outside the indexed directory")
        except Exception as exc:
            raise ValueError(f"Path validation failed: {exc}")

        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise ValueError(f"File no longer exists: {file_path}")

        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_EDIT_EXTENSIONS:
            raise ValueError(f"Unsupported file type for editing: {suffix}")

        # Timestamped backup (same directory, invisible to the user unless they look)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_path = path.with_suffix(f".{ts}.bak{suffix}")
        shutil.copy2(str(path), str(backup_path))
        logger.info("Backup created: %s", backup_path)

        try:
            if suffix == ".txt":
                applied = self._apply_txt(str(path), proposal.changes)
            else:
                applied = self._apply_docx(str(path), proposal.changes)
        except Exception as exc:
            # Restore from backup on failure
            shutil.copy2(str(backup_path), str(path))
            logger.error("Apply failed, restored from backup: %s", exc)
            raise ValueError(f"Apply failed — file restored: {exc}")

        return {"applied_changes": applied, "backup_path": str(backup_path)}

    def _apply_txt(self, file_path: str, changes: List[EditChange]) -> int:
        content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        applied = 0
        for change in changes:
            if change.find in content:
                content = content.replace(change.find, change.replace, 1)
                applied += 1
            else:
                logger.warning(
                    "_apply_txt: find text no longer present, skipping: %r", change.find[:60]
                )
        Path(file_path).write_text(content, encoding="utf-8")
        return applied

    def _apply_docx(self, file_path: str, changes: List[EditChange]) -> int:
        """
        Apply changes to a DOCX file.

        Strategy: for each paragraph (and table cell) concatenate all run texts,
        apply the replacement, then write the result back to the first run and
        blank the remaining runs.  This preserves paragraph-level formatting but
        collapses per-run formatting (bold/italic) inside changed paragraphs —
        an acceptable tradeoff for Phase 1.
        """
        from docx import Document

        doc = Document(file_path)
        remaining = list(changes)
        applied = 0

        def _try_replace_in_para(para: Any) -> None:
            nonlocal applied
            if not remaining:
                return
            para_text = para.text
            for change in list(remaining):
                if change.find not in para_text:
                    continue
                new_text = para_text.replace(change.find, change.replace, 1)
                if new_text == para_text:
                    continue
                if para.runs:
                    para.runs[0].text = new_text
                    for run in para.runs[1:]:
                        run.text = ""
                applied += 1
                remaining.remove(change)
                para_text = new_text

        for para in doc.paragraphs:
            _try_replace_in_para(para)

        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        _try_replace_in_para(para)

        doc.save(file_path)
        return applied
