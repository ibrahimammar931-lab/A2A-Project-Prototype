"""
Model Selector Agent — LLM-based ticket classification + deterministic
per-role model assignment, with inline health checks and selector fallback.

Assignment design (the part that changed):

  Stage 1 (LLM):   read the ticket, return ONLY a complexity classification
                   and any unusual required capabilities. Never returns a
                   model ID.
  Stage 2 (code):  compute each role's target "power" from complexity +
                   a per-role weight, filter candidates by required
                   capability, and pick the closest-power match per role.

Role priority (developer >= planner/reviewer >= knowledge) is guaranteed
by construction via _ROLE_POWER_WEIGHT scaling the same percentile used
for complexity — not by a separate post-hoc cap+rerank pass. See
_target_power_for_role for why this holds at every complexity level.

Health checking is unchanged from the original design: no ledger, no
caching, no TTL, no cooldown windows — a direct try/except ping when a
health check is needed. (Out of scope for this revision; the assignment
logic above is what was reworked.)
"""
from __future__ import annotations

import json
import logging
from typing import Any

import litellm
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from available_models import AVAILABLE_MODELS, AvailableModel
from config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Model Selector Agent Service", version="2.0.0")
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
        return bool(response and response.choices)
    except Exception:
        return False


# -- Roles --------------------------------------------------------------

_FALLBACK_ORDER = ["knowledge", "planner", "developer", "reviewer"]

# -- Complexity rubric ---------------------------------------------------

_COMPLEXITY_LEVELS = ["trivial", "simple", "moderate", "complex", "very_complex"]

# How far up the available power range each complexity level is allowed to
# reach, as a fraction between the lowest and highest candidate power score.
_COMPLEXITY_MAX_PERCENTILE = {
    "trivial": 0.0,
    "simple": 0.25,
    "moderate": 0.55,
    "complex": 0.85,
    "very_complex": 1.0,
}

_COMPLEXITY_RUBRIC = """\
## Complexity rubric

Classify the ticket into exactly one of these levels:

- trivial: a single, mechanical, well-understood change with no design
  decisions — e.g. "add a GET /health endpoint that returns 200 OK", "add
  a new field to an existing Pydantic model", "wire a new route into
  main.py that calls an existing service function", "fix a typo in a log
  message", "bump a config default".
- simple: a small, self-contained feature with a clear shape and low risk
  — e.g. "add a DELETE endpoint for an existing resource", "add input
  validation to an existing endpoint", "add a new CLI flag that toggles
  existing behavior".
- moderate: touches multiple files or requires some non-obvious design
  choice, but the domain is familiar — e.g. "add pagination to an existing
  list endpoint", "add a caching layer in front of an existing read path",
  "refactor a service to support a second provider".
- complex: significant design work, cross-cutting changes, or correctness
  is genuinely hard to get right — e.g. "design and implement a new retry/
  backoff system shared across services", "add multi-tenant isolation to
  an existing data layer", "implement a new consensus/locking mechanism".
- very_complex: novel architecture, security-critical logic, or a change
  whose correctness is difficult to reason about even for an expert —
  e.g. "design a new authorization model from scratch", "implement a
  custom cryptographic protocol", "rearchitect the system for horizontal
  scaling under strict consistency guarantees".
"""

# -- Per-role power weighting -------------------------------------------
#
# Encodes "Developer needs the strongest model; Planner and Reviewer need
# comparable, strong-but-below-Developer reasoning; Knowledge needs the
# least" as numbers that participate directly in the power-target formula,
# rather than as a prompt instruction the LLM has to remember and honor
# across all four roles simultaneously.
_ROLE_POWER_WEIGHT = {
    "developer": 1.0,
    "planner": 0.8,
    "reviewer": 0.8,
    "knowledge": 0.5,
}


def _target_power_for_role(role: str, complexity: str, min_power: float, max_power: float) -> float:
    """Deterministic target power for one role, given ticket complexity.

    Both the complexity percentile and the role weight scale the same
    [min_power, max_power] range, so:
        power(developer) >= power(planner)
        power(developer) >= power(reviewer)
        power(planner)   >= power(knowledge)
        power(reviewer)  >= power(knowledge)
    holds by construction at every complexity level — there's nothing to
    fix after the fact because it can't come out wrong in the first place.
    """
    percentile = _COMPLEXITY_MAX_PERCENTILE[complexity]
    weight = _ROLE_POWER_WEIGHT[role]
    return min_power + weight * percentile * (max_power - min_power)


def _select_model_for_role(target_power: float, candidates: list[dict]) -> dict:
    """Pick the cheapest candidate that meets or exceeds target_power.

    This is a floor, not a nearest-match: target_power is "at least this
    capable," not "closest guess in either direction." A model just
    below the target isn't an acceptable substitute even if it happens to
    be numerically closer than the cheapest model that actually clears
    the bar — e.g. developer's target on a moderate ticket sitting at
    55% of the range should still land on your cheapest top-tier model
    rather than a mid-tier one that's merely nearby.

    Falls back to the single strongest candidate available if nothing
    clears the floor (e.g. every candidate is weaker than the target),
    so a role never ends up with less than the best you've got.
    """
    at_or_above = [c for c in candidates if c["power"] >= target_power]
    if at_or_above:
        return min(at_or_above, key=lambda c: c["power"])
    return max(candidates, key=lambda c: c["power"])


def _filter_by_capabilities(
    candidates: list[dict],
    required_capabilities: list[str],
) -> tuple[list[dict], list[str]]:
    """Keep only candidates whose `capabilities` text mentions every
    required capability tag. If nothing qualifies, fall back to the full
    pool (closest-available-anyway) and report what's missing instead of
    silently ignoring the requirement.
    """
    if not required_capabilities:
        return candidates, []

    matched = [
        c for c in candidates
        if all(tag.lower() in c["capabilities"].lower() for tag in required_capabilities)
    ]
    if matched:
        return matched, []

    unmet = [
        tag for tag in required_capabilities
        if not any(tag.lower() in c["capabilities"].lower() for c in candidates)
    ]
    logger.warning(
        "No candidate satisfies required capabilities %s — falling back to "
        "full candidate pool. Unmet: %s",
        required_capabilities,
        unmet,
    )
    return candidates, unmet


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


# -- Stage 1: LLM classifies only, never picks a model ID -------------------

def _build_classifier_prompt(ticket_text: str) -> str:
    return (
        "You are a ticket classifier. You do NOT choose any model or agent — "
        "that happens elsewhere. Your only job is:\n\n"
        "1. Classify the ticket's complexity using the rubric below. Pick the "
        "closest matching example; don't invent a harder framing of it.\n"
        "2. List any model capabilities this ticket concretely requires beyond "
        "ordinary text/code understanding (e.g. \"image_generation\", \"vision\", "
        "\"long_context\"). Leave the list empty if nothing unusual is needed — "
        "most tickets need nothing here.\n\n"
        f"## Ticket\n\n{ticket_text}\n\n"
        f"{_COMPLEXITY_RUBRIC}\n"
        "## Output\n\n"
        "Return **only** a single valid JSON object — no markdown fences, no "
        "explanation, no extra keys:\n\n"
        "{\n"
        '  "complexity": "<one of: trivial, simple, moderate, complex, very_complex>",\n'
        '  "required_capabilities": ["<tag>", ...]\n'
        "}\n"
    )


def _parse_json_response(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        logger.warning("Classifier LLM returned invalid JSON: %r", raw_text[:300])
        return {}


def select_models_for_ticket(
    ticket_text: str,
    candidates: list[dict],
    selector_model: str,
) -> dict[str, Any]:
    """Classify the ticket, then deterministically assign a model per role.

    `candidates` must already be health-filtered and each entry must have
    at least {"id", "capabilities", "power"}.
    """
    prompt = _build_classifier_prompt(ticket_text)
    try:
        response = litellm.completion(
            model=selector_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.0,
            timeout=60,
        )
        raw_text = response.choices[0].message.content or ""
    except Exception as exc:
        logger.exception("Classifier LLM call failed for model %s", selector_model)
        raise HTTPException(
            status_code=502,
            detail=f"Model selector LLM call failed: {exc}",
        ) from exc

    parsed = _parse_json_response(raw_text)

    complexity = parsed.get("complexity")
    if complexity not in _COMPLEXITY_LEVELS:
        logger.info("Classifier returned invalid complexity %r — defaulting to 'moderate'", complexity)
        complexity = "moderate"
    else:
        logger.info("Classifier assigned ticket_complexity=%s", complexity)

    required_capabilities = parsed.get("required_capabilities")
    if not isinstance(required_capabilities, list):
        required_capabilities = []
    required_capabilities = [c for c in required_capabilities if isinstance(c, str) and c.strip()]

    usable_candidates, unmet_capabilities = _filter_by_capabilities(candidates, required_capabilities)

    powers = [c["power"] for c in usable_candidates]
    min_power, max_power = min(powers), max(powers)

    selection: dict[str, str] = {}
    for role in _FALLBACK_ORDER:
        target = _target_power_for_role(role, complexity, min_power, max_power)
        selection[role] = _select_model_for_role(target, usable_candidates)["id"]

    return {
        "selection": selection,
        "ticket_complexity": complexity,
        "required_capabilities": required_capabilities,
        "unmet_capabilities": unmet_capabilities,
    }


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
    # Do not trust the caller's pre-filtering. The service that actually
    # assigns models to roles is the one that must guarantee those models
    # are healthy.
    candidates = [c for c in all_candidates if check_model_health(c["id"])]
    if not candidates:
        raise HTTPException(
            status_code=502,
            detail="All candidate models failed health checks — cannot select models",
        )

    # Sort ascending by power so anything downstream that wants a cheap
    # default gets a stable, sensible choice.
    candidates.sort(key=lambda c: c["power"])

    # ---- Step 1: health-check the configured selector model ----------------
    selector_used = configured_selector_model
    swapped = False

    if check_model_health(configured_selector_model):
        logger.info(
            "Configured model_selector %s is healthy — using it for classification",
            configured_selector_model,
        )
    else:
        logger.warning(
            "Configured model_selector %s is unhealthy — falling back to candidates",
            configured_selector_model,
        )
        selector_used = candidates[0]["id"]
        swapped = True
        logger.info("Using %s as fallback selector model", selector_used)

    # ---- Step 2: classify + deterministically assign -----------------------
    result = select_models_for_ticket(ticket_text, candidates, selector_used)

    return {
        "selection": result["selection"],
        "selector_model_used": selector_used,
        "selector_swapped": swapped,
        "ticket_complexity": result["ticket_complexity"],
        "required_capabilities": result["required_capabilities"],
        "unmet_capabilities": result["unmet_capabilities"],
    }