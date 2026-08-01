import json
import logging
from typing import Any
import litellm

from fastapi import FastAPI, HTTPException

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


def _known_top_level_dirs(known_files: set[str]) -> set[str]:
    """Return the set of top-level directory prefixes actually present in
    the project's known files (e.g. {'routes'} for a repo with
    'routes/books.py' and root-level 'main.py'). A path with no '/' at all
    contributes no directory (it lives at the repo root)."""
    dirs: set[str] = set()
    for path in known_files:
        if "/" in path:
            dirs.add(path.split("/")[0])
    return dirs


def _has_invented_top_level_dir(path: str, known_top_level_dirs: set[str], known_files: set[str]) -> bool:
    """Detect a path whose top-level directory doesn't match anything seen
    in the real project structure — this is the specific failure mode
    where a model invents a plausible-but-wrong convention (e.g.
    'app/main.py' or 'app/routes/health.py') based on how FastAPI projects
    are *usually* structured in its training data, rather than how THIS
    repo is actually laid out. Path-separator normalization alone cannot
    catch this, since the invented path is internally well-formed — it's
    just describing a directory that doesn't exist in this project.

    A path with no '/' (root-level, e.g. 'health.py') is never flagged
    here, since root-level files are always structurally valid regardless
    of what subdirectories exist.
    """
    if "/" not in path:
        return False
    top_level = path.split("/")[0]
    if not known_top_level_dirs:
        # No directory structure known yet (e.g. a brand-new/empty repo) —
        # nothing to validate against, so don't flag anything.
        return False
    return top_level not in known_top_level_dirs


class PlannerAgent:
    def __init__(self) -> None:
        check_config()
        self.model = GROQ_PLANNER_MODEL

    def plan_task(
        self,
        jira_ticket: JiraTicket,
        project_knowledge: dict[str, Any],
        model: str | None = None,
    ) -> PlanningResult:
        logger.info("Planner agent planning ticket %s", jira_ticket.key)

        known_files_list = sorted((project_knowledge.get("files") or {}).keys())
        known_files_block = "\n".join(f"- {p}" for p in known_files_list) or "(no files found yet)"

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
            "EXACT PATH RULE (critical — read carefully): the list below, under "
            "'Actual files in this repository', is the COMPLETE and ONLY set of paths that "
            "currently exist. Do not assume any framework convention (such as wrapping "
            "everything in an 'app/' folder, or a 'src/' layout) unless files with that exact "
            "prefix already appear in the list below. If the repository's files sit at the "
            "root (e.g. 'main.py', 'routes/books.py' — no 'app/' prefix), then:\n"
            "  - likely_existing_files must reference paths EXACTLY as they appear in the list "
            "below (e.g. 'main.py', not 'app/main.py').\n"
            "  - new_files must be placed inside one of the SAME top-level directories already "
            "shown below (e.g. 'routes/health.py' if 'routes/' already exists), or at the repo "
            "root if no relevant subdirectory exists yet — never invent a new top-level folder "
            "(such as 'app/') that isn't already present in the list.\n"
            "This rule overrides any general convention you might otherwise assume about how "
            "this type of project 'usually' looks — the list below is ground truth for this "
            "specific repository, not a typical example.\n"
            "\n"
            "Actual files in this repository:\n"
            f"{known_files_block}\n"
            "\n"
            "INTEGRATION RULE: a new file is useless until something wires it in. Always check whether an "
            "existing file must be modified to register/import/mount the new code (e.g. the app entrypoint "
            "that calls app.include_router(...) for a new route file, or wherever models/services get "
            "registered). Use the project knowledge (look for signals like 'FastAPI(', 'include_router', "
            "'app = ') to find it and add it to likely_existing_files. Never leave likely_existing_files "
            "empty when new_files needs wiring — if unsure, name your best guess using an EXACT path from "
            "the list above (e.g. 'main.py', not 'app/main.py') rather than omit it. Only leave it empty "
            "for standalone additions nothing else calls.\n"
            "\n"
            "CONSISTENCY CHECK (mandatory, do this before writing your final answer): look at every string "
            "in implementation_steps. If any step mentions modifying, editing, updating, wiring, or "
            "registering an EXISTING file (e.g. 'modify main.py', 'update the entrypoint', 'register "
            "the route in main.py'), that exact file path — copied verbatim from the list above, not "
            "guessed — MUST also appear in likely_existing_files. If it does not, add it now before "
            "returning your answer — implementation_steps and likely_existing_files must never "
            "contradict each other, and neither may reference a path not shown in the list above.\n"
            "\n"
            "PATH FORMAT: always write file paths using forward slashes (e.g. 'routes/books.py'), matching "
            "the path format used in the project knowledge below, never backslashes.\n"
            "\n"
            "Return only valid JSON with exactly these keys: task_summary, requirements, "
            "implementation_steps, likely_existing_files, new_files, acceptance_criteria, risks, complexity.\n"
            "implementation_steps must be a JSON array of plain strings — each element is a single "
            "sentence describing one step, NOT an object like {\"step\": \"...\"}.\n"
            "complexity is REQUIRED and must be exactly one of: \"Low\", \"Medium\", \"High\" — never omit it.\n\n"
            f"Jira ticket:\n{jira_ticket.model_dump_json(indent=2)}\n\n"
            f"Project knowledge:\n{json.dumps(project_knowledge, indent=2)}"
        )

        selected_model = model or self.model  # override from orchestrator, or fallback default
        response = litellm.completion(
            model=selected_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior planning agent. You only produce structured implementation plans. "
                        "You never write code, edit files, review code, call Git, or communicate with other agents. "
                        "You never assume a generic framework convention when the actual project structure is "
                        "provided to you — you always use the exact paths given."
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

        # Defensive normalization: Groq models occasionally drift from the
        # requested schema (e.g. emitting implementation_steps as objects
        # like {'step': '...'} instead of plain strings, or omitting a
        # required field like complexity). Coerce/patch here rather than
        # letting a shape mismatch 502 the whole request.
        steps = data.get("implementation_steps")
        if isinstance(steps, list):
            normalized_steps = []
            for step in steps:
                if isinstance(step, str):
                    normalized_steps.append(step)
                elif isinstance(step, dict):
                    normalized_steps.append(
                        step.get("step") or step.get("description") or json.dumps(step)
                    )
                else:
                    normalized_steps.append(str(step))
            data["implementation_steps"] = normalized_steps

        if not data.get("complexity"):
            data["complexity"] = "Medium"
            logger.warning("Planner response missing 'complexity'; defaulting to 'Medium'.")

        result = PlanningResult(**data)

        # Normalize both the model's output and the knowledge base's keys to
        # forward-slash form before comparing, so an OS-specific separator
        # mismatch (e.g. Windows-produced "app\\main.py" in project_knowledge
        # vs. the model's "app/main.py") never silently drops a correct path.
        raw_known_files = (project_knowledge.get("files") or {}).keys()
        known_files = {_normalize_path(p) for p in raw_known_files}
        known_top_level_dirs = _known_top_level_dirs(known_files)

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

        # Validate new_files against the real directory structure. This
        # catches the case where the model invents a plausible-but-wrong
        # top-level folder (e.g. "app/routes/health.py" when this repo's
        # real structure is flat, "routes/health.py") — a failure mode that
        # path-separator normalization alone cannot detect, since the
        # invented path is well-formed, just describing a directory that
        # doesn't exist in this specific project. Rather than silently
        # dropping these (which could leave new_files empty when the
        # ticket genuinely needs a new file), we rewrite the path to strip
        # the invented prefix when doing so still lands inside a known
        # directory, and only drop it outright if no reasonable correction
        # exists.
        normalized_new_files: list[str] = []
        for raw_path in result.new_files:
            path = _normalize_path(raw_path)
            if not _has_invented_top_level_dir(path, known_top_level_dirs, known_files):
                normalized_new_files.append(path)
                continue

            # Try stripping the first path segment and see if what remains
            # starts with a known top-level directory or is itself a
            # plausible root-level file.
            parts = path.split("/", 1)
            remainder = parts[1] if len(parts) > 1 else ""
            remainder_top_level = remainder.split("/")[0] if "/" in remainder else None

            if remainder and (remainder_top_level in known_top_level_dirs or "/" not in remainder):
                logger.warning(
                    "Planner proposed new_files path '%s' with an invented top-level directory "
                    "not present in this project (known: %s) — correcting to '%s'.",
                    path,
                    sorted(known_top_level_dirs) or "(none — flat repo)",
                    remainder,
                )
                normalized_new_files.append(remainder)
            else:
                logger.warning(
                    "Planner proposed new_files path '%s' with an invented top-level directory "
                    "not present in this project (known: %s) and no safe correction was found — "
                    "dropping it. The Developer will need to flag this in its explanation instead "
                    "of fabricating a new top-level folder.",
                    path,
                    sorted(known_top_level_dirs) or "(none — flat repo)",
                )

        result.likely_existing_files = list(dict.fromkeys(normalized_likely_existing))
        result.new_files = list(dict.fromkeys(normalized_new_files))
        return result


agent = PlannerAgent()


def plan_task(jira_ticket: JiraTicket, project_knowledge: dict[str, Any], model: str | None = None) -> PlanningResult:
    return agent.plan_task(jira_ticket, project_knowledge, model=model)


@app.post("/plan", response_model=PlanningResult)
def plan(payload: PlanningRequest) -> PlanningResult:
    try:
        return plan_task(payload.jira_ticket, payload.project_knowledge, model=payload.model)
    except ValueError as exc:
        logger.warning("Planner validation failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Planner service failed")
        raise HTTPException(status_code=500, detail="Planner service failed.") from exc