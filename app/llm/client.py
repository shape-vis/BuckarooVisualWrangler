"""Abstract LLM client + Ollama implementation.

Scaffold only — the OllamaClient hits a local Ollama HTTP API. The abstract
class is so we can swap in a cloud Qwen client (or a fake for tests) without
touching the orchestrator.
"""
import json
import os
from abc import ABC, abstractmethod
from typing import Any

import requests


class LLMClient(ABC):
    @abstractmethod
    def chat_json(self, system: str, user: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a structured chat request, return the model's JSON response as a dict.

        `schema` is an advisory JSON Schema the implementation may pass to the
        model (Ollama supports `format=<schema>` to force valid JSON output).
        """
        ...


class OllamaClient(LLMClient):
    def __init__(self, model: str | None = None, host: str | None = None, timeout: int | None = None):
        self.model = model or os.environ.get("OLLAMA_MODEL", "qwen3.6:latest")
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.timeout = timeout if timeout is not None else int(os.environ.get("OLLAMA_TIMEOUT", "600"))

    def chat_json(self, system: str, user: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            # Ollama returns valid JSON when format is "json" or a JSON schema.
            # Passing the schema (not just "json") makes the model honor field names.
            # NOTE: previously passed the full JSON schema here; that forces
            # token-by-token validation in Ollama and is dramatically slower.
            # We rely on the prompt to describe the shape and just demand JSON.
            "format": "json",
            # Disable reasoning-model "thinking" traces — they balloon latency
            # on qwen3.x without improving structured-output quality.
            "think": False,
        }
        import time
        t0 = time.time()
        resp = requests.post(f"{self.host}/api/chat", json=payload, timeout=self.timeout)
        resp.raise_for_status()
        body = resp.json()
        content = body.get("message", {}).get("content", "")
        print(
            f"[llm] {self.model} {time.time()-t0:.1f}s "
            f"prompt_tokens={body.get('prompt_eval_count')} "
            f"eval_tokens={body.get('eval_count')}"
        )
        return json.loads(content)


class GroqClient(LLMClient):
    """OpenAI-compatible client pointed at Groq's free, fast inference API.

    Requires GROQ_API_KEY in the environment. Pick a model via GROQ_MODEL
    (default: llama-3.3-70b-versatile — free tier, fast, strong JSON).
    """

    def __init__(self, model: str | None = None, api_key: str | None = None, timeout: int | None = None):
        self.model = model or os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        self.timeout = timeout if timeout is not None else int(os.environ.get("GROQ_TIMEOUT", "60"))

    def chat_json(self, system: str, user: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        import time
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        t0 = time.time()
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        print(
            f"[llm] groq/{self.model} {time.time()-t0:.1f}s "
            f"prompt_tokens={usage.get('prompt_tokens')} "
            f"completion_tokens={usage.get('completion_tokens')}"
        )
        return json.loads(content)


def get_default_client() -> LLMClient:
    """Pick provider via LLM_PROVIDER env var: 'groq' or 'ollama' (default)."""
    provider = os.environ.get("LLM_PROVIDER", "ollama").lower()
    if provider == "groq":
        return GroqClient()
    return OllamaClient()
