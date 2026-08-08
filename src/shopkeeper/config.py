"""Configuration: load settings from .env (falling back to sensible defaults).

Everything the app needs to reach Postgres and Ollama lives here, so there is a
single place to look when something is misconfigured.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# .../src/shopkeeper/config.py -> project root is two parents up from the package dir.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    database_url: str
    ollama_host: str
    ollama_model: str
    web_host: str
    web_port: int
    web_token: str
    ai_provider: str      # "ollama" (local, free) | "claude" (cloud, paid)
    claude_model: str
    anthropic_api_key: str


def load_settings() -> Settings:
    """Read .env (if present) and return resolved settings."""
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        # Build from parts so a partial .env still works.
        user = os.getenv("POSTGRES_USER", "shopkeeper")
        password = os.getenv("POSTGRES_PASSWORD", "shopkeeper")
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5434")
        name = os.getenv("POSTGRES_DB", "shopkeeper")
        database_url = f"postgresql://{user}:{password}@{host}:{port}/{name}"

    return Settings(
        database_url=database_url,
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b-instruct"),
        web_host=os.getenv("WEB_HOST", "0.0.0.0"),  # LAN-reachable so the phone can connect
        web_port=int(os.getenv("WEB_PORT", "8765")),
        web_token=os.getenv("WEB_TOKEN", "").strip(),
        ai_provider=os.getenv("AI_PROVIDER", "ollama").strip().lower(),
        claude_model=os.getenv("CLAUDE_MODEL", "claude-haiku-4-5"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
    )
