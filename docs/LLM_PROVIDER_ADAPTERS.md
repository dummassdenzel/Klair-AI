# LLM Provider Adapters

Provider adapters give a **single place** for per-LLM limits and truncation. The rest of the app stays provider-agnostic.

## Why adapters?

- **No `if provider == "groq"` in callers** – Limits and truncation live in the adapter.
- **One source of truth** – Each provider has one class: `GroqAdapter`, `OllamaAdapter`, `GeminiAdapter`.
- **Easy to add providers** – Implement `LLMProviderAdapter` and register in the factory.
- **Testable** – You can inject a mock adapter with fixed limits.

## Interface (`LLMProviderAdapter`)

| Method | Purpose |
|--------|--------|
| `get_max_context_chars()` | Max RAG context length (chars). Used before building the RAG prompt. |
| `get_max_simple_prompt_chars()` | Max prompt length for classification / document listing. |
| `get_max_listing_context_chars()` | Max total context when building "list all documents" so every file fits. Used by the orchestrator. |
| `get_max_output_tokens(prompt_type)` | Max completion tokens. `prompt_type`: `classification`, `short_direct`, `document_listing`, `rag`. |
| `truncate_context(context)` | Truncate RAG context (default: by document boundary). |
| `truncate_prompt(prompt)` | Truncate simple prompt (default: by char limit). |

## Prompt types

- **classification** – One-word or short label (e.g. greeting, document_search). → 200 tokens.
- **short_direct** – Greeting or “what can you do?”. → 200 tokens.
- **document_listing** – “List all documents” with one line per file. → 2048 tokens.
- **rag** – Full RAG answer. → 8192 (or from adapter).

## Flow

1. **Startup** – `LLMService` is created with `provider="groq"` (or ollama/gemini). It calls `create_adapter_for_provider(provider, settings)` and gets the right adapter.
2. **RAG** – Before building the prompt, `context = self._adapter.truncate_context(context)`. Output token limit for Groq comes from `adapter.get_max_output_tokens("rag")`; Ollama/Gemini still use `LLM_MAX_RESPONSE_TOKENS` for now.
3. **Document listing** – Orchestrator calls `self.llm_service.get_max_listing_context_chars()` to cap total listing context, then `generate_simple(prompt, prompt_type="document_listing")` so the adapter uses 2048 output tokens.
4. **Classification / direct** – `generate_simple(prompt)` (default `prompt_type="classification"`) or `prompt_type="short_direct"`; adapter truncates prompt and sets 200 output tokens.

## Config

- **Groq** – `GROQ_MAX_CONTEXT_CHARS`, `GROQ_MAX_SIMPLE_PROMPT_CHARS`, `GROQ_MAX_LISTING_CONTEXT_CHARS` in config; `GroqAdapter` is built from these. Defaults are for the 30k TPM model (`meta-llama/llama-4-scout-17b-16e-instruct`); lower them if you use a smaller tier.
- **Ollama / Gemini** – Adapters use large defaults (no practical truncation). Output tokens for RAG still come from `LLM_MAX_RESPONSE_TOKENS` in config.

## Adding a provider

1. Add a new class in `provider_adapters.py` that implements `LLMProviderAdapter`.
2. In `create_adapter_for_provider()`, handle the new provider name and return an instance (reading config as needed).
3. In `LLMService._initialize_client()` (and the generate methods), add the branch for the new provider’s API. Limits and truncation are already handled by the adapter.

## Files

- `ai/services/document_processor/llm/provider_adapters.py` – Interface and Groq/Ollama/Gemini adapters.
- `ai/services/document_processor/llm/llm_service.py` – Uses `_adapter` for truncation and output token limits; exposes `get_max_listing_context_chars()`.
- `ai/services/document_processor/orchestrator.py` – Uses `get_max_listing_context_chars()` for listing; passes `prompt_type="document_listing"` or `"short_direct"` to `generate_simple`.
