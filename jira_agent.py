import logging
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException

from config import (
    JIRA_API_TOKEN,
    JIRA_BASE_URL,
    JIRA_EMAIL,
    check_jira_config,
    configure_logging,
)
from schemas import JiraTicket

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Jira Service", version="1.0.0")


def get_jira_ticket(issue_key: str) -> JiraTicket:
    check_jira_config()

    base_url = JIRA_BASE_URL.rstrip("/")
    url = f"{base_url}/rest/api/3/issue/{issue_key}"

    logger.info("Fetching Jira ticket %s", issue_key)
    response = httpx.get(
        url,
        auth=(JIRA_EMAIL, JIRA_API_TOKEN),
        headers={"Accept": "application/json"},
        timeout=20,
    )
    response.raise_for_status()

    data = response.json()
    fields = data.get("fields", {})

    return JiraTicket(
        key=data.get("key", issue_key),
        url=f"{base_url}/browse/{data.get('key', issue_key)}",
        summary=fields.get("summary") or "",
        description=extract_jira_text(fields.get("description")),
        issue_type=get_name(fields.get("issuetype")),
        status=get_name(fields.get("status")),
        priority=get_name(fields.get("priority")),
        assignee=get_display_name(fields.get("assignee")),
        reporter=get_display_name(fields.get("reporter")),
        labels=fields.get("labels") or [],
        components=get_names(fields.get("components")),
        custom_fields=get_custom_fields(fields),
    )


def extract_jira_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = []
        if "text" in value:
            parts.append(str(value["text"]))
        for item in value.get("content", []):
            text = extract_jira_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts)
    if isinstance(value, list):
        return "\n".join(extract_jira_text(item) for item in value)
    return str(value)


def get_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("name")
    return None


def get_display_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("displayName")
    return None


def get_names(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [item["name"] for item in values if isinstance(item, dict) and item.get("name")]


def get_custom_fields(fields: dict[str, Any]) -> dict[str, Any]:
    custom_fields = {}

    for key, value in fields.items():
        if key.startswith("customfield_") and value not in (None, "", [], {}):
            custom_fields[key] = simplify_value(value)

    return custom_fields


def simplify_value(value: Any) -> Any:
    if isinstance(value, dict):
        if "name" in value:
            return value["name"]
        if "value" in value:
            return value["value"]
        if "displayName" in value:
            return value["displayName"]
        if "content" in value:
            return extract_jira_text(value)
        return {key: simplify_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [simplify_value(item) for item in value]
    return value


@app.get("/tickets/{issue_key}", response_model=JiraTicket)
def get_ticket(issue_key: str) -> JiraTicket:
    try:
        return get_jira_ticket(issue_key)
    except httpx.HTTPStatusError as exc:
        logger.warning("Jira API request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Jira API request failed.") from exc
    except RuntimeError as exc:
        logger.warning("Jira service config error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Jira service failed")
        raise HTTPException(status_code=500, detail="Jira service failed.") from exc
