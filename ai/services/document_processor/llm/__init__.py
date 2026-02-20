"""LLM services for text generation. Uses provider adapters for limits and truncation."""

from .llm_service import LLMService
from .provider_adapters import (
    LLMProviderAdapter,
    create_adapter_for_provider,
    PROMPT_TYPE_CLASSIFICATION,
    PROMPT_TYPE_DOCUMENT_LISTING,
    PROMPT_TYPE_RAG,
    PROMPT_TYPE_SHORT_DIRECT,
)

__all__ = [
    "LLMService",
    "LLMProviderAdapter",
    "create_adapter_for_provider",
    "PROMPT_TYPE_CLASSIFICATION",
    "PROMPT_TYPE_DOCUMENT_LISTING",
    "PROMPT_TYPE_RAG",
    "PROMPT_TYPE_SHORT_DIRECT",
]

