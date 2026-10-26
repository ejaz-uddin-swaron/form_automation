"""
config.py – Centralised settings loaded from .env

All user-facing payload fields support `{first_name}`, `{last_name}`,
and `{company}` placeholders that are resolved at runtime.
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env from project root (or wherever the process is started)
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")


# ── Helper ────────────────────────────────────────────────────
def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# ── Pydantic models ──────────────────────────────────────────
class SenderPayload(BaseModel):
    """Contact-form payload that the agent will inject into every form."""

    first_name: str = Field(default_factory=lambda: _env("SENDER_FIRST_NAME", "John"))
    last_name: str = Field(default_factory=lambda: _env("SENDER_LAST_NAME", "Doe"))
    email: str = Field(default_factory=lambda: _env("SENDER_EMAIL", "john@example.com"))
    phone: str = Field(default_factory=lambda: _env("SENDER_PHONE", "+1-555-000-0000"))
    company: str = Field(default_factory=lambda: _env("SENDER_COMPANY", "Acme Corp"))
    subject_template: str = Field(
        default_factory=lambda: _env(
            "SUBJECT_TEMPLATE", "Partnership Inquiry from {company}"
        )
    )
    message_body: str = Field(
        default_factory=lambda: _env(
            "MESSAGE_BODY",
            (
                "Hello,\\n\\n"
                "I'm reaching out on behalf of {company} to explore potential "
                "collaboration opportunities. We'd love to schedule a brief call "
                "at your convenience.\\n\\n"
                "Best regards,\\n{first_name} {last_name}"
            ),
        )
    )

    # ── Resolved helpers ──────────────────────────────────────
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def resolved_subject(self) -> str:
        return self.subject_template.format(
            first_name=self.first_name,
            last_name=self.last_name,
            company=self.company,
        )

    @property
    def resolved_message(self) -> str:
        return (
            self.message_body
            .replace("\\n", "\n")
            .format(
                first_name=self.first_name,
                last_name=self.last_name,
                company=self.company,
            )
        )


class Settings(BaseModel):
    """Top-level application settings."""

    gemini_api_key: str = Field(default_factory=lambda: _env("GEMINI_API_KEY"))
    llm_model: str = Field(default_factory=lambda: _env("LLM_MODEL", "gemini-3.5-flash"))
    headless: bool = Field(
        default_factory=lambda: _env("HEADLESS", "false").lower() in ("1", "true", "yes")
    )
    max_agent_steps: int = Field(
        default_factory=lambda: int(_env("MAX_AGENT_STEPS", "30"))
    )
    sender: SenderPayload = Field(default_factory=SenderPayload)

    # Paths
    targets_csv: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent / "targets.csv"
    )
    results_db: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent / "results.db"
    )


# Singleton instance – import this everywhere
settings = Settings()
