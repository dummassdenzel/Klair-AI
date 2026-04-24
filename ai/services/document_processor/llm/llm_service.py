"""
LLMService — thin wrapper around LiteLLM for multi-provider LLM access.

LiteLLM translates a single acompletion() call to any provider; no more
per-provider if/elif chains. Provider model strings:
  groq   → "groq/<model>"
  gemini → "gemini/<model>"
  ollama → "ollama_chat/<model>"  (Ollama OpenAI-compat endpoint)

The provider_adapters module is kept for per-provider token limits and
context truncation — concerns that exist regardless of HTTP client.
"""

import asyncio
import logging
import random
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

from config import settings
from .provider_adapters import (
    create_adapter_for_provider,
    LLMProviderAdapter,
    PROMPT_TYPE_CLASSIFICATION,
    PROMPT_TYPE_SHORT_DIRECT,
    PROMPT_TYPE_DOCUMENT_LISTING,
    PROMPT_TYPE_RAG,
)

logger = logging.getLogger(__name__)


class LLMService:
    """Multi-provider LLM service backed by LiteLLM."""

    def __init__(
        self,
        ollama_base_url: str,
        ollama_model: str,
        gemini_api_key: Optional[str] = None,
        gemini_model: str = "gemini-2.5-pro",
        groq_api_key: Optional[str] = None,
        groq_model: str = "meta-llama/llama-4-scout-17b-16e-instruct",
        openai_api_key: Optional[str] = None,
        openai_model: str = "gpt-4o-mini",
        anthropic_api_key: Optional[str] = None,
        anthropic_model: str = "claude-sonnet-4-6",
        xai_api_key: Optional[str] = None,
        xai_model: str = "grok-3-mini",
        provider: str = "ollama",
        adapter: Optional[LLMProviderAdapter] = None,
    ):
        self.base_url = ollama_base_url
        self.model = ollama_model
        self.gemini_api_key = gemini_api_key or ""
        self.gemini_model = gemini_model
        self.groq_api_key = groq_api_key or ""
        self.groq_model = groq_model
        self.openai_api_key = openai_api_key or ""
        self.openai_model = openai_model
        self.anthropic_api_key = anthropic_api_key or ""
        self.anthropic_model = anthropic_model
        self.xai_api_key = xai_api_key or ""
        self.xai_model = xai_model
        self.provider = provider.lower().strip()
        self._adapter: LLMProviderAdapter = adapter or create_adapter_for_provider(self.provider, settings)
        self._token_usage: Dict[str, int] = {"prompt": 0, "completion": 0, "total": 0}
        logger.info("LLMService initialized with provider: %s", self.provider)

    # ── Retry helper ─────────────────────────────────────────────────────────

    async def _with_retry(self, coro_factory: Callable, label: str = "") -> Any:
        """
        Execute `coro_factory()` and retry up to 3 times on 429 rate-limit errors
        using exponential backoff (1 s → 2 s → 4 s + up to 0.5 s jitter).
        All other exceptions propagate immediately.
        """
        delays = [1.0, 2.0, 4.0]
        for attempt in range(len(delays) + 1):
            try:
                return await coro_factory()
            except Exception as exc:
                s = str(exc).lower()
                is_rate_limit = (
                    "ratelimiterror" in type(exc).__name__.lower()
                    or "429" in s
                    or "rate limit" in s
                    or "too many requests" in s
                )
                if not is_rate_limit or attempt >= len(delays):
                    raise
                delay = delays[attempt] + random.uniform(0, 0.5)
                logger.warning(
                    "LLM rate limited (429)%s — retrying in %.1fs (attempt %d/3)",
                    f" [{label}]" if label else "",
                    delay,
                    attempt + 1,
                )
                await asyncio.sleep(delay)

    # ── Provider helpers ──────────────────────────────────────────────────────

    def _litellm_model(self) -> str:
        if self.provider == "groq":
            return f"groq/{self.groq_model}"
        if self.provider == "gemini":
            return f"gemini/{self.gemini_model}"
        if self.provider == "openai":
            return f"openai/{self.openai_model}"
        if self.provider == "anthropic":
            return f"anthropic/{self.anthropic_model}"
        if self.provider == "xai":
            return f"xai/{self.xai_model}"
        return f"ollama_chat/{self.model}"

    def _api_key(self) -> Optional[str]:
        if self.provider == "groq":
            return self.groq_api_key or None
        if self.provider == "gemini":
            return self.gemini_api_key or None
        if self.provider == "openai":
            return self.openai_api_key or None
        if self.provider == "anthropic":
            return self.anthropic_api_key or None
        if self.provider == "xai":
            return self.xai_api_key or None
        return None

    def _extra_kwargs(self) -> Dict[str, Any]:
        if self.provider == "ollama":
            return {"api_base": self.base_url}
        return {}

    def _record_usage(self, response: Any, label: str = "") -> None:
        try:
            usage = getattr(response, "usage", None)
            p = int(getattr(usage, "prompt_tokens", 0) or 0)
            c = int(getattr(usage, "completion_tokens", 0) or 0)
        except Exception:
            p = c = 0
        t = p + c
        self._token_usage["prompt"] += p
        self._token_usage["completion"] += c
        self._token_usage["total"] += t
        if t:
            logger.info(
                "LLM token usage%s: prompt=%s, completion=%s, total=%s (cumulative=%s)",
                f" ({label})" if label else "",
                p, c, t, self._token_usage["total"],
            )

    # ── Public interface ──────────────────────────────────────────────────────

    def get_max_listing_context_chars(self) -> int:
        return self._adapter.get_max_listing_context_chars()

    def supports_tool_calling(self) -> bool:
        return self._adapter.supports_tool_calling()

    def get_token_usage(self) -> Dict[str, int]:
        return dict(self._token_usage)

    def switch_provider(
        self,
        provider: str,
        *,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        provider = provider.lower().strip()
        _VALID = {"ollama", "gemini", "groq", "openai", "anthropic", "xai"}
        if provider not in _VALID:
            raise ValueError(f"Unknown provider: {provider!r}. Must be one of {sorted(_VALID)}.")
        if provider == "ollama":
            if model:
                self.model = model
            if base_url:
                self.base_url = base_url
        elif provider == "gemini":
            if model:
                self.gemini_model = model
            if api_key:
                self.gemini_api_key = api_key
        elif provider == "groq":
            if model:
                self.groq_model = model
            if api_key:
                self.groq_api_key = api_key
        elif provider == "openai":
            if model:
                self.openai_model = model
            if api_key:
                self.openai_api_key = api_key
        elif provider == "anthropic":
            if model:
                self.anthropic_model = model
            if api_key:
                self.anthropic_api_key = api_key
        elif provider == "xai":
            if model:
                self.xai_model = model
            if api_key:
                self.xai_api_key = api_key
        self.provider = provider
        self._adapter = create_adapter_for_provider(self.provider, settings)
        logger.info("LLM provider switched to: %s", self.provider)

    def update_model(self, new_model: str):
        self.model = new_model

    def update_base_url(self, new_url: str):
        self.base_url = new_url

    # ── Prompt construction ───────────────────────────────────────────────────

    def _build_messages(self, query: str, context: str, conversation_history: list) -> List[Dict[str, Any]]:
        """Build structured messages list for LiteLLM (fixes F5: single-blob prompt)."""
        system_parts = [
            "Use the document context below when it is relevant to the user's question. "
            "Cite sources as [Document: filename].\n\n"
            "Rules:\n"
            "- Use the documents when they help answer the question. If asked for an overview, "
            "summarize what the context says and what the documents are about.\n"
            "- If the question is general conversation (e.g. greetings), respond normally; "
            "do not force document citations.\n"
            "- Combine information from multiple chunks of the same document into one answer. "
            "When asked for a list, include every matching item from the context.\n"
            "- Only say 'the context doesn't contain the answer' when the user clearly asked a "
            "factual question that is not in the context.\n"
            "- Use specific details and quotes when relevant."
        ]
        history_messages: List[Dict[str, Any]] = []

        for msg in (conversation_history or []):
            role = msg.get("role", "user")
            content = (msg.get("content") or "").strip()
            if not content:
                continue
            if role == "system":
                system_parts.append(f"\n[Earlier conversation summary]:\n{content}")
            elif role in ("user", "assistant"):
                history_messages.append({"role": role, "content": content})

        messages: List[Dict[str, Any]] = [{"role": "system", "content": "\n".join(system_parts)}]
        messages.extend(history_messages)
        messages.append({"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"})
        return messages

    # ── Core generation ───────────────────────────────────────────────────────

    async def generate_simple(
        self,
        prompt: str,
        prompt_type: str = PROMPT_TYPE_CLASSIFICATION,
        max_completion_tokens: Optional[int] = None,
    ) -> str:
        import litellm
        prompt = self._adapter.truncate_prompt(prompt)
        out_tokens = (
            max_completion_tokens
            if max_completion_tokens is not None
            else self._adapter.get_max_output_tokens(prompt_type)
        )
        try:
            response = await self._with_retry(
                lambda: litellm.acompletion(
                    model=self._litellm_model(),
                    messages=[{"role": "user", "content": prompt}],
                    api_key=self._api_key(),
                    temperature=0.1,
                    max_tokens=out_tokens,
                    **self._extra_kwargs(),
                ),
                label="generate_simple",
            )
            self._record_usage(response, label=f"generate_simple_{self.provider}")
            return (response.choices[0].message.content or "").strip() or "I couldn't generate a response."
        except Exception as e:
            logger.error("generate_simple failed: %s", e)
            return "I couldn't generate a response due to an error."

    async def generate_response(
        self, query: str, context: str, conversation_history: list = None
    ) -> str:
        import litellm
        context = self._adapter.truncate_context(context)
        messages = self._build_messages(query, context, conversation_history or [])
        max_tokens = getattr(settings, "LLM_MAX_RESPONSE_TOKENS", 8192)
        try:
            response = await self._with_retry(
                lambda: litellm.acompletion(
                    model=self._litellm_model(),
                    messages=messages,
                    api_key=self._api_key(),
                    temperature=getattr(settings, "LLM_TEMPERATURE", 0.1),
                    max_tokens=max_tokens,
                    **self._extra_kwargs(),
                ),
                label="generate_response",
            )
            self._record_usage(response, label=f"generate_response_{self.provider}")
            return (response.choices[0].message.content or "").strip() or "I couldn't generate a response."
        except Exception as e:
            logger.error("generate_response failed: %s", e)
            return "I couldn't generate a response due to an error."

    async def generate_response_stream(
        self, query: str, context: str, conversation_history: list = None
    ) -> AsyncIterator[str]:
        import litellm
        context = self._adapter.truncate_context(context)
        messages = self._build_messages(query, context, conversation_history or [])
        max_tokens = getattr(settings, "LLM_MAX_RESPONSE_TOKENS", 8192)
        try:
            stream = await self._with_retry(
                lambda: litellm.acompletion(
                    model=self._litellm_model(),
                    messages=messages,
                    api_key=self._api_key(),
                    temperature=getattr(settings, "LLM_TEMPERATURE", 0.1),
                    max_tokens=max_tokens,
                    stream=True,
                    **self._extra_kwargs(),
                ),
                label="generate_response_stream",
            )
            async for chunk in stream:
                delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                if delta:
                    yield delta
        except Exception as e:
            logger.error("generate_response_stream failed: %s", e)
            yield "I couldn't generate a response due to an error."

    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int = 4096,
    ) -> Tuple[Optional[str], Optional[List[Dict[str, Any]]]]:
        import litellm
        try:
            response = await self._with_retry(
                lambda: litellm.acompletion(
                    model=self._litellm_model(),
                    messages=messages,
                    api_key=self._api_key(),
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.1,
                    max_tokens=max_tokens,
                    **self._extra_kwargs(),
                ),
                label="chat_with_tools",
            )
            self._record_usage(response, label=f"chat_with_tools_{self.provider}")
            msg = response.choices[0].message if response.choices else None
            if not msg:
                return "I couldn't generate a response.", None
            content = (getattr(msg, "content", None) or "").strip() or None
            raw_tool_calls = getattr(msg, "tool_calls", None) or []
            tool_calls = []
            for tc in raw_tool_calls:
                if not getattr(tc, "id", None) or not getattr(tc, "function", None):
                    continue
                fn = tc.function
                tool_calls.append({
                    "id": tc.id,
                    "type": getattr(tc, "type", "function"),
                    "function": {
                        "name": getattr(fn, "name", ""),
                        "arguments": getattr(fn, "arguments", "") or "{}",
                    },
                })
            return content, tool_calls if tool_calls else None
        except Exception as e:
            err_str = str(e)
            if "tool_use_failed" in err_str.lower():
                # Groq rejected the model output because it wrote plain text instead
                # of a tool call. The error payload contains `failed_generation` —
                # the model's actual attempted answer. Extract and return it directly
                # so the user still gets a useful response without an extra API call.
                failed_text = self._extract_failed_generation(err_str)
                if failed_text and len(failed_text) > 20 and not self._looks_like_tool_call(failed_text):
                    logger.info(
                        "chat_with_tools: tool_use_failed — returning failed_generation text (%d chars)",
                        len(failed_text),
                    )
                    return failed_text, None
                # failed_generation was empty, too short, or contains tool call JSON — fall back
                logger.info("chat_with_tools: tool_use_failed with no usable text; retrying without tools")
                try:
                    content = await self._chat_messages_no_tools(messages, max_tokens)
                    return (content or "I couldn't generate a response.", None)
                except Exception as retry_e:
                    logger.warning("Fallback chat without tools failed: %s", retry_e)
            logger.error("chat_with_tools failed: %s", e)
            return "I couldn't generate a response due to an error.", None

    @staticmethod
    def _extract_failed_generation(err_str: str) -> str:
        """Parse failed_generation text from a Groq tool_use_failed error string."""
        import json, re
        # The error string typically contains the raw JSON payload somewhere.
        # Try to find and parse it.
        json_match = re.search(r'\{.*"failed_generation".*\}', err_str, re.DOTALL)
        if json_match:
            try:
                payload = json.loads(json_match.group(0))
                text = (
                    payload.get("error", {}).get("failed_generation")
                    or payload.get("failed_generation")
                    or ""
                )
                return text.strip()
            except (json.JSONDecodeError, AttributeError):
                pass
        # Fallback: simple substring extraction
        marker = '"failed_generation":'
        idx = err_str.find(marker)
        if idx != -1:
            after = err_str[idx + len(marker):].strip()
            if after.startswith('"'):
                end = after.find('"}')
                if end != -1:
                    return after[1:end].replace("\\n", "\n").strip()
        return ""

    @staticmethod
    def _looks_like_tool_call(text: str) -> bool:
        """Return True if the text appears to be a tool call schema rather than a user-facing answer."""
        import re
        return bool(re.search(r'"name"\s*:\s*"(?:search_|list_|summarize_|propose_)', text))

    async def _chat_messages_no_tools(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int = 4096,
    ) -> Optional[str]:
        import litellm
        # Replace the system message with a plain instruction so the model doesn't
        # try to write tool call JSON when no tools are available via the API.
        clean_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                clean_messages.append({
                    "role": "system",
                    "content": (
                        "You are a helpful assistant. Answer the user's question directly "
                        "using only the information already provided in this conversation. "
                        "Do not write JSON, tool calls, or code blocks. Just answer in plain text."
                    ),
                })
            else:
                clean_messages.append(msg)
        response = await self._with_retry(
            lambda: litellm.acompletion(
                model=self._litellm_model(),
                messages=clean_messages,
                api_key=self._api_key(),
                temperature=0.1,
                max_tokens=max_tokens,
                **self._extra_kwargs(),
            ),
            label="chat_no_tools",
        )
        self._record_usage(response, label=f"_chat_no_tools_{self.provider}")
        msg = response.choices[0].message if response.choices else None
        return (getattr(msg, "content", None) or "").strip() or None

    async def chat_messages_stream(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        import litellm
        try:
            stream = await self._with_retry(
                lambda: litellm.acompletion(
                    model=self._litellm_model(),
                    messages=messages,
                    api_key=self._api_key(),
                    temperature=0.1,
                    max_tokens=max_tokens,
                    stream=True,
                    **self._extra_kwargs(),
                ),
                label="chat_messages_stream",
            )
            async for chunk in stream:
                delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                if delta:
                    yield delta
        except Exception as e:
            logger.error("chat_messages_stream failed: %s", e)
            yield "I couldn't generate a response due to an error."

    async def cleanup(self):
        pass  # LiteLLM manages its own connections

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()
