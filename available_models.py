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
    capabilities: str
    power: int


AVAILABLE_MODELS: list[AvailableModel] = [
    {
        "id": "deepseek/deepseek-v4-pro",
        "label": "DeepSeek V4 Pro (DeepSeek, strong reasoning/coding)",
        "provider": "deepseek",
        "requires_env": "DEEPSEEK_API_KEY",
        "capabilities": "strong reasoning, advanced coding, structured output, code review",
        "power": 5,
    },
    {
        "id": "gemini/gemini-2.5-flash",
        "label": "Gemini 2.5 Flash (Google, strong reasoning/coding)",
        "provider": "gemini",
        "requires_env": "GOOGLE_API_KEY",
        "capabilities": "strong reasoning, code generation, fast inference, code review",
        "power": 4,
    },
    {
        "id": "deepseek/deepseek-v4-flash",
        "label": "DeepSeek V4 Flash (DeepSeek, fast/cheap)",
        "provider": "deepseek",
        "requires_env": "DEEPSEEK_API_KEY",
        "capabilities": "fast inference, code generation, instruction-following",
        "power": 4,
    },
    {
        "id": "groq/llama-3.3-70b-versatile",
        "label": "Llama 3.3 70B Versatile (Groq, fast/cheap)",
        "provider": "groq",
        "requires_env": "GROQ_API_KEY",
        "capabilities": "fast inference, code generation, instruction-following",
        "power": 3,
    },
    {
        "id": "groq/openai/gpt-oss-20b",
        "label": "GPT-OSS 20B (Groq, fast/cheap)",
        "provider": "groq",
        "requires_env": "GROQ_API_KEY",
        "capabilities": "fast inference, code generation, instruction-following",
        "power": 2,
    },
    {
        "id": "openrouter/qwen/qwen3.7-flash",
        "label": "Qwen 3.7 Flash (via OpenRouter)",
        "provider": "openrouter",
        "requires_env": "OPENROUTER_API_KEY",
        "capabilities": "code generation, reasoning",
        "power": 3,
    },


]