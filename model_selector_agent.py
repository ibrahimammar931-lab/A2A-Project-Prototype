"""
Model Selector Agent — Single LLM call for end-to-end model selection per role.

Architecture:
  1. Health-check all candidates + the configured selector model via a simple
     ping (same as before — try/except litellm.completion, no ledger/cache).
  2. Pass the ticket text + the list of healthy candidates (with their
     capabilities, power, and label) to a single LLM call.
  3. The LLM assesses the ticket's complexity, determines which capabilities
     each role needs (knowledge, planner, developer, reviewer), and selects
     the best model from the healthy candidates for each role.
  4. Return the selection, complexity, required capabilities, and metadata.

The LLM is the sole decision-maker for the 4 role assignments — there are no
deterministic post-processing functions that override or re-rank its choices
for knowledge/planner/developer/reviewer. The model_selector itself (the LLM
that makes this call) is a separately configured, fixed setting — it is never
swapped automatically; see _resolve_selector_model.
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

app = FastAPI(title="Model Selector Agent Service", version="3.0.0")
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


# -- Roles -------------------------------------------------------------------

_ROLES = ["knowledge", "planner", "developer", "reviewer"]

_ROLE_DESCRIPTIONS = """
## Role Capability Profiles

Each role in the workflow has different demands — the model assigned to it
must match those demands.

### knowledge
- Extracts project context, conventions, and existing patterns from the
  codebase.
- Needs: strong retrieval/understanding over potentially large code surfaces,
  reliable instruction-following, code comprehension.
- Prioritise: breadth of understanding over raw creative power. A fast,
  cost-effective model with solid code-reading ability is ideal.

### planner
- Reads the ticket + knowledge report and produces a structured implementation
  plan with file paths, change descriptions, and ordering.
- Needs: structured output, reasoning, code architecture understanding,
  ability to break down ambiguous requirements into concrete steps.
- Prioritise: strong reasoning and planning ability. Should be able to
  handle moderate-to-complex architectural decisions.

### developer
- Implements the actual code changes according to the plan. This is the
  most execution-heavy role and the one most likely to need the strongest
  model.
- Needs: advanced code generation, strong reasoning, instruction-following,
  ability to work with diffs and multi-file changes. May need long-context
  if many files are involved.
- Prioritise: raw coding strength above all else. This role gets the most
  capable model available.

### reviewer
- Reviews the developer's diff for correctness, bugs, security issues,
  style violations, and missed requirements.
- Needs: strong reasoning, code review capabilities, ability to spot subtle
  bugs and security issues.
- Prioritise: analytical depth and attention to detail. Should be comparable
  to the planner in strength.
"""

# -- Complexity rubric -------------------------------------------------------

_COMPLEXITY_RUBRIC = """\
## Complexity Rubric

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

_COMPLEXITY_LEVELS = ["trivial", "simple", "moderate", "complex", "very_complex"]


# -- Candidate enrichment ----------------------------------------------------

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


def _format_candidates_for_prompt(candidates: list[dict]) -> str:
    """Render the healthy candidates list as a human-readable table for the LLM."""
    lines = ["## Available Models (healthy only)", ""]
    lines.append("| # | Model ID | Label | Power | Capabilities |")
    lines.append("|---|----------|-------|-------|--------------|")
    for i, c in enumerate(candidates, 1):
        lines.append(
            f"| {i} | `{c['id']}` | {c['label']} | "
            f"{c['power']} / 5 | {c['capabilities']} |"
        )
    lines.append("")
    return "\n".join(lines)


# -- Stage: Single LLM call does everything ----------------------------------

def _build_selector_prompt(ticket_text: str, candidates: list[dict]) -> str:
    """Build a prompt that asks the LLM to do the full model selection."""
    candidates_table = _format_candidates_for_prompt(candidates)

    complexity_options = ", ".join(_COMPLEXITY_LEVELS)
    return (
        "You are a model selection engine for a multi-agent code-generation "
        "workflow. Your job is to analyse a Jira ticket and select the best "
        "model from the available pool for each of four specialised agents.\n\n"

        "You must:\n"
        "1. Classify the ticket's complexity using the rubric below.\n"
        "2. Identify any special capabilities this ticket requires beyond "
        'ordinary text/code understanding (e.g. "image_generation", '
        '"vision", "long_context"). Leave the list empty if nothing '
        "unusual is needed — most tickets need nothing here.\n"
        "3. For each of the four roles (knowledge, planner, developer, "
        "reviewer), pick ONE model ID from the available models table. Your "
        "choice must respect the role's capability profile AND the ticket's "
        "complexity — stronger models for harder tickets, cheaper/faster "
        "models for trivial ones.\n\n"

        f"{_ROLE_DESCRIPTIONS}\n\n"

        f"{candidates_table}\n"

        "## Selection Rules\n\n"
        "- Developer always gets the strongest model or a model very close to "
        "the strongest, proportional to ticket complexity.\n"
        "- Planner and Reviewer get comparable strength, slightly below "
        "Developer when complexity demands it.\n"
        "- Knowledge gets the most cost-effective model that still satisfies "
        "the ticket's needs — it can be weaker than the others.\n"
        "- For trivial/simple tickets, it is acceptable (and encouraged) to "
        "use cheaper/faster models for all roles.\n"
        "- You MUST pick model IDs exactly as they appear in the table above. "
        "Do not invent model IDs.\n"
        "- If only one model is available, use it for all roles.\n\n"

        f"## Ticket\n\n{ticket_text}\n\n"

        f"{_COMPLEXITY_RUBRIC}\n"

        "## Output\n\n"
        "Return **only** a single valid JSON object — no markdown fences, no "
        "explanation, no extra keys:\n\n"
        "{\n"
        f'  "complexity": "<one of: {complexity_options}>",\n'
        '  "required_capabilities": ["<tag>", ...],\n'
        '  "selection": {\n'
        '    "knowledge": "<model_id from table>",\n'
        '    "planner": "<model_id from table>",\n'
        '    "developer": "<model_id from table>",\n'
        '    "reviewer": "<model_id from table>"\n'
        '  }\n'
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
        logger.warning("Selector LLM returned invalid JSON: %r", raw_text[:300])
        return {}


def select_models_for_ticket(
    ticket_text: str,
    candidates: list[dict],
    selector_model: str,
) -> dict[str, Any]:
    """Single LLM call that classifies the ticket AND selects a model per role.

    ``candidates`` must already be health-filtered and each entry must have
    at least {"id", "capabilities", "power", "label"}.

    Returns a dict with keys: selection, ticket_complexity,
    required_capabilities, unmet_capabilities.
    """
    prompt = _build_selector_prompt(ticket_text, candidates)
    try:
        response = litellm.completion(
            model=selector_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.0,
            timeout=60,
        )
        raw_text = response.choices[0].message.content or ""
    except Exception as exc:
        logger.exception("Selector LLM call failed for model %s", selector_model)
        raise HTTPException(
            status_code=502,
            detail=f"Model selector LLM call failed: {exc}",
        ) from exc

    parsed = _parse_json_response(raw_text)

    # -- Validate complexity --------------------------------------------------
    complexity = parsed.get("complexity")
    if complexity not in _COMPLEXITY_LEVELS:
        logger.info(
            "Selector returned invalid complexity %r — defaulting to 'moderate'",
            complexity,
        )
        complexity = "moderate"
    else:
        logger.info("Selector assigned ticket_complexity=%s", complexity)

    # -- Validate required_capabilities ---------------------------------------
    required_capabilities = parsed.get("required_capabilities")
    if not isinstance(required_capabilities, list):
        required_capabilities = []
    required_capabilities = [
        c for c in required_capabilities if isinstance(c, str) and c.strip()
    ]

    # -- Validate and sanitise selection --------------------------------------
    selection: dict[str, str] = parsed.get("selection") or {}
    if not isinstance(selection, dict):
        selection = {}

    valid_model_ids = {c["id"] for c in candidates}

    sanitised_selection: dict[str, str] = {}
    for role in _ROLES:
        chosen = selection.get(role, "")
        if isinstance(chosen, str) and chosen.strip() in valid_model_ids:
            sanitised_selection[role] = chosen.strip()
        else:
            # Fallback: pick the strongest (highest power) candidate for this role
            fallback = max(candidates, key=lambda c: c["power"])
            sanitised_selection[role] = fallback["id"]
            logger.warning(
                "Selector returned invalid or missing model for role %r "
                "(got %r) — falling back to %s",
                role,
                chosen,
                fallback["id"],
            )

    # Determine if any required capabilities are unmet by the selected models
    unmet_capabilities: list[str] = []
    if required_capabilities:
        selected_ids = set(sanitised_selection.values())
        selected_caps_text = " ".join(
            c["capabilities"].lower()
            for c in candidates
            if c["id"] in selected_ids
        )
        for tag in required_capabilities:
            if tag.lower() not in selected_caps_text:
                unmet_capabilities.append(tag)
        if unmet_capabilities:
            logger.warning(
                "Required capabilities %s are not covered by selected models",
                unmet_capabilities,
            )

    return {
        "selection": sanitised_selection,
        "ticket_complexity": complexity,
        "required_capabilities": required_capabilities,
        "unmet_capabilities": unmet_capabilities,
    }


# -- Model selection config --------------------------------------------------

MODEL_SELECTION_FILE = "model_selection.json"


def _load_selector_model_id() -> str:
    """Read the model_selector key from model_selection.json."""
    try:
        raw = json.loads(open(MODEL_SELECTION_FILE, encoding="utf-8").read())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Cannot read {MODEL_SELECTION_FILE}: {exc}",
        ) from exc

    model_id = raw.get("model_selector")
    if not isinstance(model_id, str) or not model_id.strip():
        raise HTTPException(
            status_code=502,
            detail=f"model_selector key is missing or invalid in {MODEL_SELECTION_FILE}",
        )
    return model_id.strip()


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

    # Enrich candidates with capabilities/power from static registry
    all_candidates = _build_candidates_list(raw_candidates)

    # ---- Step 0: health-check every candidate --------------------------------
    # Only healthy models are presented to the selector LLM as choices for the
    # 4 roles.
    candidates = [c for c in all_candidates if check_model_health(c["id"])]
    if not candidates:
        raise HTTPException(
            status_code=502,
            detail="All candidate models failed health checks — cannot select models",
        )

    # Sort ascending by power for consistent prompt rendering
    candidates.sort(key=lambda c: c["power"])

    # ---- Step 1: resolve the selector model from model_selection.json ---------
    # This is a fixed, user-configured setting — unlike the 4 role candidates,
    # it is never swapped automatically. If it's unhealthy, that's a config/
    # ops problem to surface and fix, not something this endpoint should paper
    # over by silently routing the selection call through a different model
    # than the one configured.
    selector_model = _load_selector_model_id()

    if not check_model_health(selector_model):
        logger.error(
            "Configured model_selector %s (from %s) is unhealthy — refusing to "
            "auto-swap it. Fix the model's credentials/availability or update "
            "%s.",
            selector_model,
            MODEL_SELECTION_FILE,
            MODEL_SELECTION_FILE,
        )
        raise HTTPException(
            status_code=503,
            detail=(
                f"Configured model_selector '{selector_model}' failed its "
                "health check. It is not auto-swapped — update "
                f"{MODEL_SELECTION_FILE} or restore the model's availability."
            ),
        )

    logger.info("model_selector %s (from %s) is healthy", selector_model, MODEL_SELECTION_FILE)

    # ---- Step 2: single LLM call does everything for the 4 roles -------------
    result = select_models_for_ticket(ticket_text, candidates, selector_model)

    return {
        "selection": result["selection"],
        "selector_model_used": selector_model,
        "ticket_complexity": result["ticket_complexity"],
        "required_capabilities": result["required_capabilities"],
        "unmet_capabilities": result["unmet_capabilities"],
    }