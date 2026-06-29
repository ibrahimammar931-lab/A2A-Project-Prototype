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
from schemas import AgentMessage, ReviewFeedback

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Reviewer Agent Service", version="1.0.0")


class ReviewerAgent:
    def __init__(self) -> None:
        check_config()
        self.model = GROQ_REVIEWER_MODEL
        self.client = OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
        )

    def review_code(self, task: str, code: str, explanation: str) -> ReviewFeedback:
        logger.info("Reviewer agent reviewing developer output")
        prompt = (
            "Review the generated code for bugs, missing validation, security issues, "
            "code quality issues, and best-practice violations.\n"
            "Return only valid JSON with exactly these keys: approved, issues, "
            "suggestions, security_notes, quality_notes.\n\n"
            f"Task:\n{task}\n\n"
            f"Developer explanation:\n{explanation}\n\n"
            f"Code:\n{code}"
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict senior code reviewer. You identify bugs, "
                        "missing validation, security issues, code quality issues, "
                        "and best-practice violations. Always respond with strict JSON."
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
            code=message.payload["code"],
            explanation=message.payload["explanation"],
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
