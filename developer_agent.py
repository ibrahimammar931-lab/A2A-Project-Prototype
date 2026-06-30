import json
import logging

from fastapi import FastAPI, HTTPException
from openai import OpenAI

from config import (
    GROQ_API_KEY,
    GROQ_MODEL,
    check_config,
    configure_logging,
)
from schemas import (
    AgentMessage,
    AgentTaskRequest,
    DeveloperOutput,
    RepoFile,
    ReviewFeedback,
)

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Developer Agent Service", version="1.0.0")


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


class DeveloperAgent:
    def __init__(self) -> None:
        check_config()
        self.model = GROQ_MODEL
        self.client = OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
        )

    def generate_code(
        self,
        task: str,
        repo_files: list[RepoFile] | None = None,
    ) -> DeveloperOutput:
        logger.info("Developer agent generating initial code")
        prompt = (
            "Generate production-minded Python code for this task.\n"
            "Return only valid JSON with exactly these keys: code, explanation, changes.\n"
            "The changes value must be a list of objects with path, action, and content.\n"
            "Do not wrap the JSON in Markdown.\n\n"
            f"Task: {task}"
            f"{format_repo_files(repo_files or [])}"
        )
        return self._ask_groq(prompt)

    def improve_code(
        self,
        task: str,
        original_code: str,
        review_feedback: ReviewFeedback,
        repo_files: list[RepoFile] | None = None,
    ) -> DeveloperOutput:
        logger.info("Developer agent improving code from review feedback")
        prompt = (
            "Improve the code using the reviewer feedback.\n"
            "Return only valid JSON with exactly these keys: code, explanation, changes.\n"
            "The changes value must be a list of objects with path, action, and content.\n"
            "Do not wrap the JSON in Markdown.\n\n"
            f"Original task:\n{task}\n\n"
            f"Original code:\n{original_code}\n\n"
            f"Reviewer feedback JSON:\n{review_feedback.model_dump_json(indent=2)}"
            f"{format_repo_files(repo_files or [])}"
        )
        return self._ask_groq(prompt)

    def _ask_groq(self, prompt: str) -> DeveloperOutput:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior developer agent. You write clean, secure, "
                        "well explained code and always respond with strict JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Developer model returned an empty response.")

        data = json.loads(content)
        return DeveloperOutput(**data)


@app.post("/generate", response_model=DeveloperOutput)
def generate_code(request: AgentTaskRequest) -> DeveloperOutput:
    try:
        developer_agent = DeveloperAgent()
        return developer_agent.generate_code(request.task, request.repo_files)
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
            repo_files=[
                RepoFile(**repo_file)
                for repo_file in message.payload.get("repo_files", [])
            ],
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
