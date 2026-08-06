import asyncio
import json
import logging
import os
import time
import uuid
from difflib import unified_diff
from typing import Any

import httpx
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from available_models import AVAILABLE_MODELS
from config import (
    DEVELOPER_SERVICE_URL,
    JIRA_SERVICE_URL,
    KNOWLEDGE_SERVICE_URL,
    MODEL_SELECTOR_SERVICE_URL,
    PLANNER_SERVICE_URL,
    REPO_SERVICE_URL,
    REVIEWER_SERVICE_URL,
    configure_logging,
)
from schemas import (
    AgentMessage,
    AgentTaskRequest,
    ApplyChangesRequest,
    ApplyChangesResponse,
    BranchResponse,
    CommitRequest,
    CommitResponse,
    CreateBranchRequest,
    DeveloperOutput,
    GenerateRequest,
    GenerateResponse,
    JiraTicket,
    PlanningRequest,
    PlanningResult,
    PrepareRepoRequest,
    PushRequest,
    PushResponse,
    PullRequestRequest,
    PullRequestResponse,
    ReadFilesRequest,
    ReadFilesResponse,
    RepoDiffResponse,
    RepoInfo,
    ReviewFeedback,
)

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Orchestrator Agent Service", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:4200", "http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def post_or_raise(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
    step: str,
) -> httpx.Response:
    try:
        response = await client.post(url, json=payload)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"{step} failed with {response.status_code}: {response.text}",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"{step} failed due to a transport error: {exc}",
        ) from exc
    return response


def ticket_to_task(ticket: JiraTicket) -> str:
    return (
        "Work on this Jira ticket and generate the code needed to complete it.\n\n"
        f"Ticket: {ticket.key}\n"
        f"URL: {ticket.url}\n"
        f"Summary: {ticket.summary}\n"
        f"Type: {ticket.issue_type}\n"
        f"Status: {ticket.status}\n"
        f"Priority: {ticket.priority}\n"
        f"Assignee: {ticket.assignee}\n"
        f"Reporter: {ticket.reporter}\n"
        f"Labels: {', '.join(ticket.labels)}\n"
        f"Components: {', '.join(ticket.components)}\n\n"
        f"Description:\n{ticket.description}\n\n"
        f"Custom fields:\n{json.dumps(ticket.custom_fields, indent=2)}"
    )


def build_review_diff(changes: list[dict], repo_files: list) -> str:
    repo_file_map = {repo_file.path: repo_file.content for repo_file in repo_files}
    diff_parts: list[str] = []

    for change in changes:
        path = change.get("path", "")
        action = str(change.get("action", "")).lower().strip()
        new_content = change.get("content") or ""
        old_content = repo_file_map.get(path, "")

        if action in {"delete", "removed", "remove"}:
            diff_lines = list(
                unified_diff(
                    old_content.splitlines(),
                    [],
                    fromfile=path,
                    tofile="/dev/null",
                    lineterm="",
                )
            )
        else:
            diff_lines = list(
                unified_diff(
                    old_content.splitlines(),
                    new_content.splitlines(),
                    fromfile=path if old_content else "/dev/null",
                    tofile=path,
                    lineterm="",
                )
            )

        if diff_lines:
            diff_parts.append("\n".join(diff_lines))

    return "\n\n".join(diff_parts)


def validate_planned_changes(output: DeveloperOutput, repo_files: list) -> None:
    allowed_paths = {repo_file.path for repo_file in repo_files}

    unexpected_paths = [
        change.path
        for change in output.changes
        if change.action.lower().strip() in {"update", "delete", "upsert"}
        and change.path not in allowed_paths
    ]
    if unexpected_paths:
        allowed = ", ".join(sorted(allowed_paths)) or "(none — no existing files were provided)"
        unexpected = ", ".join(unexpected_paths)
        raise ValueError(
            "Developer attempted to change files outside the Planner-selected files. "
            f"Unexpected: {unexpected}. Allowed: {allowed}."
        )


class ManualWorkflowController:
    def __init__(self) -> None:
        self.issue_key = os.getenv("DEFAULT_ISSUE_KEY", "A2A-184")
        self.default_base_branch = os.getenv("DEFAULT_BASE_BRANCH", "main")
        self.base_branch = self.default_base_branch
        self.existing_branch = ""
        self.open_pr = True
        self.repo_url = ""
        self.status = "waiting"
        self.current_action = "Ready to start manual workflow."
        self.running_agent = "None"
        self.started_at: float | None = None
        self.step_index = 0
        self.previous_agent = "None"
        self.current_agent = "Jira"
        self.next_agent = "Repository"
        self.context: dict[str, Any] = {}
        self.agents = self._initial_agents()
        self.messages: list[dict[str, Any]] = []
        self.active_path: list[str] = []
        self.clients: set[WebSocket] = set()
        self.lock = None
        self.current_task: asyncio.Task | None = None

    @property
    def steps(self) -> list[dict[str, str]]:
        return [
            {"id": "jira", "name": "Jira"},
            {"id": "repo-initial", "name": "Repository"},
            {"id": "knowledge", "name": "Knowledge"},
            {"id": "planner", "name": "Planner"},
            {"id": "developer", "name": "Developer"},
            {"id": "reviewer", "name": "Reviewer"},
            {"id": "developer-improve", "name": "Developer"},
            {"id": "repo-final", "name": "Repository"},
        ]

    def _agent_id_for_step(self, step_id: str) -> str:
        # Steps that represent a re-run of an existing agent card map back to
        # the original agent id so the dashboard updates the same card instead
        # of spawning a duplicate.
        return {
            "developer-improve": "developer",
        }.get(step_id, step_id)

    def _initial_agents(self) -> dict[str, dict[str, Any]]:
        now = self._now()
        definitions = [
            ("jira", "Jira"),
            ("orchestrator", "Orchestrator"),
            ("repo-initial", "Repo"),
            ("knowledge", "Knowledge"),
            ("planner", "Planner"),
            ("developer", "Developer"),
            ("reviewer", "Reviewer"),
            ("repo-final", "Repo"),
        ]
        return {
            agent_id: {
                "id": agent_id,
                "name": name,
                "status": "waiting",
                "executionState": "Waiting",
                "startTime": None,
                "endTime": None,
                "duration": "00:00:00",
                "currentAction": "Waiting",
                "executionCount": 0,
                "lastExecution": "Never",
                "messagesSent": 0,
                "messagesReceived": 0,
                "files": {"read": [], "modified": [], "created": []},
                "output": {},
                "errors": [],
            }
            for agent_id, name in definitions
        } | {
            "orchestrator": {
                "id": "orchestrator",
                "name": "Orchestrator",
                "status": "success",
                "executionState": "Manual control ready",
                "startTime": now,
                "endTime": None,
                "duration": "00:00:00",
                "currentAction": "Manual control ready",
                "executionCount": 0,
                "lastExecution": now,
                "messagesSent": 0,
                "messagesReceived": 0,
                "files": {"read": [], "modified": [], "created": []},
                "output": {"mode": "manual"},
                "errors": [],
            }
        }

    def reset(
        self,
        issue_key: str | None = None,
        base_branch: str | None = None,
        existing_branch: str | None = None,
        open_pr: bool | None = None,
        repo_url: str | None = None,
    ) -> None:
        # Validate mutual exclusivity based ONLY on what was explicitly passed
        # into *this* call. Checking against the merged/fallback state (the
        # old behavior) was wrong: self.base_branch always has a value
        # (it defaults to "main" and is never actually empty), so it would
        # look "provided" even when the caller only passed existing_branch,
        # causing this to raise on the primary existing-branch path.
        # Unlike the strict /work-on-ticket API (schemas.GenerateRequest,
        # which has a real validator and rejects an explicit conflict with a
        # clear 422), this manual-mode entry point is fed by a dashboard
        # form. That form's base_branch input realistically always carries
        # *some* text - its default value - whether or not the operator
        # actually meant to use it. So if we hard-error whenever both fields
        # are non-empty, using existing_branch from the UI becomes
        # impossible: the leftover default in the base_branch box always
        # trips the "conflict" and Start Workflow silently 400s with no
        # visible feedback. Instead, explicit existing_branch intent simply
        # wins and any base_branch value is discarded alongside it.
        base_given = bool(base_branch and base_branch.strip())
        existing_given = bool(existing_branch and existing_branch.strip())
        if base_given and existing_given:
            logger.info(
                "Both base_branch (%r) and existing_branch (%r) were submitted; "
                "existing_branch takes precedence and base_branch is ignored.",
                base_branch,
                existing_branch,
            )
        # Whichever one was explicitly chosen this call wins outright; clear
        # the other so a previous reset()'s value doesn't linger and get
        # treated as still "set" (e.g. a stale existing_branch surviving a
        # reset that now specifies base_branch).
        if existing_given:
            base_branch = ""
        elif base_given:
            existing_branch = ""

        self.issue_key = issue_key or self.issue_key
        self.base_branch = base_branch if base_branch is not None else self.base_branch
        self.existing_branch = existing_branch if existing_branch is not None else self.existing_branch
        self.open_pr = open_pr if open_pr is not None else self.open_pr
        self.repo_url = repo_url if repo_url is not None else self.repo_url
        self.status = "waiting"
        self.current_action = "Workflow started in manual mode. Jira is waiting for approval."
        self.running_agent = "None"
        self.started_at = time.time()
        self.step_index = 0
        self.previous_agent = "None"
        self.current_agent = "Jira"
        self.next_agent = "Repository"
        self.context = {}
        self.agents = self._initial_agents()
        self.messages = []
        self.active_path = []
        self.current_task = None

    def request_stop(self, reason: str) -> None:
        """Interrupts whatever step is currently executing, if any, and marks
        the workflow as failed/stopped. Safe to call whether or not a step is
        actually mid-execution."""
        self.status = "failed"
        self.running_agent = "None"
        self.current_action = reason
        if self.current_task is not None and not self.current_task.done():
            self.current_task.cancel()

    async def run_next(self) -> None:
        if self.status in {"failed", "completed"}:
            return
        if self.step_index >= len(self.steps):
            self.status = "completed"
            self.current_action = "Workflow completed."
            self.running_agent = "None"
            return

        step = self.steps[self.step_index]
        agent_id = self._agent_id_for_step(step["id"])
        agent = self.agents[agent_id]
        self.status = "running"
        self.running_agent = step["name"]
        self.current_agent = step["name"]
        self.current_action = f"Running {step['name']}"
        self._mark_agent(step["id"], "running", self.current_action)
        await self.broadcast()

        started = time.time()
        handler = getattr(self, f"_run_{step['id'].replace('-', '_')}")
        task = asyncio.ensure_future(handler())
        self.current_task = task
        try:
            await task
            duration = self._duration(started)
            self._mark_agent(step["id"], "success", "Completed", duration=duration)
            if agent_id not in self.active_path:
                self.active_path.append(agent_id)
            self.previous_agent = step["name"]
            self.step_index += 1
            if self.step_index >= len(self.steps):
                self.status = "completed"
                self.current_agent = "None"
                self.next_agent = "None"
                self.running_agent = "None"
                self.current_action = "Workflow completed."
            else:
                next_step = self.steps[self.step_index]
                self.status = "waiting"
                self.current_agent = next_step["name"]
                self.next_agent = self.steps[self.step_index + 1]["name"] if self.step_index + 1 < len(self.steps) else "None"
                self.running_agent = "None"
                self.current_action = f"{step['name']} completed. {next_step['name']} is waiting for approval."
        except asyncio.CancelledError:
            logger.warning("Manual workflow step '%s' was cancelled by operator", step["id"])
            self.status = "failed"
            self.running_agent = "None"
            self.current_action = f"{step['name']} was cancelled by operator."
            self._mark_agent(step["id"], "failed", "Cancelled by operator", error="Cancelled by operator")
        except Exception as exc:
            logger.exception("Manual workflow step failed")
            self.status = "failed"
            self.running_agent = "None"
            self.current_action = str(exc)
            self._mark_agent(step["id"], "failed", "Failed", error=str(exc))
        finally:
            self.current_task = None
        await self.broadcast()

    async def _run_jira(self) -> None:
        async with httpx.AsyncClient(timeout=60) as client:
            # Sync all branch knowledge before starting any real work.
            # This is unconditional housekeeping that runs identically in
            # manual and automatic modes — no operator approval needed.
            # We prepare the repo early (idempotent call) just to get the
            # repository path for the sync; _run_repo_initial will call
            # prepare-repo again later for the actual branch setup.
            repo_response = await post_or_raise(
                client,
                f"{REPO_SERVICE_URL}/prepare-repo",
                PrepareRepoRequest(repo_url=self.repo_url or None).model_dump(),
                "Repo prepare (pre-sync)",
            )
            repo = RepoInfo(**repo_response.json())
            await post_or_raise(
                client,
                f"{KNOWLEDGE_SERVICE_URL}/sync-branches",
                {"repository_path": repo.path, "model": current_model_selection.get("knowledge")},
                "Knowledge sync-branches",
            )

            response = await client.get(f"{JIRA_SERVICE_URL}/tickets/{self.issue_key}")
            response.raise_for_status()
            ticket = JiraTicket(**response.json())
        self.context["ticket"] = ticket
        self.context["task"] = ticket_to_task(ticket)
        self.agents["jira"]["output"] = ticket.model_dump()

    async def _run_repo_initial(self) -> None:
        ticket: JiraTicket = self.context["ticket"]
        async with httpx.AsyncClient(timeout=60) as client:
            response = await post_or_raise(
                client,
                f"{REPO_SERVICE_URL}/prepare-repo",
                PrepareRepoRequest(repo_url=self.repo_url or None).model_dump(),
                "Repo prepare",
            )
            repo = RepoInfo(**response.json())

            if self.existing_branch:
                branch = BranchResponse(
                    repo_id=repo.repo_id,
                    branch=self.existing_branch,
                    base_branch=self.base_branch or self.default_base_branch,
                )
            else:
                branch_response = await post_or_raise(
                    client,
                    f"{REPO_SERVICE_URL}/create-branch",
                    CreateBranchRequest(
                        repo_url=repo.remote_url,
                        issue_key=ticket.key,
                        title=ticket.summary,
                        base_branch=self.base_branch,
                    ).model_dump(),
                    "Repo create-branch",
                )
                branch = BranchResponse(**branch_response.json())

        self.context["repo"] = repo
        self.context["branch"] = branch
        self.agents["repo-initial"]["output"] = {
            "repo": repo.model_dump(),
            "branch": branch.model_dump(),
        }
        self._add_message("Orchestrator", "Repo", "repo.prepared", repo.model_dump(), "delivered")
        self._add_message("Orchestrator", "Repo", "repo.branch_created", branch.model_dump(), "delivered")

    async def _run_knowledge(self) -> None:
        repo: RepoInfo = self.context["repo"]
        branch: BranchResponse = self.context["branch"]
        async with httpx.AsyncClient(timeout=60) as client:
            response = await post_or_raise(
                client,
                f"{KNOWLEDGE_SERVICE_URL}/ensure-knowledge",
                {
                    "repository_path": repo.path,
                    "branch": branch.branch,
                    "known_parent": branch.base_branch,
                    "model": current_model_selection.get("knowledge"),
                },
                "Knowledge ensure",
            )
        knowledge = response.json()
        self.context["knowledge"] = knowledge
        self.agents["knowledge"]["output"] = knowledge
        self._add_message("Knowledge", "Planner", "context.ready", knowledge, "delivered")

    async def _run_planner(self) -> None:
        ticket: JiraTicket = self.context["ticket"]
        knowledge: dict[str, Any] = self.context["knowledge"]
        async with httpx.AsyncClient(timeout=180) as client:
            response = await post_or_raise(
                client,
                f"{PLANNER_SERVICE_URL}/plan",
                PlanningRequest(jira_ticket=ticket, project_knowledge=knowledge, model=current_model_selection.get("planner")).model_dump(),
                "Planner plan",
            )
        planning_result = PlanningResult(**response.json())
        self.context["planning_result"] = planning_result
        payload = planning_result.model_dump()
        self.agents["planner"]["status"] = "requires-revision"
        self.agents["planner"]["output"] = payload
        self._add_message("Planner", "Developer", "planning.completed", payload, "pending-approval")

    async def _run_developer(self) -> None:
        ticket: JiraTicket = self.context["ticket"]
        repo: RepoInfo = self.context["repo"]
        branch: BranchResponse = self.context["branch"]
        planning_result = self._current_planning_result()
        planned_existing_files = list(dict.fromkeys(planning_result.likely_existing_files))
        planned_new_files = list(dict.fromkeys(planning_result.new_files))

        async with httpx.AsyncClient(timeout=180) as client:
            repo_files = []
            if planned_existing_files:
                files_response = await post_or_raise(
                    client,
                    f"{REPO_SERVICE_URL}/read-files",
                    # FIX: pass branch so the Repo service (a) knows which
                    # branch's content to read, and (b) can hard-reset its
                    # working tree to match that branch's remote state
                    # before reading — see checkout_branch's updated
                    # docstring in repo_agent.py. Without this, a file
                    # committed via the GitHub Contents API moments earlier
                    # (or on a prior run) could be genuinely absent from
                    # this local clone's working tree and fail with
                    # "File does not exist" despite existing in the repo's
                    # real history.
                    ReadFilesRequest(
                        repo_url=repo.remote_url,
                        paths=planned_existing_files,
                        branch=branch.branch,
                    ).model_dump(),
                    "Repo read-files",
                )
                repo_files = ReadFilesResponse(**files_response.json()).files
            self.context["repo_files"] = repo_files

            generation_response = await post_or_raise(
                client,
                f"{DEVELOPER_SERVICE_URL}/generate",
                AgentTaskRequest(
                    task=self.context["task"],
                    ticket=ticket,
                    planning_result=planning_result,
                    likely_existing_files=planned_existing_files,
                    planned_new_files=planned_new_files,
                    repo_files=repo_files,
                    model=current_model_selection.get("developer"),
                ).model_dump(),
                "Developer generate",
            )
        output = DeveloperOutput(**generation_response.json())
        validate_planned_changes(output, self.context["repo_files"])
        self.context["developer_output"] = output
        self.agents["developer"]["output"] = output.model_dump()
        self.agents["developer"]["files"] = {
            "read": [repo_file.path for repo_file in self.context["repo_files"]],
            "modified": [change.path for change in output.changes if change.action.lower() in {"update", "upsert"}],
            "created": [change.path for change in output.changes if change.action.lower() == "create"],
        }
        self._add_message("Developer", "Reviewer", "code.review.request", self._review_payload(), "pending-approval")

    async def _run_reviewer(self) -> None:
        review_payload = self._latest_payload("Developer", "Reviewer") or self._review_payload()
        review_payload["model"] = current_model_selection.get("reviewer")
        review_request = AgentMessage(
            sender="orchestrator_agent",
            receiver="reviewer_agent",
            message_type="code_review_request",
            payload=review_payload,
        )
        async with httpx.AsyncClient(timeout=180) as client:
            reviewer_response = await post_or_raise(
                client,
                f"{REVIEWER_SERVICE_URL}/review",
                review_request.model_dump(),
                "Reviewer review",
            )
        review_response = AgentMessage(**reviewer_response.json())
        feedback = ReviewFeedback(**review_response.payload)
        self.context["review_feedback"] = feedback
        self.agents["reviewer"]["output"] = feedback.model_dump()
        status = "requires-revision" if feedback.requires_revision else "success"
        self.agents["reviewer"]["status"] = status
        self._add_message("Reviewer", "Repo", "review.completed", feedback.model_dump(), "pending-approval")

    async def _run_developer_improve(self) -> None:
        feedback: ReviewFeedback = self.context["review_feedback"]
        should_regenerate = bool(feedback.requires_revision and feedback.blocking_issues)

        if not should_regenerate:
            self.agents["developer"]["output"] = {
                "skipped": True,
                "reason": "No blocking issues reported by Reviewer.",
            }
            self._add_message(
                "Reviewer",
                "Developer",
                "code.improvement_skipped",
                {"reason": "No blocking issues reported by Reviewer."},
                "delivered",
            )
            return

        ticket: JiraTicket = self.context["ticket"]
        planning_result = self._current_planning_result()
        planned_existing_files = list(dict.fromkeys(planning_result.likely_existing_files))
        planned_new_files = list(dict.fromkeys(planning_result.new_files))
        repo_files = self.context.get("repo_files", [])
        original_output: DeveloperOutput = self.context["developer_output"]

        filtered_feedback = ReviewFeedback(
            approved=False,
            decision="request_changes",
            summary="Address the blocking issues below while preserving the completed ticket behavior.",
            issues=[issue.summary for issue in feedback.blocking_issues],
            suggestions=[issue.recommendation for issue in feedback.blocking_issues],
            security_notes=[issue.summary for issue in feedback.blocking_issues if issue.category == "security"],
            quality_notes=[issue.summary for issue in feedback.blocking_issues if issue.category in {"bug", "performance", "missing_requirement"}],
            blocking_issues=feedback.blocking_issues,
            optional_suggestions=[],
            requires_revision=True,
            rationale="Only blocking issues were forwarded for revision.",
        )

        improvement_request = AgentMessage(
            sender="orchestrator_agent",
            receiver="developer_agent",
            message_type="code_improvement_request",
            payload={
                "task": self.context["task"],
                "ticket": ticket.model_dump(),
                "planning_result": planning_result.model_dump(),
                "likely_existing_files": planned_existing_files,
                "original_code": original_output.code,
                "planned_new_files": planned_new_files,
                "review_feedback": filtered_feedback.model_dump(),
                "repo_files": [repo_file.model_dump() for repo_file in repo_files],
                "model": current_model_selection.get("developer"),
            },
        )

        async with httpx.AsyncClient(timeout=180) as client:
            improvement_response = await post_or_raise(
                client,
                f"{DEVELOPER_SERVICE_URL}/improve",
                improvement_request.model_dump(),
                "Developer improve",
            )
        improvement_message = AgentMessage(**improvement_response.json())
        improved_output = DeveloperOutput(**improvement_message.payload)
        validate_planned_changes(improved_output, repo_files)

        self.context["developer_output"] = improved_output
        self.agents["developer"]["output"] = improved_output.model_dump()
        self.agents["developer"]["files"] = {
            "read": [repo_file.path for repo_file in repo_files],
            "modified": [change.path for change in improved_output.changes if change.action.lower() in {"update", "upsert"}],
            "created": [change.path for change in improved_output.changes if change.action.lower() == "create"],
        }
        self._add_message("Developer", "Repo", "code.improved", improved_output.model_dump(), "delivered")

    async def _run_repo_final(self) -> None:
        ticket: JiraTicket = self.context["ticket"]
        repo: RepoInfo = self.context["repo"]
        branch: BranchResponse = self.context["branch"]
        output: DeveloperOutput = self.context["developer_output"]
        applied_changes = None
        pull_request = None
        async with httpx.AsyncClient(timeout=60) as client:
            if output.changes:
                apply_request = ApplyChangesRequest(
                    repo_url=repo.remote_url,
                    changes=[change.model_dump() for change in output.changes],
                    branch=branch.branch,
                    commit_message=f"{ticket.key} {ticket.summary}",
                )
                apply_response = await post_or_raise(
                    client,
                    f"{REPO_SERVICE_URL}/apply-changes",
                    apply_request.model_dump(),
                    "Repo apply-changes",
                )
                applied_changes = ApplyChangesResponse(**apply_response.json())
                await post_or_raise(
                    client,
                    f"{KNOWLEDGE_SERVICE_URL}/update-knowledge",
                    {"repository_path": repo.path, "branch": branch.branch, "changes": [change.model_dump() for change in output.changes], "model": current_model_selection.get("knowledge")},
                    "Knowledge update",
                )
                if self.open_pr:
                    pr_response = await post_or_raise(
                        client,
                        f"{REPO_SERVICE_URL}/open-pr",
                        PullRequestRequest(
                            repo_url=repo.remote_url,
                            issue_key=ticket.key,
                            title=ticket.summary,
                            summary=ticket.description or "Pull request created by orchestrator.",
                            base_branch=self.base_branch or self.default_base_branch,
                            head_branch=branch.branch,
                            ticket_url=ticket.url,
                        ).model_dump(),
                        "Repo open-pr",
                    )
                    pull_request = PullRequestResponse(**pr_response.json())
        output_payload = {
            "commits": applied_changes.commit_shas if applied_changes else [],
            "changed_files": applied_changes.changed_files if applied_changes else [],
            "pr_url": pull_request.url if pull_request else None,
        }
        self.agents["repo-final"]["output"] = output_payload
        self.agents["repo-final"]["files"] = {
            "read": [],
            "modified": output_payload["changed_files"],
            "created": [],
        }
        self._add_message("Repo", "Orchestrator", "repo.completed", output_payload, "delivered")

    def _review_payload(self) -> dict[str, Any]:
        ticket: JiraTicket = self.context["ticket"]
        planning_result = self._current_planning_result()
        output: DeveloperOutput = self.context["developer_output"]
        repo_files = self.context.get("repo_files", [])
        return {
            "task": self.context["task"],
            "ticket": ticket.model_dump(),
            "planning_result": planning_result.model_dump(),
            "diff": build_review_diff([change.model_dump() for change in output.changes], repo_files),
            "changes": [change.model_dump() for change in output.changes],
            "explanation": output.explanation,
            "repo_files": [repo_file.model_dump() for repo_file in repo_files],
        }

    def _current_planning_result(self) -> PlanningResult:
        payload = self._latest_payload("Planner", "Developer")
        if payload:
            return PlanningResult(**payload)
        return self.context["planning_result"]

    def _latest_payload(self, sender: str, receiver: str) -> dict[str, Any] | None:
        for message in reversed(self.messages):
            if message["sender"] == sender and message["receiver"] == receiver:
                return message.get("editedPayload") or message["payload"]
        return None

    def save_edited_message(self, message_id: str, payload: dict[str, Any], description: str) -> None:
        for message in self.messages:
            if message["id"] == message_id:
                message["editedPayload"] = payload
                message["status"] = "pending-approval"
                message["userChanges"].append({
                    "time": self._now(),
                    "author": "Dashboard operator",
                    "description": description,
                })
                return
        raise HTTPException(status_code=404, detail="Message not found")

    def send_edited_message(self, message_id: str) -> None:
        for message in self.messages:
            if message["id"] == message_id:
                message["payload"] = message.get("editedPayload") or message["payload"]
                message["status"] = "sent"
                return
        raise HTTPException(status_code=404, detail="Message not found")

    def skip_agent(self) -> None:
        if self.step_index >= len(self.steps):
            return
        step = self.steps[self.step_index]
        self._mark_agent(step["id"], "success", "Skipped by operator")
        self.previous_agent = step["name"]
        self.step_index += 1
        self.status = "waiting"
        self.current_action = f"{step['name']} skipped by operator."
        if self.step_index < len(self.steps):
            self.current_agent = self.steps[self.step_index]["name"]
            self.next_agent = self.steps[self.step_index + 1]["name"] if self.step_index + 1 < len(self.steps) else "None"
        else:
            self.status = "completed"

    async def rerun_current(self) -> None:
        """Re-executes the agent that just ran (or just failed) instead of
        advancing to the next one. run_next() always operates on
        self.steps[self.step_index], and step_index is only incremented after
        a step succeeds - so to rerun the same step we rewind step_index back
        to it before delegating to run_next()."""
        if self.status == "failed":
            # The step at step_index is the one that failed; it was never
            # advanced past, so it's already the rerun target.
            target_index = self.step_index
        else:
            # The step that just completed (or the whole workflow, if
            # "completed") is the one immediately before step_index.
            target_index = self.step_index - 1

        if target_index < 0 or target_index >= len(self.steps):
            # Nothing has run yet, or the index is out of range - no-op.
            return

        step = self.steps[target_index]
        self.step_index = target_index
        self.status = "waiting"
        self.current_action = f"Re-running {step['name']} by operator request."
        self.current_agent = step["name"]
        self.next_agent = self.steps[target_index + 1]["name"] if target_index + 1 < len(self.steps) else "None"
        await self.run_next()

    def snapshot(self) -> dict[str, Any]:
        elapsed = self._duration(self.started_at) if self.started_at else "00:00:00"
        repo = self.context.get("repo")
        branch = self.context.get("branch")
        return {
            "summary": {
                "status": self._dashboard_status(),
                "ticket": self.issue_key,
                "branch": branch.branch if branch else (self.existing_branch or self.base_branch or self.default_base_branch),
                "repository": repo.remote_url if repo else (self.repo_url or os.getenv("GITHUB_REPO_URL", "Not prepared")),
                "runningAgent": self.running_agent,
                "currentAction": self.current_action,
                "totalExecutionTime": elapsed,
                "progress": round((self.step_index / len(self.steps)) * 100),
                "manualMode": current_mode == "manual",
                "previousAgent": self.previous_agent,
                "currentAgent": self.current_agent,
                "nextAgent": self.next_agent,
            },
            "agents": list(self.agents.values()),
            "messages": self.messages,
            "activePath": ["orchestrator", *self.active_path],
        }

    async def broadcast(self) -> None:
        if not self.clients:
            return
        snapshot = self.snapshot()
        disconnected: list[WebSocket] = []
        for websocket in self.clients:
            try:
                await websocket.send_json(snapshot)
            except Exception:
                disconnected.append(websocket)
        for websocket in disconnected:
            self.clients.discard(websocket)

    def _dashboard_status(self) -> str:
        if self.status == "revision":
            return "requires-revision"
        return self.status

    def _add_message(self, sender: str, receiver: str, message_type: str, payload: dict[str, Any], status: str) -> None:
        now = self._now()
        self.messages.append({
            "id": f"msg-{uuid.uuid4().hex[:10]}",
            "time": now,
            "sender": sender,
            "receiver": receiver,
            "type": message_type,
            "status": status,
            "duration": "00:00",
            "summary": message_type.replace(".", " ").title(),
            "payload": payload,
            "userChanges": [],
        })
        for agent in self.agents.values():
            if agent["name"] == sender:
                agent["messagesSent"] += 1
            if agent["name"] == receiver:
                agent["messagesReceived"] += 1

    def _mark_agent(self, agent_id: str, status: str, action: str, duration: str | None = None, error: str | None = None) -> None:
        agent = self.agents[self._agent_id_for_step(agent_id)]
        now = self._now()
        if status == "running":
            agent["startTime"] = now
            agent["executionCount"] += 1
        if status in {"success", "failed"}:
            agent["endTime"] = now
            agent["lastExecution"] = now
        agent["status"] = status
        agent["executionState"] = action
        agent["currentAction"] = action
        if duration:
            agent["duration"] = duration
        if error:
            agent["errors"].append(error)

    def _duration(self, started: float | None) -> str:
        if not started:
            return "00:00:00"
        seconds = int(time.time() - started)
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    def _now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


manual_workflow = ManualWorkflowController()
current_mode: str = "manual"  # "manual" or "automatic"
auto_model_selection: bool = False  # gated by /api/workflow/auto-model-selection

# -- Model selection persistence (system-wide, survives reset()) ----------
MODEL_SELECTION_FILE = "model_selection.json"
AGENT_KEYS = ("knowledge", "planner", "developer", "reviewer")
ALL_MODEL_SELECTION_KEYS = ("knowledge", "planner", "developer", "reviewer", "model_selector")

# Default fallback: each agent key maps to the service's own config.py
# default, which is selected inside the agent itself when model=None is
# received. We store None in the dictionary for agents where no override
# has been picked yet, which lets agent-level fallback happen naturally.
_model_selection_defaults: dict[str, str | None] = {
    "knowledge": None,
    "planner": None,
    "developer": None,
    "reviewer": None,
    "model_selector": None,
}


def _load_model_selection() -> dict[str, str | None]:
    """Load persisted model selection from MODEL_SELECTION_FILE.

    Returns a dict mapping each agent key to a LiteLLM model id, or None
    if no override has been saved yet or the saved model is no longer in
    AVAILABLE_MODELS. Missing keys are filled with None from
    _model_selection_defaults.

    If any stale model ids (not in AVAILABLE_MODELS) are found in the file,
    they are sanitized to None and the file is rewritten immediately so the
    invalid entries are gone from disk on the next load — no manual cleanup
    required.
    """
    available_ids = {entry["id"] for entry in AVAILABLE_MODELS}
    try:
        with open(MODEL_SELECTION_FILE, encoding="utf-8") as f:
            raw = json.loads(f.read())
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_model_selection_defaults)

    result: dict[str, str | None] = {}
    needs_save = False
    for key in ALL_MODEL_SELECTION_KEYS:
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            model_id = val.strip()
            if model_id in available_ids:
                result[key] = model_id
            else:
                logger.warning(
                    "Ignoring saved model selection for %s: %s is not in "
                    "AVAILABLE_MODELS — sanitizing file",
                    key,
                    model_id,
                )
                result[key] = None
                needs_save = True
        else:
            result[key] = None

    if needs_save:
        _save_model_selection(result)

    return result


def _save_model_selection(selection: dict[str, str | None]) -> None:
    """Write the current model selection dict to MODEL_SELECTION_FILE.
    Only persists keys in ALL_MODEL_SELECTION_KEYS."""
    available_ids = {entry["id"] for entry in AVAILABLE_MODELS}
    out: dict[str, str | None] = {}
    for key in ALL_MODEL_SELECTION_KEYS:
        value = selection.get(key)
        out[key] = value if value in available_ids else None
    with open(MODEL_SELECTION_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


current_model_selection: dict[str, str | None] = _load_model_selection()


def _credentialed_model_ids() -> set[str]:
    """Return the set of AVAILABLE_MODELS ids whose requires_env is set."""
    credentialed: set[str] = set()
    for entry in AVAILABLE_MODELS:
        env_var = entry.get("requires_env", "")
        if env_var and os.getenv(env_var):
            credentialed.add(entry["id"])
    return credentialed


def command_result(command: str) -> dict[str, Any]:
    return {"command": command, "accepted": True, "timestamp": manual_workflow._now()}


def _first_provided(payload: dict[str, Any], *keys: str) -> Any:
    """Returns the value for the first key that is actually present in the
    payload, checking in order - even if that value is an empty string.

    This matters because `payload.get("a") or payload.get("b")` treats an
    explicitly-sent empty string for "a" the same as "a" being absent, and
    silently falls through to "b" instead of honoring the caller's explicit
    "clear this field" intent. Only returns None if none of the keys were
    present at all.
    """
    for key in keys:
        if key in payload:
            return payload[key]
    return None


@app.get("/api/workflow/state")
async def workflow_state() -> dict[str, Any]:
    return manual_workflow.snapshot()


@app.websocket("/ws/workflow")
async def workflow_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    manual_workflow.clients.add(websocket)
    await websocket.send_json(manual_workflow.snapshot())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manual_workflow.clients.discard(websocket)


@app.post("/api/workflow/set-mode")
async def workflow_set_mode(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    global current_mode
    new_mode = str(payload.get("mode", "manual")).lower()
    if new_mode not in {"manual", "automatic"}:
        raise HTTPException(status_code=400, detail="Mode must be 'manual' or 'automatic'")
    current_mode = new_mode
    manual_workflow.current_action = f"Mode switched to {new_mode}."
    await manual_workflow.broadcast()
    return {"command": "set-mode", "accepted": True, "mode": current_mode, "timestamp": manual_workflow._now()}


@app.get("/api/workflow/mode")
async def workflow_get_mode() -> dict[str, Any]:
    return {"mode": current_mode}


HEALTH_CHECK_PROMPT = "Say the word healthy and nothing else."
HEALTH_CHECK_TIMEOUT = 15


async def _check_model_health(model_id: str) -> bool:
    """Single-shot LiteLLM health ping from the orchestrator.

    Kept separate from the Model Selector's own health check so the
    orchestrator can pre-filter candidates without depending on the
    selector being available.
    """
    import litellm

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


async def _run_model_selection() -> None:
    """Call the Model Selector agent and persist its returned assignments.

    Only ever overwrites the 4 agent keys (knowledge, planner, developer,
    reviewer). ``model_selector`` is a fixed, human-controlled setting —
    this function's job is choosing models *for* the 4 agents, never for
    itself. The Model Selector service now fails loudly (503) instead of
    silently swapping when its configured model is unhealthy, so there is
    no "swapped" case to handle or persist here anymore.

    Every candidate model is health-checked **before** the list is sent to
    the selector — only models that respond to a trivial ping are included.
    """
    global current_model_selection

    # Build candidate list from credentialed AVAILABLE_MODELS enriched with
    # capabilities and power so the selector has all the context it needs.
    credentialed = _credentialed_model_ids()
    all_candidates = [
        {
            "id": entry["id"],
            "label": entry["label"],
            "capabilities": entry.get("capabilities", "unknown"),
            "power": entry.get("power", 1),
        }
        for entry in AVAILABLE_MODELS
        if entry["id"] in credentialed
    ]

    if not all_candidates:
        logger.warning("No credentialed models available — skipping model selection")
        return

    # ---- Health-check every candidate; only keep the healthy ones -------
    manual_workflow.current_action = "Health-checking candidate models..."
    await manual_workflow.broadcast()

    healthy_candidates: list[dict] = []
    unhealthy: list[str] = []
    for c in all_candidates:
        cid = c["id"]
        if await _check_model_health(cid):
            healthy_candidates.append(c)
            logger.info("Candidate %s is healthy", cid)
        else:
            unhealthy.append(cid)
            logger.warning("Candidate %s is unhealthy — excluded from selection", cid)

    if not healthy_candidates:
        logger.warning("All candidate models failed health checks — skipping model selection")
        return

    if unhealthy:
        logger.info(
            "Filtered %d unhealthy candidates: %s",
            len(unhealthy),
            ", ".join(unhealthy),
        )

    ticket: JiraTicket | None = manual_workflow.context.get("ticket")
    ticket_text = ticket_to_task(ticket) if ticket else ""

    # The model_selector agent reads its own model from model_selection.json
    # itself — we don't pass a current_selection payload for it here.
    payload = {
        "ticket": ticket_text,
        "candidates": healthy_candidates,
    }

    async with httpx.AsyncClient(timeout=90) as client:
        try:
            response = await client.post(
                f"{MODEL_SELECTOR_SERVICE_URL}/select-models",
                json=payload,
            )
            response.raise_for_status()
        except Exception:
            logger.exception("Model selector call failed — keeping current selection")
            return

    result = response.json()
    selection: dict[str, str] = result.get("selection") or {}

    # Only the 4 role keys are ever written here. model_selector is a fixed,
    # human-controlled setting (see model_selection.json /
    # workflow_set_model_selection) — this function never touches it,
    # regardless of what the selector service reports about itself.
    # Reload from disk before applying the partial update. This prevents a
    # long-running server from writing an old in-memory model_selector value
    # back over a manual edit to model_selection.json.
    updated = _load_model_selection()
    for key in AGENT_KEYS:
        if key in selection:
            updated[key] = selection[key]

    current_model_selection = updated
    _save_model_selection(updated)
    logger.info(
        "Model selection updated: %s (selector_model_used=%s)",
        {k: updated.get(k) for k in AGENT_KEYS},
        result.get("selector_model_used"),
    )


async def _run_automatic_workflow() -> None:
    """Runs all workflow steps sequentially without waiting for manual approval.

    Stop/cancel is honored immediately even mid-step: run_next() cancels its
    own in-flight task when manual_workflow.request_stop(...) is called from
    another request, which surfaces here as status flipping to "failed" the
    moment that run_next() call returns — the loop condition below then exits
    without kicking off another step.

    Model selection (when enabled) runs **after** the Jira step, so the
    ticket context has already been populated and can be fed to the
    selector agent.
    """
    manual_workflow.current_action = "Automatic workflow running..."
    manual_workflow.status = "running"
    await manual_workflow.broadcast()

    # Run the Jira step first so the ticket is available for model selection
    if manual_workflow.step_index == 0:
        await manual_workflow.run_next()
        if manual_workflow.status == "failed":
            await manual_workflow.broadcast()
            return
        manual_workflow.status = "running"

    # Model selection right after Jira (ticket context is now populated)
    if auto_model_selection:
        manual_workflow.current_action = "Running model selection..."
        await manual_workflow.broadcast()
        await _run_model_selection()

    # Run remaining steps
    while manual_workflow.status not in {"failed", "completed"} and manual_workflow.step_index < len(manual_workflow.steps):
        await manual_workflow.run_next()
        if manual_workflow.status == "waiting":
            # In auto mode, don't wait - just continue to the next step
            manual_workflow.status = "running"
    await manual_workflow.broadcast()


@app.post("/api/workflow/start")
async def workflow_start(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    manual_workflow.reset(
        issue_key=_first_provided(payload, "issue_key", "ticket"),
        base_branch=_first_provided(payload, "base_branch", "branch"),
        existing_branch=payload.get("existing_branch"),
        open_pr=payload.get("open_pr"),
        repo_url=payload.get("repo_url"),
    )
    await manual_workflow.broadcast()
    if current_mode == "automatic":
        await _run_automatic_workflow()
    return command_result("start")


@app.post("/api/workflow/run-next-agent")
async def workflow_run_next() -> dict[str, Any]:
    await manual_workflow.run_next()
    return command_result("run-next-agent")


@app.post("/api/workflow/pause")
async def workflow_pause() -> dict[str, Any]:
    manual_workflow.status = "paused"
    manual_workflow.running_agent = "None"
    manual_workflow.current_action = "Workflow paused by dashboard operator."
    await manual_workflow.broadcast()
    return command_result("pause")


@app.post("/api/workflow/resume")
async def workflow_resume() -> dict[str, Any]:
    manual_workflow.status = "waiting"
    manual_workflow.current_action = f"{manual_workflow.current_agent} is waiting for approval."
    await manual_workflow.broadcast()
    return command_result("resume")


@app.post("/api/workflow/stop")
async def workflow_stop() -> dict[str, Any]:
    manual_workflow.request_stop("Workflow stopped by dashboard operator.")
    await manual_workflow.broadcast()
    return command_result("stop")


@app.post("/api/workflow/restart")
async def workflow_restart(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    issue_key = payload["issue_key"] if "issue_key" in payload else manual_workflow.issue_key
    base_branch = payload["base_branch"] if "base_branch" in payload else manual_workflow.base_branch
    existing_branch = payload["existing_branch"] if "existing_branch" in payload else manual_workflow.existing_branch
    repo_url = payload["repo_url"] if "repo_url" in payload else manual_workflow.repo_url
    manual_workflow.reset(
        issue_key=issue_key,
        base_branch=base_branch,
        existing_branch=existing_branch,
        open_pr=payload.get("open_pr") if "open_pr" in payload else manual_workflow.open_pr,
        repo_url=repo_url,
    )
    await manual_workflow.broadcast()
    return command_result("restart")


@app.post("/api/workflow/rerun-current-agent")
async def workflow_rerun_current() -> dict[str, Any]:
    await manual_workflow.rerun_current()
    return command_result("rerun-current-agent")


@app.post("/api/workflow/skip-agent")
async def workflow_skip_agent() -> dict[str, Any]:
    manual_workflow.skip_agent()
    await manual_workflow.broadcast()
    return command_result("skip-agent")


@app.post("/api/workflow/cancel")
async def workflow_cancel() -> dict[str, Any]:
    manual_workflow.request_stop("Workflow cancelled by dashboard operator.")
    await manual_workflow.broadcast()
    return command_result("cancel")


@app.post("/api/workflow/export-log")
async def workflow_export_log() -> dict[str, Any]:
    return manual_workflow.snapshot()


@app.post("/api/workflow/save-edited-message")
async def workflow_save_edited_message(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    manual_workflow.save_edited_message(
        message_id=payload["messageId"],
        payload=payload["editedPayload"],
        description=payload.get("description") or "Edited message payload",
    )
    await manual_workflow.broadcast()
    return command_result("save-edited-message")


@app.post("/api/workflow/send-edited-message")
async def workflow_send_edited_message(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    manual_workflow.send_edited_message(payload["messageId"])
    await manual_workflow.broadcast()
    return command_result("send-edited-message")


# -- Model selection endpoints ---------------------------------------------


@app.get("/api/workflow/available-models")
async def workflow_available_models() -> list[dict[str, str]]:
    """Return the credentialed subset of AVAILABLE_MODELS.

    Only entries whose ``requires_env`` environment variable is currently
    set (non-empty) are included — the dashboard dropdown never shows an
    option that would fail for lack of an API key.
    """
    return [
        {"id": entry["id"], "label": entry["label"], "provider": entry["provider"]}
        for entry in AVAILABLE_MODELS
        if os.getenv(entry.get("requires_env", ""))
    ]


@app.get("/api/workflow/model-selection")
async def workflow_get_model_selection() -> dict[str, str | None]:
    """Return the current per-agent model selection dict.

    A null value for an agent means "no override — use the agent's own
    hardcoded default".
    """
    return dict(current_model_selection)


@app.post("/api/workflow/model-selection")
async def workflow_set_model_selection(payload: dict[str, Any] = Body(...)) -> dict[str, str | None]:
    """Update per-agent model selection.

    Accepts a partial dict — only keys present in the payload are updated;
    omitted keys keep their current value. Validates that any provided
    model id exists in AVAILABLE_MODELS AND is currently credentialed.
    """
    global current_model_selection
    credentialed = _credentialed_model_ids()

    updated = dict(current_model_selection)
    for key in ALL_MODEL_SELECTION_KEYS:
        if key not in payload:
            continue
        value = payload[key]
        if value is None or (isinstance(value, str) and not value.strip()):
            # Explicitly clearing the override — store None to fall back to
            # the agent's own default.
            updated[key] = None
            continue
        if not isinstance(value, str):
            raise HTTPException(
                status_code=400,
                detail=f"Model id for '{key}' must be a string, got {type(value).__name__}",
            )
        model_id = value.strip()
        if model_id not in credentialed:
            raise HTTPException(
                status_code=400,
                detail=f"Model '{model_id}' is not available — it is either not in the "
                f"AVAILABLE_MODELS list or its required API key is not configured.",
            )
        updated[key] = model_id

    current_model_selection = updated
    _save_model_selection(updated)
    return dict(current_model_selection)


# -- Auto model selection endpoints -----------------------------------------


@app.get("/api/workflow/auto-model-selection")
async def workflow_get_auto_model_selection() -> dict[str, bool]:
    """Return whether LLM-based model selection runs before each workflow."""
    return {"enabled": auto_model_selection}


@app.post("/api/workflow/set-auto-model-selection")
async def workflow_set_auto_model_selection(
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Enable or disable automatic LLM-based model selection.

    When enabled, the orchestrator calls the Model Selector agent before
    each automatic workflow run and overwrites the per-agent model choices
    with its recommendations.
    """
    global auto_model_selection
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(
            status_code=400,
            detail="'enabled' must be a boolean",
        )
    auto_model_selection = enabled
    return {
        "command": "set-auto-model-selection",
        "accepted": True,
        "enabled": auto_model_selection,
        "timestamp": manual_workflow._now(),
    }
