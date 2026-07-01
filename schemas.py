from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    issue_key: str
    files_to_read: list[str] = Field(default_factory=list)
    repo_url: str | None = None
    base_branch: str = "main"


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


class AgentTaskRequest(BaseModel):
    task: str
    ticket: JiraTicket | None = None
    repo_files: list[RepoFile] = Field(default_factory=list)


class DeveloperOutput(BaseModel):
    explanation: str
    changes: list[FileChange] = Field(default_factory=list)
    code: str = ""


class ReviewFeedback(BaseModel):
    approved: bool
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    security_notes: list[str] = Field(default_factory=list)
    quality_notes: list[str] = Field(default_factory=list)


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
<<<<<<< HEAD
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


class ApplyChangesResponse(BaseModel):
    repo_id: str
    changed_files: list[str]


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
=======
>>>>>>> parent of 8f9fd06 (add git agent)
