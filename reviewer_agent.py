import json
import logging

from fastapi import FastAPI, HTTPException
from openai import OpenAI

from config import (
    GROQ_API_KEY,
    GROQ_REVIEWER_MODEL,
    check_config,
    configure_logging,
)
from schemas import AgentMessage, RepoFile, ReviewFeedback

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Reviewer Agent Service", version="1.0.0")


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

    return "\n\nRelevant project files:\n\n" + "\n\n".join(formatted_files)


def format_diff(diff: str | None) -> str:
    if not diff:
        return ""
    return "\n\nProposed code changes:\n\n" + diff


class ReviewerAgent:
    def __init__(self) -> None:
        check_config()
        self.model = GROQ_REVIEWER_MODEL
        self.client = OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
        )

    def review_code(
        self,
        task: str,
        ticket: dict | None,
        diff: str | None,
        explanation: str,
        repo_files: list[RepoFile] | None = None,
    ) -> ReviewFeedback:
        logger.info("Reviewer agent reviewing developer output")
        prompt = (
            "You are reviewing a code change for a Jira ticket. Review only the proposed patch and relevant context.\n"
            "Your job is to judge whether the change satisfies the ticket requirements and whether it introduces bugs or regressions.\n"
            "Prioritize: missing requirements, functional bugs, security issues, and performance regressions.\n"
            "Treat style, naming, documentation, refactoring, and extra validation as optional suggestions unless they are required to make the ticket work safely.\n"
            "Do not request unrelated redesigns or broad refactors.\n"
            "Return only valid JSON with exactly these keys: approved, decision, summary, issues, suggestions, security_notes, quality_notes, blocking_issues, optional_suggestions, requires_revision, rationale.\n"
            "The values for issues, suggestions, security_notes, and quality_notes must be arrays of plain strings.\n"
            "The values for blocking_issues and optional_suggestions must be arrays of objects with category, severity, summary, recommendation, location, and ticket_relevant.\n\n"
            f"Task:\n{task}\n\n"
            f"Ticket:\n{json.dumps(ticket or {}, indent=2)}\n\n"
            f"Developer explanation:\n{explanation}\n\n"
            f"{format_diff(diff)}"
            f"{format_repo_files(repo_files or [])}"
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict senior code reviewer for a Jira-driven workflow. "
                        "Judge changes against the ticket requirements, not against personal style preferences. "
                        "Separate blocking issues from optional suggestions and respond with strict JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Reviewer model returned an empty response.")

        data = json.loads(content)
        return ReviewFeedback(**data)


@app.post("/review", response_model=AgentMessage)
def review(message: AgentMessage) -> AgentMessage:
    try:
        reviewer_agent = ReviewerAgent()
        feedback = reviewer_agent.review_code(
            task=message.payload["task"],
            ticket=message.payload.get("ticket"),
            diff=message.payload.get("diff"),
            explanation=message.payload["explanation"],
            repo_files=[
                RepoFile(**repo_file)
                for repo_file in message.payload.get("repo_files", [])
            ],
        )
        return AgentMessage(
            sender="reviewer_agent",
            receiver="developer_agent",
            message_type="review_feedback",
            payload=feedback.model_dump(),
        )
    except ValueError as exc:
        logger.warning("Reviewer output validation failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Reviewer service failed")
        raise HTTPException(status_code=500, detail="Reviewer service failed.") from exc
