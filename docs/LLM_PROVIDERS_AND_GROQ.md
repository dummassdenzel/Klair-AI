# LLM Providers and Switching to Groq

Klair AI supports three LLM backends. You switch by setting **one** environment variable: `LLM_PROVIDER`. Limits and truncation are handled by **provider adapters** (see [LLM_PROVIDER_ADAPTERS.md](LLM_PROVIDER_ADAPTERS.md)).

| Provider | Use case | Env vars |
|----------|----------|----------|
| **ollama** | Local inference, no API key | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` |
| **gemini** | Google cloud | `GEMINI_API_KEY`, `GEMINI_MODEL` |
| **groq** | Fast inference, 30k TPM default model | `GROQ_API_KEY`, `GROQ_MODEL` |

**Default Groq model:** `meta-llama/llama-4-scout-17b-16e-instruct` (30k TPM). Limits are set so we don’t over-truncate; if you switch to a lower-TPM model, set the `GROQ_MAX_*` env vars lower to avoid 413 errors.

---

## Switching to Groq (e.g. from Gemini)

1. **Get an API key**  
   Sign up at [console.groq.com](https://console.groq.com) and create an API key (free tier available).

2. **Set environment variables** (e.g. in `ai/.env`):
   ```env
   LLM_PROVIDER=groq
   GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxx
   GROQ_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
   ```
   Optional: leave `GEMINI_API_KEY` and `GEMINI_MODEL` set if you want to switch back later.

   **Defaults (30k TPM model):** `GROQ_MAX_CONTEXT_CHARS=50000`, `GROQ_MAX_SIMPLE_PROMPT_CHARS=15000`, `GROQ_MAX_LISTING_CONTEXT_CHARS=25000`. You usually don’t need to set these.

   **If you hit "Request too large" (413):** you’re likely on a lower-TPM tier. Lower the caps, e.g.:
   - `GROQ_MAX_CONTEXT_CHARS=12000`
   - `GROQ_MAX_SIMPLE_PROMPT_CHARS=4000`
   - `GROQ_MAX_LISTING_CONTEXT_CHARS=3200`

3. **Install dependency** (if not already):
   ```bash
   pip install groq
   ```

4. **Restart the app.**  
   No code changes needed; the app reads `LLM_PROVIDER` at startup.

### Groq model

- **meta-llama/llama-4-scout-17b-16e-instruct** (default) – 30k TPM; good balance of quality and capacity for document Q&A. Limits in the app are tuned for this tier.
- If you switch to another model (e.g. a 6k TPM tier), set `GROQ_MAX_CONTEXT_CHARS`, `GROQ_MAX_SIMPLE_PROMPT_CHARS`, and `GROQ_MAX_LISTING_CONTEXT_CHARS` lower to avoid 413 errors.

---

## Switching back to Gemini

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key
GEMINI_MODEL=gemini-2.5-pro
```

Restart the app.

---

## Behaviour

- **Classification** (query routing) and **chat** (RAG answers) both use the selected provider.
- **Streaming** is supported for Ollama and Groq; Gemini returns the full message in one chunk in the current implementation.
- **Token limits** are controlled by `LLM_MAX_RESPONSE_TOKENS` (default 8192) for all providers.
