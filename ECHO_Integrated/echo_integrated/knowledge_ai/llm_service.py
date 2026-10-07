"""Thin local Ollama client (standard library only) with robust JSON parsing."""

import json
import re
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from .config import Config


class LLMError(Exception):
    """Base class for model-related failures."""


class LLMUnavailableError(LLMError):
    """Ollama is not reachable, or the configured model is not installed."""


class LLMResponseError(LLMError):
    """The model answered, but the answer could not be parsed as JSON."""


def parse_json_loose(text: str) -> Any:
    """Parse JSON from model output, tolerating code fences, prose and trailing commas."""
    if not isinstance(text, str) or not text.strip():
        raise LLMResponseError("empty model response")
    candidates = [text.strip()]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.append(fenced.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for cand in candidates:
        for attempt in (cand, re.sub(r",\s*([}\]])", r"\1", cand)):
            try:
                return json.loads(attempt)
            except ValueError:
                continue
    raise LLMResponseError(f"could not parse JSON from model output: {text[:120]!r}")


class LLMService:
    """Calls a local Ollama server. In mock mode no network call is ever made."""

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or Config()
        # Bypass system/Windows proxy settings: Ollama is local.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @property
    def is_mock(self) -> bool:
        return self.config.mock_mode

    @property
    def mode(self) -> str:
        return "mock" if self.config.mock_mode else "real"

    # ---- low-level HTTP ------------------------------------------------
    def _request(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self.config.ollama_base_url.rstrip("/") + path
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        try:
            with self._opener.open(req, timeout=self.config.timeout_seconds) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise LLMUnavailableError(
                    f"Ollama returned 404 - model '{self.config.model}' may not be installed. "
                    f"Run: ollama pull {self.config.model}"
                ) from exc
            raise LLMError(f"Ollama HTTP error {exc.code}") from exc
        except (urllib.error.URLError, ConnectionError, socket.timeout, TimeoutError, OSError) as exc:
            raise LLMUnavailableError(
                f"Cannot reach Ollama at {self.config.ollama_base_url} ({exc}). "
                "Start it with 'ollama serve' or enable ECHO_MOCK_MODE=true."
            ) from exc
        try:
            parsed = json.loads(body)
        except ValueError as exc:
            raise LLMResponseError("Ollama returned a non-JSON HTTP body") from exc
        if not isinstance(parsed, dict):
            raise LLMResponseError("Ollama returned an unexpected HTTP body")
        return parsed

    # ---- public API ----------------------------------------------------
    def check_status(self) -> Dict[str, Any]:
        """Report mode / availability without raising."""
        status = {
            "mode": self.mode,
            "model": self.config.model,
            "base_url": self.config.ollama_base_url,
            "available": False,
            "detail": "",
        }
        if self.is_mock:
            status.update(available=True, detail="mock mode: no model is used")
            return status
        try:
            tags = self._request("/api/tags")
        except LLMError as exc:
            status["detail"] = str(exc)
            return status
        names = [str(m.get("name", "")) for m in tags.get("models", []) if isinstance(m, dict)]
        wanted = self.config.model
        found = any(n == wanted or n.split(":")[0] == wanted or n == wanted + ":latest" for n in names)
        status["available"] = found
        status["detail"] = "ok" if found else f"model not installed; run: ollama pull {wanted}"
        return status

    def is_available(self) -> bool:
        return bool(self.check_status()["available"])

    def generate_json(self, prompt: str, system: Optional[str] = None) -> Dict[str, Any]:
        """Ask the model for a JSON object. Retries on unparseable output.

        Raises LLMUnavailableError (server/model missing) or LLMResponseError
        (still unparseable after retries). Never call in mock mode.
        """
        if self.is_mock:
            raise LLMError("generate_json() was called in mock mode; no model is available")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {"temperature": self.config.temperature, "num_ctx": self.config.num_ctx},
        }
        last_error: Optional[LLMError] = None
        for _ in range(self.config.max_retries + 1):
            try:
                response = self._request("/api/chat", payload)
                content = (response.get("message") or {}).get("content")
                if not isinstance(content, str):
                    raise LLMResponseError("Ollama response had no message content")
                data = parse_json_loose(content)
                if not isinstance(data, dict):
                    raise LLMResponseError("model returned JSON that is not an object")
                return data
            except LLMResponseError as exc:
                last_error = exc
        raise last_error or LLMResponseError("unknown model failure")
