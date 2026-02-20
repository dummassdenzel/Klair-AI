"""
Provider adapters: per-LLM limits and truncation.
Single source of truth for input/output limits; no provider-specific logic in callers.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)

# Prompt types used when requesting output token limits
PROMPT_TYPE_CLASSIFICATION = "classification"
PROMPT_TYPE_SHORT_DIRECT = "short_direct"
PROMPT_TYPE_DOCUMENT_LISTING = "document_listing"
PROMPT_TYPE_RAG = "rag"

# Document boundary used in RAG context (must match orchestrator)
DOC_CONTEXT_SEP = "\n\n---\n\n"


class LLMProviderAdapter(ABC):
    """Adapter for provider-specific limits and truncation. Implement per provider."""

    @abstractmethod
    def get_max_context_chars(self) -> int:
        """Max RAG context length (chars) before truncation. For providers with strict input limits."""
        pass

    @abstractmethod
    def get_max_simple_prompt_chars(self) -> int:
        """Max prompt length for simple (non-RAG) calls: classification, document listing."""
        pass

    @abstractmethod
    def get_max_listing_context_chars(self) -> int:
        """Max total context when building document listing so all files fit in one prompt. Used by orchestrator."""
        pass

    @abstractmethod
    def get_max_output_tokens(self, prompt_type: str) -> int:
        """Max completion tokens for this prompt type. Types: classification, short_direct, document_listing, rag."""
        pass

    def truncate_context(self, context: str) -> str:
        """Truncate RAG context to provider limit. Default: by document boundary."""
        max_chars = self.get_max_context_chars()
        if len(context) <= max_chars:
            return context
        parts = [p.strip() for p in context.split(DOC_CONTEXT_SEP) if p.strip()]
        out = []
        for part in parts:
            candidate = (DOC_CONTEXT_SEP.join(out) + DOC_CONTEXT_SEP + part) if out else part
            if len(candidate) <= max_chars:
                out.append(part)
            else:
                break
        if not out and parts:
            out = [parts[0][:max_chars].rstrip()]
        result = DOC_CONTEXT_SEP.join(out)
        if len(result) < len(context):
            result += "\n\n[Additional documents omitted for length.]"
        return result

    def truncate_prompt(self, prompt: str) -> str:
        """Truncate simple prompt to provider limit. Default: raw char cut."""
        max_chars = self.get_max_simple_prompt_chars()
        if len(prompt) <= max_chars:
            return prompt
        return prompt[:max_chars].rstrip() + "\n\n[Truncated.]"


class GroqAdapter(LLMProviderAdapter):
    """Groq: config-driven caps. Defaults tuned for 30k TPM (e.g. llama-4-scout); lower if using a smaller tier."""

    def __init__(self, max_context_chars: int = 50000, max_simple_prompt_chars: int = 15000, listing_context_chars: int = 25000):
        self._max_context = max_context_chars
        self._max_simple = max_simple_prompt_chars
        self._listing = listing_context_chars

    def get_max_context_chars(self) -> int:
        return self._max_context

    def get_max_simple_prompt_chars(self) -> int:
        return self._max_simple

    def get_max_listing_context_chars(self) -> int:
        return self._listing

    def get_max_output_tokens(self, prompt_type: str) -> int:
        if prompt_type == PROMPT_TYPE_DOCUMENT_LISTING:
            return 2048
        if prompt_type in (PROMPT_TYPE_CLASSIFICATION, PROMPT_TYPE_SHORT_DIRECT):
            return 200
        return 8192  # rag


class OllamaAdapter(LLMProviderAdapter):
    """Ollama: no practical input limit in normal use; high defaults."""

    def get_max_context_chars(self) -> int:
        return 500_000

    def get_max_simple_prompt_chars(self) -> int:
        return 100_000

    def get_max_listing_context_chars(self) -> int:
        return 50_000

    def get_max_output_tokens(self, prompt_type: str) -> int:
        if prompt_type == PROMPT_TYPE_DOCUMENT_LISTING:
            return 2048
        if prompt_type in (PROMPT_TYPE_CLASSIFICATION, PROMPT_TYPE_SHORT_DIRECT):
            return 200
        return 8192


class GeminiAdapter(LLMProviderAdapter):
    """Gemini: high limits; no truncation needed in practice."""

    def get_max_context_chars(self) -> int:
        return 500_000

    def get_max_simple_prompt_chars(self) -> int:
        return 100_000

    def get_max_listing_context_chars(self) -> int:
        return 50_000

    def get_max_output_tokens(self, prompt_type: str) -> int:
        if prompt_type == PROMPT_TYPE_DOCUMENT_LISTING:
            return 2048
        if prompt_type in (PROMPT_TYPE_CLASSIFICATION, PROMPT_TYPE_SHORT_DIRECT):
            return 200
        return 8192


def create_adapter_for_provider(provider: str, settings: Optional[object] = None) -> LLMProviderAdapter:
    """Factory: returns the adapter for the given provider. Reads config from settings if present."""
    provider = (provider or "ollama").lower().strip()
    if provider == "groq" and settings:
        max_ctx = getattr(settings, "GROQ_MAX_CONTEXT_CHARS", 50000)
        max_simple = getattr(settings, "GROQ_MAX_SIMPLE_PROMPT_CHARS", 15000)
        listing = getattr(settings, "GROQ_MAX_LISTING_CONTEXT_CHARS", 25000)
        return GroqAdapter(max_context_chars=max_ctx, max_simple_prompt_chars=max_simple, listing_context_chars=listing)
    if provider == "groq":
        return GroqAdapter()
    if provider == "gemini":
        return GeminiAdapter()
    return OllamaAdapter()
