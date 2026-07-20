import json
import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from openai import OpenAI

from config import (
    GROQ_API_KEY,
    GROQ_PLANNER_MODEL,
    check_config,
    configure_logging,
)
from schemas import JiraTicket, PlanningRequest, PlanningResult

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Planner Agent Service", version="1.0.0")


def _normalize_path(path: str) -> str:
    """Normalize a file path to forward-slash form so comparisons work
    regardless of which OS produced the path (e.g. the Knowledge agent's
    on-disk relative paths can come out as 'app\\main.py' on Windows,
    while the LLM will almost always write 'app/main.py'). Without this,
    a correct model output can be silently filtered out below simply
    because the separators don't match."""
    return path.replace("\\", "/").strip()


class PlannerAgent:
    def __init__(self) -> None:
        check_config()
        self.model = GROQ_PLANNER_MODEL
        self.client = OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
        )

    def plan_task(
        self,
        jira_ticket: JiraTicket,
        project_knowledge: dict[str, Any],
    ) -> PlanningResult:
        logger.info("Planner agent planning ticket %s", jira_ticket.key)
        prompt = (
            "Create an implementation plan for this Jira ticket using the project knowledge.\n"
            "Do not generate source code. Do not edit files. Do not review code. Do not call tools.\n"
            "Prefer modifying existing files when they already implement the required responsibility.\n"
            "Suggest creating new files whenever doing so results in a cleaner architecture or is necessary for the feature.\n"
            "Do not avoid new files simply because they are not present in the project.\n"
            "Follow the existing project structure and naming conventions when proposing new files.\n"
            "Never duplicate existing functionality.\n"
            "If a new file is required, mention it explicitly in implementation_steps.\n"
            "\n"
            "INTEGRATION RULE: a new file is useless until something wires it in. Always check whether an "
            "existing file must be modified to register/import/mount the new code (e.g. the app entrypoint "
            "that calls app.include_router(...) for a new route file, or wherever models/services get "
            "registered). Use the project knowledge (look for signals like 'FastAPI(', 'include_router', "
            "'app = ') to find it and add it to likely_existing_files. Never leave likely_existing_files "
            "empty when new_files needs wiring — if unsure, name your best guess (e.g. main.py) rather than "
            "omit it. Only leave it empty for standalone additions nothing else calls.\n"
            "\n"
            "CONSISTENCY CHECK (mandatory, do this before writing your final answer): look at every string "
            "in implementation_steps. If any step mentions modifying, editing, updating, wiring, or "
            "registering an EXISTING file (e.g. 'modify app/main.py', 'update the entrypoint', 'register "
            "the route in main.py'), that exact file path MUST also appear in likely_existing_files. If it "
            "does not, add it now before returning your answer — implementation_steps and "
            "likely_existing_files must never contradict each other.\n"
            "\n"
            "PATH FORMAT: always write file paths using forward slashes (e.g. 'app/main.py'), matching the "
            "path format used in the project knowledge below, never backslashes.\n"
            "\n"
            "Return only valid JSON with exactly these keys: task_summary, requirements, "
            "implementation_steps, likely_existing_files, new_files, acceptance_criteria, risks, complexity.\n"
            "complexity must be one of: Low, Medium, High.\n\n"
            f"Jira ticket:\n{jira_ticket.model_dump_json(indent=2)}\n\n"
            f"Project knowledge:\n{json.dumps(project_knowledge, indent=2)}"
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior planning agent. You only produce structured implementation plans. "
                        "You never write code, edit files, review code, call Git, or communicate with other agents."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Planner model returned an empty response.")

        data = json.loads(content)
        result = PlanningResult(**data)

        # Normalize both the model's output and the knowledge base's keys to
        # forward-slash form before comparing, so an OS-specific separator
        # mismatch (e.g. Windows-produced "app\\main.py" in project_knowledge
        # vs. the model's "app/main.py") never silently drops a correct path.
        raw_known_files = (project_knowledge.get("files") or {}).keys()
        known_files = {_normalize_path(p) for p in raw_known_files}

        normalized_likely_existing = [_normalize_path(p) for p in result.likely_existing_files]
        if known_files:
            dropped = [p for p in normalized_likely_existing if p not in known_files]
            if dropped:
                logger.warning(
                    "Planner dropped likely_existing_files not found in project knowledge: %s "
                    "(known files: %s)",
                    dropped,
                    sorted(known_files),
                )
            normalized_likely_existing = [p for p in normalized_likely_existing if p in known_files]

        result.likely_existing_files = list(dict.fromkeys(normalized_likely_existing))
        result.new_files = list(dict.fromkeys(_normalize_path(p) for p in result.new_files))
        return result


agent = PlannerAgent()


def plan_task(jira_ticket: JiraTicket, project_knowledge: dict[str, Any]) -> PlanningResult:
    return agent.plan_task(jira_ticket, project_knowledge)


@app.post("/plan", response_model=PlanningResult)
def plan(payload: PlanningRequest) -> PlanningResult:
    try:
        return plan_task(payload.jira_ticket, payload.project_knowledge)
    except ValueError as exc:
        logger.warning("Planner validation failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Planner service failed")
        raise HTTPException(status_code=500, detail="Planner service failed.") from exc