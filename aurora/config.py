"""Configuração local; nunca imprime ou persiste credenciais."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    google_api_key: str = field(repr=False)
    gemini_model: str


def load_settings() -> Settings:
    """Preserva variáveis injetadas e exige configuração explícita do Gemini."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    names = ("GOOGLE_API_KEY", "GEMINI_MODEL")
    values = {name: os.environ.get(name, "").strip() for name in names}
    missing = [name for name in names if not values[name]]
    if missing:
        raise ValueError(
            "Configure as variáveis no ambiente ou no .env: " + ", ".join(missing)
        )
    return Settings(
        google_api_key=values["GOOGLE_API_KEY"],
        gemini_model=values["GEMINI_MODEL"],
    )
