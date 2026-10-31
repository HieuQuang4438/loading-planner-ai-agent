"""The one way the code calls a model: structured output into a Pydantic model, temperature 0,
timeout, retries with backoff, and one log line per call (model, prompt name, key number, tokens, latency). Several
API keys (`GOOGLE_API_KEY`, `GOOGLE_API_KEY_1`, `GOOGLE_API_KEY_2`, ...) take turns, one per call; a retry goes to the
next key. A key's value is never logged. Nothing else imports the vendor SDK.

`converse` is the chat: function calling with the loop run here, not by the SDK, so every tool call goes through
the caller's `call` and is logged; the model's own turns are sent back as it gave them (Gemini needs them whole)."""
from __future__ import annotations

import logging
import itertools
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, TypeVar

from pydantic import BaseModel

log = logging.getLogger(__name__)

# Override with GEMINI_MODEL. Checked 2026-10-24 on the probe documents: gemini-2.5-flash is gone for new keys (404),
# gemini-3.8-flash timed out (504) even on one small sheet, gemini-3.5-flash / gemini-flash-latest were overloaded (503);
# gemini-3.1-flash-lite answered in 4-23 s per document and read the probe as the hand-written answer does.
DEFAULT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_THINKING = "default"  # GEMINI_THINKING: minimal, low, medium, high, or default (the model's own)
PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
TIMEOUT_S = 120.0
RETRIES = 5  # 503 and 429 come in bursts: a backoff of 2 + 4 + 8 + 16 s rides most of one out
# An overloaded model or a spent quota: the user is told to try again later, the raw answer goes to the log only.
BUSY = re.compile(r"(503|429)|UNAVAILABLE|RESOURCE_EXHAUSTED|high demand|overloaded", re.IGNORECASE)
M = TypeVar("M", bound=BaseModel)


def api_keys(env: Mapping[str, str] = os.environ) -> list[str]:
    """The API keys set: `GOOGLE_API_KEY`, then `GOOGLE_API_KEY_<n>` by n; empty and repeated ones left out."""
    numbered = sorted((int(m.group(1)), v) for k, v in env.items() if (m := re.fullmatch(r"GOOGLE_API_KEY_(\d+)", k)))
    keys = [env.get("GOOGLE_API_KEY", "")] + [v for _, v in numbered]
    return list(dict.fromkeys(k.strip() for k in keys if k and k.strip()))


def load_env(path: str | Path = ".env") -> None:
    """Read `.env` into the environment (variables already set win). Called once by each entry point, not here."""
    from dotenv import load_dotenv

    load_dotenv(path, override=False)


def prompt(name: str) -> str:
    """The text of `src/prompts/<name>.md`."""
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


@dataclass(frozen=True)
class Part:
    """One piece of a request: text, or a file's bytes with its MIME type."""

    text: str | None = None
    data: bytes | None = None
    mime: str | None = None


@dataclass(frozen=True)
class Tool:
    """A function the chat model may call: its name, what it does, and its parameters as JSON schema."""

    name: str
    description: str
    parameters: dict[str, Any]


class LLMError(RuntimeError):
    pass


def failure(model: str, exc: Exception) -> str:
    """What a failed call says to the user: busy is a sentence in Vietnamese, anything else the first 200 characters."""
    if BUSY.search(str(exc)):
        return "Gemini đang quá tải, thử lại sau ít phút"
    return f"gọi {model} lỗi: {str(exc)[:200]}"


class ChatLLM(Protocol):
    def converse(self, system: str, history: list[tuple[str, str]], tools: list[Tool],
                 call: Callable[[str, dict[str, Any]], dict[str, Any]], max_steps: int) -> str:
        """The model's reply to `history` ((role, text), role "user" or "model", the last one the user's), calling
        `tools` through `call` as often as it asks, at most `max_steps` model calls; LLMError when it fails."""
        ...


class LLM(Protocol):
    def generate(self, name: str, parts: list[Part], schema: type[M]) -> M:
        """The model's answer to the prompt `name` and `parts`, parsed into `schema`; LLMError when it fails."""
        ...


class Gemini:
    """Gemini through the `google-genai` SDK. The keys and `GEMINI_MODEL` are read once, here."""

    def __init__(self, model: str | None = None, keys: list[str] | None = None, timeout_s: float = TIMEOUT_S,
                 retries: int = RETRIES) -> None:
        from google import genai
        from google.genai import types

        keys = keys or api_keys()
        if not keys:
            raise LLMError("thiếu GOOGLE_API_KEY (hoặc GOOGLE_API_KEY_1, GOOGLE_API_KEY_2...)")
        self.model = model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
        self.thinking = os.environ.get("GEMINI_THINKING") or DEFAULT_THINKING
        self.retries = retries
        self._types = types
        options = types.HttpOptions(timeout=int(timeout_s * 1000))
        self._clients = [genai.Client(api_key=k, http_options=options) for k in keys]
        self._turn = itertools.cycle(range(len(self._clients)))
        self._lock = threading.Lock()

    def _next(self) -> int:
        with self._lock:
            return next(self._turn)

    def _send(self, name: str, contents: list[Any], config: Any) -> Any:
        """One model call with retries, each on the next key; the SDK's response."""
        for attempt in range(1, self.retries + 1):
            key = self._next()  # a retry goes to the next key: a quota error on one key does not stop the call
            start = time.monotonic()
            try:
                response = self._clients[key].models.generate_content(model=self.model, contents=contents, config=config)
            except Exception as exc:  # noqa: BLE001 - every SDK or network failure is retried, then reported
                log.warning("llm call failed: model=%s prompt=%s key=%d attempt=%d error=%s", self.model, name,
                            key + 1, attempt, exc)
                if attempt == self.retries:
                    raise LLMError(failure(self.model, exc)) from exc
                time.sleep(2 ** attempt)
                continue
            usage = response.usage_metadata
            log.info("llm call: model=%s prompt=%s key=%d in=%s out=%s latency=%.2fs", self.model, name, key + 1,
                     getattr(usage, "prompt_token_count", None), getattr(usage, "candidates_token_count", None),
                     time.monotonic() - start)
            return response
        raise LLMError("unreachable")

    def converse(self, system: str, history: list[tuple[str, str]], tools: list[Tool],
                 call: Callable[[str, dict[str, Any]], dict[str, Any]], max_steps: int = 8) -> str:
        types = self._types
        contents: list[Any] = [types.Content(role=role, parts=[types.Part.from_text(text=text)]) for role, text in history]
        declarations = [types.FunctionDeclaration(name=t.name, description=t.description,
                                                  parameters_json_schema=t.parameters) for t in tools]
        thinking = None if self.thinking == "default" else types.ThinkingConfig(thinking_level=self.thinking.upper())
        config = types.GenerateContentConfig(
            temperature=0, system_instruction=system, tools=[types.Tool(function_declarations=declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True), thinking_config=thinking)
        for _ in range(max_steps):
            response = self._send("chat", contents, config)
            calls = response.function_calls or []
            if not calls:
                return response.text or ""
            contents.append(response.candidates[0].content)
            answers = []
            for fc in calls:
                log.info("tool call: %s %s", fc.name, dict(fc.args or {}))
                answers.append(types.Part.from_function_response(name=fc.name, response=call(fc.name, dict(fc.args or {}))))
            contents.append(types.Content(role="user", parts=answers))
        raise LLMError(f"mô hình gọi công cụ quá {max_steps} lần trong một lượt")

    def generate(self, name: str, parts: list[Part], schema: type[M]) -> M:
        types = self._types
        contents = []  # the rules go in the system instruction, apart from the document they are applied to
        for p in parts:
            contents.append(types.Part.from_bytes(data=p.data, mime_type=p.mime) if p.data is not None
                            else types.Part.from_text(text=p.text or ""))
        thinking = None if self.thinking == "default" else types.ThinkingConfig(thinking_level=self.thinking.upper())
        config = types.GenerateContentConfig(temperature=0, system_instruction=prompt(name),
                                             response_mime_type="application/json", response_schema=schema,
                                             thinking_config=thinking)
        for attempt in range(1, self.retries + 1):
            response = self._send(name, contents, config)
            parsed = response.parsed
            if isinstance(parsed, schema):
                return parsed
            try:
                return schema.model_validate_json(response.text or "")
            except ValueError as exc:
                if attempt == self.retries:
                    raise LLMError(f"{self.model} trả về không đúng schema: {exc}") from exc
        raise LLMError("unreachable")
