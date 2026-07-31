"""
Model Selector Agent — LLM-based ticket complexity analysis + per-role model
assignment, with inline health checks and candidate fallback.

No ledger, no caching, no TTL, no cooldown windows — just a direct try/except
ping when a health check is needed.
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

import litellm
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from available_models import AVAILABLE_MODELS, AvailableModel
from config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Model Selector Agent Service", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:4200", "http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -- Health check ------------------------------------------------------------

HEALTH_CHECK_PROMPT = "Say the word healthy and nothing else."
HEALTH_CHECK_TIMEOUT = 15


def check_model_health(model_id: str) -> bool:
    """Ping *model_id* with a single cheap LiteLLM completion call.

    Returns ``True`` if the call succeeds, ``False`` for any failure
    (bad key, rate-limit, timeout, network error, …).  No ledger, no
    caching, no classification — just pass/fail.
    """
    try:
        response = litellm.completion(
            model=model_id,
            messages=[{"role": "user", "content": HEALTH_CHECK_PROMPT}],
            max_tokens=5,
            timeout=HEALTH_CHECK_TIMEOUT,
        )
        # Any response at all counts as healthy
        return bool(response and response.choices)
    except Exception:
        return False


# -- Fallback selection ------------------------------------------------------

_ROLE_DESCRIPTIONS = {
    "knowledge": (
        "Knowledge Agent — reads repository structure, diffs, and file content "
        "to build a project-context summary. Needs strong instruction-following "
        "and the ability to summarise large amounts of plain text accurately."
    ),
    "planner": (
        "Planner Agent — analyses the ticket and project context to produce a "
        "step-by-step implementation plan, identifying which files to touch, "
        "what to create, and what the acceptance criteria are. Needs strong "
        "reasoning, structured-output capability, and careful task decomposition."
    ),
    "developer": (
        "Developer Agent — writes the actual code changes based on the planner's "
        "output. Needs the strongest code-generation ability, familiarity with "
        "multiple languages/frameworks, and reliable instruction-following so "
        "it only changes what was asked."
    ),
    "reviewer": (
        "Reviewer Agent — reviews diffs for correctness, security issues, bugs, "
        "and missing requirements. Needs strong reasoning, code understanding, "
        "and the ability to produce structured, actionable feedback."
    ),
}

_FALLBACK_ORDER = ["knowledge", "planner", "developer", "reviewer"]


def _build_candidates_list(candidate_models: list[dict]) -> list[dict]:
    """Merge the supplied candidate list with data from AVAILABLE_MODELS.

    If the caller already passes ``capabilities`` and ``power`` in each
    candidate, use them as-is; otherwise enrich from the static registry.
    """
    static_by_id: dict[str, AvailableModel] = {
        entry["id"]: entry for entry in AVAILABLE_MODELS
    }
    enriched: list[dict] = []
    for c in candidate_models:
        model_id = c.get("id", "")
        static = static_by_id.get(model_id)
        enriched.append({
            "id": model_id,
            "label": c.get("label", static.get("label", model_id) if static else model_id),
            "capabilities": c.get("capabilities", static.get("capabilities", "unknown") if static else "unknown"),
            "power": c.get("power", static.get("power", 1) if static else 1),
        })
    return enriched


def _build_selector_prompt(
    ticket_text: str,
    candidates: list[dict],
) -> str:
    """Construct the prompt for the LLM-based selector."""
    candidate_lines: list[str] = []
    for c in candidates:
        candidate_lines.append(
            f"  - id: {c['id']}\n"
            f"    label: {c['label']}\n"
            f"    capabilities: {c['capabilities']}\n"
            f"    power: {c['power']}"
        )

    role_lines: list[str] = []
    for role_key in _FALLBACK_ORDER:
        role_lines.append(f"  - {role_key}: {_ROLE_DESCRIPTIONS[role_key]}")

    return (
        "You are a model selection agent. Your job is to analyse the Jira ticket "
        "below, judge its complexity, and assign the most capability-appropriate "
        "model to each of the 4 agent roles.\n\n"
        "## Ticket\n\n"
        f"{ticket_text}\n\n"
        "## Candidate Models\n\n"
        f"{chr(10).join(candidate_lines)}\n\n"
        "## Roles\n\n"
        f"{chr(10).join(role_lines)}\n\n"
        "## Instructions\n\n"
        "1. Consider the ticket's complexity, technical domain, and scope.\n"
        "2. For each role, pick the candidate model whose capabilities best "
        "match what that role needs for this particular ticket.\n"
        "3. Return **only** a single valid JSON object mapping each role name "
        'to a model id string — no explanation, no rationale, no markdown fences.\n\n'
        "Example output:\n"
        '{"knowledge": "groq/llama-3.3-70b-versatile", "planner": "deepseek/deepseek-v4-pro", '
        '"developer": "deepseek/deepseek-v4-pro", "reviewer": "gemini/gemini-2.5-flash"}'
    )


def _validate_and_fill(
    raw: dict[str, Any],
    valid_ids: set[str],
    current_selection: dict[str, str | None],
    first_candidate_id: str,
) -> dict[str, str]:
    """Validate the LLM response and fill missing/invalid entries.

    Returns a complete 4-key dict mapping each role to a valid model id.
    """
    result: dict[str, str] = {}
    for role_key in _FALLBACK_ORDER:
        value = raw.get(role_key)
        if isinstance(value, str) and value.strip() in valid_ids:
            result[role_key] = value.strip()
        else:
            # Fall back: previous value if it's in the candidate list,
            # otherwise the first candidate.
            prev = current_selection.get(role_key)
            if prev and prev in valid_ids:
                result[role_key] = prev
            else:
                result[role_key] = first_candidate_id
    return result


# -- /select-models endpoint ------------------------------------------------

@app.post("/select-models")
async def select_models(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    ticket_text = str(payload.get("ticket", "") or "")
    if not ticket_text.strip():
        raise HTTPException(status_code=400, detail="'ticket' must be a non-empty string")

    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise HTTPException(
            status_code=400,
            detail="'candidates' must be a non-empty list of model objects",
        )

    current_selection: dict[str, str | None] = payload.get("current_selection") or {}
    if not isinstance(current_selection, dict):
        current_selection = {}

    configured_selector_model: str | None = current_selection.get("model_selector")
    if not configured_selector_model:
        raise HTTPException(
            status_code=400,
            detail="'current_selection.model_selector' is required and must be a non-empty string",
        )

    # Enrich candidates with capabilities/power from static registry
    all_candidates = _build_candidates_list(raw_candidates)

    # ---- Step 0: health-check every candidate ourselves --------------------
    # Do not trust the caller's pre-filtering (e.g. the orchestrator's own
    # health check before this call). The service that actually assigns
    # models to roles is the one that must guarantee those models are
    # healthy — a stale filter, a race between the caller's check and this
    # request, or a future caller that skips filtering entirely should
    # never be able to get a broken model into the prompt or the final
    # selection.
    candidates = [c for c in all_candidates if check_model_health(c["id"])]
    if not candidates:
        raise HTTPException(
            status_code=502,
            detail="All candidate models failed health checks — cannot select models",
        )

    valid_ids = {c["id"] for c in candidates}
    first_candidate_id = candidates[0]["id"]

    # ---- Step 1: health-check the configured selector model ----------------
    # Note: the selector model does the reasoning call and is not required
    # to be one of the role candidates, so it's checked separately from the
    # candidates filter above.
    selector_used = configured_selector_model
    swapped = False

    if check_model_health(configured_selector_model):
        logger.info(
            "Configured model_selector %s is healthy — using it for selection",
            configured_selector_model,
        )
    else:
        logger.warning(
            "Configured model_selector %s is unhealthy — falling back to candidates",
            configured_selector_model,
        )
        # candidates is already health-filtered, so the first entry is a
        # safe fallback selector — no need to re-check each one here.
        selector_used = candidates[0]["id"]
        swapped = True
        logger.info("Using %s as fallback selector model", selector_used)

    # ---- Step 2: call the selector LLM ------------------------------------
    prompt = _build_selector_prompt(ticket_text, candidates)
    print(candidates)

    try:
        response = litellm.completion(
            model=selector_used,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            timeout=60,
        )
        raw_text = response.choices[0].message.content or ""
    except Exception as exc:
        logger.exception("Selector LLM call failed for model %s", selector_used)
        raise HTTPException(
            status_code=502,
            detail=f"Model selector LLM call failed: {exc}",
        ) from exc

    # ---- Step 3: parse and validate ---------------------------------------
    json_text = raw_text.strip()
    if json_text.startswith("```"):
        first_newline = json_text.find("\n")
        if first_newline != -1:
            json_text = json_text[first_newline + 1:]
        if json_text.endswith("```"):
            json_text = json_text[:-3]
        json_text = json_text.strip()

    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError:
        logger.warning("Selector LLM returned invalid JSON: %r", raw_text[:500])
        parsed = {}

    if not isinstance(parsed, dict):
        parsed = {}

    selection = _validate_and_fill(parsed, valid_ids, current_selection, first_candidate_id)

    return {
        "selection": selection,
        "selector_model_used": selector_used,
        "selector_swapped": swapped,
    }