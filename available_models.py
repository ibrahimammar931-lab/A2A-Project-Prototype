"""
Static, curated list of available models spanning multiple providers.

Each entry's ``id`` is a full LiteLLM-format model string (``"<provider>/<model>"``)
that can be passed directly to ``litellm.completion(model=...)`` with no further
translation needed anywhere else in the codebase.

``requires_env`` names the environment variable the orchestrator checks for a
simple credential-presence filter — models whose key is not configured are
omitted from the /available-models response so the dashboard never shows an
unusable option.

This list is maintained by hand:
- Groq's catalog changes over time (models get deprecated) — check against
  https://console.groq.com/docs/models periodically.
- Anthropic model names should be checked against
  https://docs.anthropic.com/en/docs/about-claude/models
- OpenAI model names should be checked against
  https://platform.openai.com/docs/models
"""
from typing import TypedDict


class AvailableModel(TypedDict):
    id: str
    label: str
    provider: str
    requires_env: str


AVAILABLE_MODELS: list[AvailableModel] = [
    {
        "id": "groq/openai/gpt-oss-20b",
        "label": "GPT-OSS 20B (Groq, fast/cheap)",
        "provider": "groq",
        "requires_env": "GROQ_API_KEY",
    },
    {
        "id": "groq/openai/gpt-oss-120b",
        "label": "GPT-OSS 120B (Groq, balanced)",
        "provider": "groq",
        "requires_env": "GROQ_API_KEY",
    },
    {
        "id": "groq/qwen/qwen3-32b",
        "label": "Qwen3 32B (Groq, strong reasoning)",
        "provider": "groq",
        "requires_env": "GROQ_API_KEY",
    },
    {
        "id": "anthropic/claude-3-5-haiku-latest",
        "label": "Claude 3.5 Haiku (Anthropic)",
        "provider": "anthropic",
        "requires_env": "ANTHROPIC_API_KEY",
    },
    {
        "id": "openai/gpt-4o-mini",
        "label": "GPT-4o mini (OpenAI)",
        "provider": "openai",
        "requires_env": "OPENAI_API_KEY",
    },
]