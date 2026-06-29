import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_REVIEWER_MODEL = os.getenv("GROQ_REVIEWER_MODEL", "llama-3.3-70b-versatile")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")

JIRA_SERVICE_URL = os.getenv("JIRA_SERVICE_URL", "http://127.0.0.1:8001")
REVIEWER_SERVICE_URL = os.getenv("REVIEWER_SERVICE_URL", "http://127.0.0.1:8002")
DEVELOPER_SERVICE_URL = os.getenv("DEVELOPER_SERVICE_URL", "http://127.0.0.1:8000")
REPO_SERVICE_URL = os.getenv("REPO_SERVICE_URL", "http://127.0.0.1:8004")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO_URL = os.getenv("GITHUB_REPO_URL")
REPO_WORKSPACE_ROOT = Path(
    os.getenv("REPO_WORKSPACE_ROOT", str(Path(__file__).parent / "workspaces"))
)


def check_config() -> None:
    if not GROQ_API_KEY:
        raise RuntimeError("Missing GROQ_API_KEY. Add it to your .env file.")


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
