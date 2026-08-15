import json
import logging

import litellm
from fastapi import FastAPI, HTTPException

from config import (
    GROQ_API_KEY,
    LLM_MAX_TOKENS,
    GROQ_MODEL,
    check_config,
    configure_logging,
)
from schemas import (
    AgentMessage,
    AgentTaskRequest,
    DeveloperOutput,
    JiraTicket,
    PlanningResult,
    RepoFile,
    ReviewFeedback,
)

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Developer Agent Service", version="1.0.0")


def _normalize_path(path: str) -> str:
    """Match the Planner's normalization so paths compare consistently
    across services regardless of which OS produced them."""
    return path.replace("\\", "/").strip()


def format_repo_files(repo_files: list[RepoFile]) -> str:
    if not repo_files:
        return ""

    formatted_files = []
    for repo_file in repo_files:
        formatted_files.append(
            f"File: {repo_file.path}\n"
            "```text\n"
            f"{repo_file.content}\n"
            "```"
        )

    return "\n\nExisting project files provided for context:\n\n" + "\n\n".join(formatted_files)


def format_ticket(ticket: JiraTicket | None) -> str:
    if not ticket:
        return ""
    return f"\n\nOriginal Jira ticket:\n{ticket.model_dump_json(indent=2)}"


def format_plan(planning_result: PlanningResult | None) -> str:
    if not planning_result:
        return ""
    return (
        "\n\nImplementation plan (guidance, not a restriction):\n"
        f"{planning_result.model_dump_json(indent=2)}"
    )


def format_planned_new_files(planned_new_files: list[str] | None) -> str:
    if not planned_new_files:
        return ""

    paths = "\n".join(f"- {path}" for path in planned_new_files)
    return (
        "\n\nPlanner-requested new files:\n"
        f"{paths}\n"
        "If these files are necessary to satisfy the ticket, create them.\n"
    )


def format_file_boundary_rule(repo_files: list) -> str:
    """Shortened version: keeps the hard create/update boundary and the
    'flag, don't fabricate' instruction, drops the explanatory prose."""
    repo_files = repo_files or []
    allowed_paths = [_normalize_path(rf.path) for rf in repo_files]

    if allowed_paths:
        paths_list = "\n".join(f"- {p}" for p in allowed_paths)
        allowed_section = f"Files you have real content for:\n{paths_list}\n"
    else:
        allowed_section = "You have not been given any existing file's content.\n"

    return (
        "\n\nFILE RULE:\n"
        f"{allowed_section}"
        "\"create\" is fine for new files. \"update\"/\"upsert\" is only allowed on the paths "
        "listed above. If another existing file also needs changing, do not guess its content — "
        "note it in `explanation` instead. Use forward slashes in paths.\n"
    )


class DeveloperAgent:
    def __init__(self) -> None:
        check_config()
        self.model = GROQ_MODEL

    def generate_code(
        self,
        task: str,
        ticket: JiraTicket | None = None,
        planning_result: PlanningResult | None = None,
        planned_new_files: list[str] | None = None,
        repo_files: list[RepoFile] | None = None,
        model: str | None = None,
    ) -> DeveloperOutput:
        logger.info("Developer agent generating initial code")
        prompt = (
            "Implement the ticket requirements with the smallest possible change set.\n"
            "Focus only on the requested behavior and preserve the existing application structure.\n"
            "Do not refactor unrelated code, add broad validation, or redesign the architecture.\n"
            "The implementation plan is guidance, not a restriction.\n"
            "You may create additional new source files if they are necessary to implement the "
            "Jira ticket correctly and follow the project's architecture.\n"
            f"{format_planned_new_files(planned_new_files)}"
            f"{format_file_boundary_rule(repo_files)}"
            "Return only valid JSON with exactly these keys: code, explanation, changes.\n"
            "The changes value must be a list of objects with path, action, and content.\n"
            "Each change.content must be the full file contents after the edit, not a summary.\n"
            "Do not wrap the JSON in Markdown.\n\n"
            f"Task: {task}"
            f"{format_ticket(ticket)}"
            f"{format_plan(planning_result)}"
            f"{format_repo_files(repo_files or [])}"
        )
        return self._call_llm(prompt, model)

    def improve_code(
        self,
        task: str,
        original_code: str,
        review_feedback: ReviewFeedback,
        ticket: JiraTicket | None = None,
        planning_result: PlanningResult | None = None,
        planned_new_files: list[str] | None = None,
        repo_files: list[RepoFile] | None = None,
        model: str | None = None,
    ) -> DeveloperOutput:
        logger.info("Developer agent improving code from review feedback")
        prompt = (
            "Revise the previous implementation in response to review feedback.\n"
            "Preserve all previously completed ticket functionality. Do not remove or regress existing behavior.\n"
            "Only address blocking issues from the review feedback. Ignore optional suggestions and style-only feedback.\n"
            "Do not refactor unrelated code or change the core design.\n"
            "The implementation plan is guidance, not a restriction.\n"
            "You may create additional new source files if they are necessary to implement the "
            "Jira ticket correctly and follow the project's architecture.\n"
            f"{format_planned_new_files(planned_new_files)}"
            f"{format_file_boundary_rule(repo_files)}"
            "Return only valid JSON with exactly these keys: code, explanation, changes.\n"
            "The changes value must be a list of objects with path, action, and content.\n"
            "Each change.content must be the full file contents after the edit, not a summary.\n"
            "Do not wrap the JSON in Markdown.\n\n"
            f"Original task:\n{task}\n\n"
            f"{format_ticket(ticket)}"
            f"Original code:\n{original_code}\n\n"
            f"Reviewer feedback JSON:\n{review_feedback.model_dump_json(indent=2)}"
            f"{format_plan(planning_result)}"
            f"{format_repo_files(repo_files or [])}"
        )
        return self._call_llm(prompt, model)

    def _call_llm(self, prompt: str, model: str | None = None) -> DeveloperOutput:
        selected_model = model or self.model  # override from orchestrator, or fallback default
        response = litellm.completion(
            model=selected_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior developer agent for a Jira-driven workflow. "
                        "Implement the ticket requirements precisely and preserve existing behavior. "
                        "Never fabricate the content of a file you have not been shown — creating new "
                        "files is fine, but rewriting an existing file you were never given is not. "
                        "Respond with strict JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=LLM_MAX_TOKENS,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Developer model returned an empty response.")

        data = json.loads(content)
        output = DeveloperOutput(**data)

        # Normalize every change's path to forward-slash form so it matches
        # repo_files / allowed_paths consistently regardless of OS, the same
        # way the Planner normalizes likely_existing_files and new_files.
        for change in output.changes:
            change.path = _normalize_path(change.path)

        return output


@app.post("/generate", response_model=DeveloperOutput)
def generate_code(request: AgentTaskRequest) -> DeveloperOutput:
    try:
        developer_agent = DeveloperAgent()
        return developer_agent.generate_code(
            request.task,
            request.ticket,
            request.planning_result,
            request.planned_new_files,
            request.repo_files,
            model=request.model,
        )
    except ValueError as exc:
        logger.warning("Developer output validation failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Developer generation failed")
        raise HTTPException(status_code=500, detail="Developer generation failed.") from exc


@app.post("/improve", response_model=AgentMessage)
def improve_code(message: AgentMessage) -> AgentMessage:
    try:
        developer_agent = DeveloperAgent()
        review_feedback = ReviewFeedback(**message.payload["review_feedback"])
        improved_code = developer_agent.improve_code(
            task=message.payload["task"],
            original_code=message.payload["original_code"],
            review_feedback=review_feedback,
            ticket=(
                JiraTicket(**message.payload["ticket"])
                if message.payload.get("ticket")
                else None
            ),
            planning_result=(
                PlanningResult(**message.payload["planning_result"])
                if message.payload.get("planning_result")
                else None
            ),
            planned_new_files=message.payload.get("planned_new_files", []),
            repo_files=[
                RepoFile(**repo_file)
                for repo_file in message.payload.get("repo_files", [])
            ],
            model=message.payload.get("model"),
        )
        return AgentMessage(
            sender="developer_agent",
            receiver=message.sender,
            message_type="code_generation_result",
            payload=improved_code.model_dump(),
        )
    except ValueError as exc:
        logger.warning("Developer improvement validation failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Developer improvement failed")
        raise HTTPException(status_code=500, detail="Developer improvement failed.") from exc
