"""Configuration for knowledge_ai.

Values come from (lowest to highest priority): defaults, a .env file, real
environment variables, explicit keyword overrides. All variables use the
``ECHO_`` prefix, e.g. ``ECHO_MODEL=gemma3:4b``.
"""

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Dict, Mapping, Optional
from urllib.parse import urlparse

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class ConfigError(ValueError):
    """Raised when a configuration value is invalid."""


@dataclass
class Config:
    ollama_base_url: str = "http://localhost:11434"
    model: str = "gemma3:4b"
    timeout_seconds: float = 120.0
    temperature: float = 0.0
    num_ctx: int = 4096
    max_retries: int = 2  # extra attempts when the model returns unparseable JSON
    mock_mode: bool = False  # True = rule-based mock, no Ollama needed
    allow_non_local: bool = False  # keep inference local unless explicitly allowed
    require_evidence: bool = True  # drop relationships without verifiable evidence
    chunk_max_chars: int = 1500
    top_k: int = 8  # max entities used as retrieval seeds
    max_decisions: int = 3  # max decision trails per answer
    min_coverage: float = 0.6  # share of key question terms that must be found

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> "Config":
        parsed = urlparse(self.ollama_base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ConfigError(f"Invalid ollama_base_url: {self.ollama_base_url!r}")
        if not self.allow_non_local and parsed.hostname.lower() not in _LOCAL_HOSTS:
            raise ConfigError(
                "ollama_base_url must point to this machine (localhost/127.0.0.1) "
                "to keep inference local. Set ECHO_ALLOW_NON_LOCAL=true to override."
            )
        if not str(self.model).strip():
            raise ConfigError("model must not be empty")
        if self.timeout_seconds <= 0:
            raise ConfigError("timeout_seconds must be > 0")
        if self.max_retries < 0:
            raise ConfigError("max_retries must be >= 0")
        if self.chunk_max_chars < 200:
            raise ConfigError("chunk_max_chars must be >= 200")
        if self.top_k < 1 or self.max_decisions < 1:
            raise ConfigError("top_k and max_decisions must be >= 1")
        if not 0.0 <= self.min_coverage <= 1.0:
            raise ConfigError("min_coverage must be between 0 and 1")
        return self


def _parse_bool(value: str, key: str) -> bool:
    v = value.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{key} must be true/false, got {value!r}")


def read_env_file(path: str) -> Dict[str, str]:
    """Tiny .env parser (KEY=VALUE lines, # comments). Missing file -> {}."""
    values: Dict[str, str] = {}
    p = Path(path)
    if not p.is_file():
        return values
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        elif " #" in val:
            val = val.split(" #", 1)[0].strip()
        values[key] = val
    return values


def load_config(
    env_file: Optional[str] = ".env",
    environ: Optional[Mapping[str, str]] = None,
    **overrides,
) -> Config:
    """Build a Config from .env + environment variables + overrides."""
    env: Dict[str, str] = dict(read_env_file(env_file)) if env_file else {}
    env.update(os.environ if environ is None else environ)
    defaults = Config()
    kwargs = {}
    for f in fields(Config):
        key = "ECHO_" + f.name.upper()
        raw = env.get(key)
        if raw is None or raw.strip() == "":
            continue
        kind = type(getattr(defaults, f.name))
        try:
            if kind is bool:
                kwargs[f.name] = _parse_bool(raw, key)
            elif kind is int:
                kwargs[f.name] = int(raw)
            elif kind is float:
                kwargs[f.name] = float(raw)
            else:
                kwargs[f.name] = raw.strip()
        except ValueError as exc:
            raise ConfigError(f"{key} has an invalid value {raw!r}") from exc
    kwargs.update(overrides)
    return Config(**kwargs)
