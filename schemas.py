from typing import Any

from pydantic import BaseModel


class GenerateRequest(BaseModel):
    issue_key: str


class JiraTicket(BaseModel):
    key: str
    url: str
    summary: str
    description: str
    issue_type: str | None = None
    status: str | None = None
    priority: str | None = None
    assignee: str | None = None
    reporter: str | None = None
    labels: list[str] = []
    components: list[str] = []
    custom_fields: dict[str, Any] = {}


class AgentTaskRequest(BaseModel):
    task: str
    ticket: JiraTicket | None = None


class DeveloperOutput(BaseModel):
    code: str
    explanation: str


class ReviewFeedback(BaseModel):
    approved: bool
    issues: list[str] = []
    suggestions: list[str] = []
    security_notes: list[str] = []
    quality_notes: list[str] = []


class AgentMessage(BaseModel):
    sender: str
    receiver: str
    message_type: str
    payload: dict[str, Any]


class GenerateResponse(BaseModel):
    ticket: JiraTicket | None = None
    original_code: DeveloperOutput
    review_feedback: ReviewFeedback
    improved_code: DeveloperOutput
    messages: list[AgentMessage]
