import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from available_models import AVAILABLE_MODELS

load_dotenv()


def _first_configured_model() -> str:
    for entry in AVAILABLE_MODELS:
        env_var = entry.get("requires_env", "")
        if env_var and os.getenv(env_var):
            return entry["id"]
    return AVAILABLE_MODELS[0]["id"]


GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL") or os.getenv("A2A_DEFAULT_MODEL") or _first_configured_model()
GROQ_REVIEWER_MODEL = os.getenv("GROQ_REVIEWER_MODEL") or GROQ_MODEL
GROQ_PLANNER_MODEL = os.getenv("GROQ_PLANNER_MODEL") or GROQ_MODEL
GROQ_MAX_COMPLETION_TOKENS = 65536


def _bounded_int_env(name: str, default: int, upper_bound: int) -> int:
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return max(1, min(value, upper_bound))


LLM_MAX_TOKENS = _bounded_int_env(
    "A2A_LLM_MAX_TOKENS",
    default=32768,
    upper_bound=GROQ_MAX_COMPLETION_TOKENS,
)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")

JIRA_SERVICE_URL = os.getenv("JIRA_SERVICE_URL", "http://127.0.0.1:8001")
REVIEWER_SERVICE_URL = os.getenv("REVIEWER_SERVICE_URL", "http://127.0.0.1:8002")
DEVELOPER_SERVICE_URL = os.getenv("DEVELOPER_SERVICE_URL", "http://127.0.0.1:8000")
REPO_SERVICE_URL = os.getenv("REPO_SERVICE_URL", "http://127.0.0.1:8004")
KNOWLEDGE_SERVICE_URL = os.getenv("KNOWLEDGE_SERVICE_URL", "http://127.0.0.1:8005")
PLANNER_SERVICE_URL = os.getenv("PLANNER_SERVICE_URL", "http://127.0.0.1:8006")
MODEL_SELECTOR_SERVICE_URL = os.getenv("MODEL_SELECTOR_SERVICE_URL", "http://127.0.0.1:8007")

GITHUB_REPO_URL = os.getenv("GITHUB_REPO_URL")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_WORKSPACE_ROOT = Path(os.getenv("REPO_WORKSPACE_ROOT", "workspaces"))

GITHUB_REPO_URL = os.getenv("GITHUB_REPO_URL")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_WORKSPACE_ROOT = Path(os.getenv("REPO_WORKSPACE_ROOT", "workspaces"))
LOCAL_KNOWLEDGE_ROOT = Path(os.getenv("LOCAL_KNOWLEDGE_ROOT", "local_knowledge_cache"))


def check_config() -> None:
    configured_env_vars = {
        entry["requires_env"]
        for entry in AVAILABLE_MODELS
        if entry.get("requires_env") and os.getenv(entry["requires_env"])
    }
    if not configured_env_vars:
        required = ", ".join(sorted({entry["requires_env"] for entry in AVAILABLE_MODELS}))
        raise RuntimeError(f"Missing model provider API key. Configure one of: {required}.")


def check_jira_config() -> None:
    missing_values = []

    if not JIRA_BASE_URL:
        missing_values.append("JIRA_BASE_URL")
    if not JIRA_EMAIL:
        missing_values.append("JIRA_EMAIL")
    if not JIRA_API_TOKEN:
        missing_values.append("JIRA_API_TOKEN")

    if missing_values:
        names = ", ".join(missing_values)
        raise RuntimeError(f"Missing Jira config: {names}. Add them to your .env file.")


def configure_logging() -> None:
    logging.basicConfig(
        level=LOG_LEVEL.upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
