from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def _has_meaningful_content(content: str) -> bool:
    return bool(content and content.strip())


class GenerateRequest(BaseModel):
    issue_key: str
    # NOTE: intentionally "" rather than "main". A truthy default here means
    # any caller that sends only existing_branch (without ALSO explicitly
    # overriding base_branch="") gets rejected by validate_branch_exclusivity
    # below, even though it never touched base_branch. The actual "main"
    # default is applied downstream (see main.py) once we know which mode
    # was requested.
    base_branch: str = ""
    existing_branch: str = ""
    open_pr: bool = True

    @model_validator(mode="after")
    def validate_branch_exclusivity(self):
        if self.base_branch and self.existing_branch:
            raise ValueError(
                "base_branch and existing_branch are mutually exclusive. "
                "Provide exactly one."
            )
        return self


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
    labels: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class RepoInfo(BaseModel):
    repo_id: str
    path: str
    current_branch: str | None = None
    remote_url: str
    status: str


class BranchResponse(BaseModel):
    repo_id: str
    branch: str
    base_branch: str


class RepoFile(BaseModel):
    path: str
    content: str


class FileChange(BaseModel):
    path: str
    action: str
    content: str | None = None


class PlanningRequest(BaseModel):
    jira_ticket: JiraTicket
    project_knowledge: dict[str, Any]


class PlanningResult(BaseModel):
    task_summary: str
    requirements: list[str] = Field(default_factory=list)
    implementation_steps: list[str] = Field(default_factory=list)
    likely_modules: list[str] = Field(default_factory=list)
    likely_existing_files: list[str] = Field(default_factory=list)
    new_files: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    complexity: Literal["Low", "Medium", "High"]

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_file_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        if "likely_files" in normalized and "likely_existing_files" not in normalized:
            normalized["likely_existing_files"] = normalized.pop("likely_files")

        normalized.setdefault("new_files", [])
        return normalized

    @property
    def likely_files(self) -> list[str]:
        return list(dict.fromkeys([*self.likely_existing_files, *self.new_files]))


class AgentTaskRequest(BaseModel):
    task: str
    ticket: JiraTicket | None = None
    planning_result: PlanningResult | None = None
    likely_modules: list[str] = Field(default_factory=list)
    likely_existing_files: list[str] = Field(default_factory=list)
    planned_new_files: list[str] = Field(default_factory=list)
    repo_files: list[RepoFile] = Field(default_factory=list)


class DeveloperOutput(BaseModel):
    explanation: str
    changes: list[FileChange] = Field(default_factory=list)
    code: str = ""

    @field_validator("code", mode="before")
    @classmethod
    def coerce_code(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)

    @field_validator("changes")
    def validate_changes(cls, changes: list[FileChange]) -> list[FileChange]:
        for change in changes:
            action = change.action.lower().strip()
            if action in {"create", "update", "upsert"}:
                if change.content is None:
                    raise ValueError(
                        f"FileChange content is required for action {change.action} on {change.path}."
                    )
                if not _has_meaningful_content(change.content):
                    raise ValueError(
                        f"FileChange content for {change.path} cannot be empty."
                    )
        return changes


class ReviewIssue(BaseModel):
    category: str
    severity: str
    summary: str
    recommendation: str
    location: str | None = None
    ticket_relevant: bool = True


class ReviewFeedback(BaseModel):
    approved: bool
    decision: str = "approve"
    summary: str = ""
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    security_notes: list[str] = Field(default_factory=list)
    quality_notes: list[str] = Field(default_factory=list)
    blocking_issues: list[ReviewIssue] = Field(default_factory=list)
    optional_suggestions: list[ReviewIssue] = Field(default_factory=list)
    requires_revision: bool = False
    rationale: str = ""


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
    planning_result: PlanningResult | None = None
    repo: RepoInfo | None = None
    branch: BranchResponse | None = None
    repo_files: list[RepoFile] = Field(default_factory=list)
    applied_changes: ApplyChangesResponse | None = None
    diff: RepoDiffResponse | None = None
    commit: CommitResponse | None = None
    push: PushResponse | None = None
    pull_request: PullRequestResponse | None = None


class PrepareRepoRequest(BaseModel):
    repo_url: str | None = None


class CreateBranchRequest(BaseModel):
    repo_url: str
    issue_key: str
    title: str
    base_branch: str = "main"


class ReadFilesRequest(BaseModel):
    repo_url: str
    paths: list[str]


class ReadFilesResponse(BaseModel):
    repo_id: str
    files: list[RepoFile]


class ApplyChangesRequest(BaseModel):
    repo_url: str
    changes: list[FileChange]
    branch: str
    commit_message: str | None = None


class ApplyChangesResponse(BaseModel):
    repo_id: str
    changed_files: list[str]
    branch: str
    commit_shas: list[str] = Field(default_factory=list)


class RepoDiffRequest(BaseModel):
    repo_url: str


class RepoDiffResponse(BaseModel):
    repo_id: str
    diff: str


class CommitRequest(BaseModel):
    repo_url: str
    issue_key: str
    summary: str
    body: str | None = None


class CommitResponse(BaseModel):
    repo_id: str
    commit_sha: str
    message: str


class PushRequest(BaseModel):
    repo_url: str
    branch: str | None = None


class PushResponse(BaseModel):
    repo_id: str
    branch: str
    remote: str = "origin"


class PullRequestRequest(BaseModel):
    repo_url: str
    issue_key: str
    title: str
    summary: str
    base_branch: str = "main"
    head_branch: str | None = None
    draft: bool = False
    ticket_url: str | None = None
    test_results: str | None = None


class PullRequestResponse(BaseModel):
    repo_id: str
    number: int
    url: str
    title: str