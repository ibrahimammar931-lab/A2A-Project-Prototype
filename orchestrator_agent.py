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

from config import (
    DEVELOPER_SERVICE_URL,
    JIRA_SERVICE_URL,
    KNOWLEDGE_SERVICE_URL,
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
    if not allowed_paths:
        return

    unexpected_paths = [
        change.path
        for change in output.changes
        if change.action.lower().strip() in {"update", "delete", "upsert"}
        and change.path not in allowed_paths
    ]
    if unexpected_paths:
        allowed = ", ".join(sorted(allowed_paths))
        unexpected = ", ".join(unexpected_paths)
        raise ValueError(
            "Developer attempted to change files outside the Planner-selected files. "
            f"Unexpected: {unexpected}. Allowed: {allowed}."
        )


class ManualWorkflowController:
    def __init__(self) -> None:
        self.issue_key = os.getenv("DEFAULT_ISSUE_KEY", "A2A-184")
        self.base_branch = os.getenv("DEFAULT_BASE_BRANCH", "main")
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

    def reset(self, issue_key: str | None = None, base_branch: str | None = None) -> None:
        self.issue_key = issue_key or self.issue_key
        self.base_branch = base_branch or self.base_branch
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
                PrepareRepoRequest().model_dump(),
                "Repo prepare",
            )
            repo = RepoInfo(**response.json())

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
        async with httpx.AsyncClient(timeout=60) as client:
            response = await post_or_raise(
                client,
                f"{KNOWLEDGE_SERVICE_URL}/ensure-knowledge",
                {"repository_path": repo.path},
                "Knowledge ensure",
            )
        knowledge = response.json()
        self.context["knowledge"] = knowledge
        self.agents["knowledge"]["output"] = knowledge
        self._add_message("Knowledge", "Planner", "context.ready", knowledge, "delivered")

    async def _run_planner(self) -> None:
        ticket: JiraTicket = self.context["ticket"]
        knowledge: dict[str, Any] = self.context["knowledge"]
        async with httpx.AsyncClient(timeout=60) as client:
            response = await post_or_raise(
                client,
                f"{PLANNER_SERVICE_URL}/plan",
                PlanningRequest(jira_ticket=ticket, project_knowledge=knowledge).model_dump(),
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
        planning_result = self._current_planning_result()
        planned_existing_files = list(dict.fromkeys(planning_result.likely_existing_files))
        planned_new_files = list(dict.fromkeys(planning_result.new_files))

        async with httpx.AsyncClient(timeout=60) as client:
            repo_files = []
            if planned_existing_files:
                files_response = await post_or_raise(
                    client,
                    f"{REPO_SERVICE_URL}/read-files",
                    ReadFilesRequest(repo_url=repo.remote_url, paths=planned_existing_files).model_dump(),
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
                    likely_modules=list(dict.fromkeys(planning_result.likely_modules)),
                    likely_existing_files=planned_existing_files,
                    planned_new_files=planned_new_files,
                    repo_files=repo_files,
                ).model_dump(),
                "Developer generate",
            )
        output = DeveloperOutput(**generation_response.json())
        #validate_planned_changes(output, self.context["repo_files"])
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
        review_request = AgentMessage(
            sender="orchestrator_agent",
            receiver="reviewer_agent",
            message_type="code_review_request",
            payload=review_payload,
        )
        async with httpx.AsyncClient(timeout=60) as client:
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
                "likely_modules": list(dict.fromkeys(planning_result.likely_modules)),
                "likely_existing_files": planned_existing_files,
                "original_code": original_output.code,
                "planned_new_files": planned_new_files,
                "review_feedback": filtered_feedback.model_dump(),
                "repo_files": [repo_file.model_dump() for repo_file in repo_files],
            },
        )

        async with httpx.AsyncClient(timeout=60) as client:
            improvement_response = await post_or_raise(
                client,
                f"{DEVELOPER_SERVICE_URL}/improve",
                improvement_request.model_dump(),
                "Developer improve",
            )
        improvement_message = AgentMessage(**improvement_response.json())
        improved_output = DeveloperOutput(**improvement_message.payload)
        #validate_planned_changes(improved_output, repo_files)

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
                    {"repository_path": repo.path, "changes": [change.model_dump() for change in output.changes]},
                    "Knowledge update",
                )
                pr_response = await post_or_raise(
                    client,
                    f"{REPO_SERVICE_URL}/open-pr",
                    PullRequestRequest(
                        repo_url=repo.remote_url,
                        issue_key=ticket.key,
                        title=ticket.summary,
                        summary=ticket.description or "Pull request created by orchestrator.",
                        base_branch=self.base_branch,
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
                "branch": branch.branch if branch else self.base_branch,
                "repository": repo.remote_url if repo else os.getenv("GITHUB_REPO_URL", "Not prepared"),
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


def command_result(command: str) -> dict[str, Any]:
    return {"command": command, "accepted": True, "timestamp": manual_workflow._now()}


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


async def _run_automatic_workflow() -> None:
    """Runs all workflow steps sequentially without waiting for manual approval.

    Stop/cancel is honored immediately even mid-step: run_next() cancels its
    own in-flight task when manual_workflow.request_stop(...) is called from
    another request, which surfaces here as status flipping to "failed" the
    moment that run_next() call returns — the loop condition below then exits
    without kicking off another step.
    """
    manual_workflow.current_action = "Automatic workflow running..."
    manual_workflow.status = "running"
    await manual_workflow.broadcast()
    while manual_workflow.status not in {"failed", "completed"} and manual_workflow.step_index < len(manual_workflow.steps):
        await manual_workflow.run_next()
        if manual_workflow.status == "waiting":
            # In auto mode, don't wait - just continue to the next step
            manual_workflow.status = "running"
    await manual_workflow.broadcast()


@app.post("/api/workflow/start")
async def workflow_start(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    manual_workflow.reset(
        issue_key=payload.get("issue_key") or payload.get("ticket"),
        base_branch=payload.get("base_branch") or payload.get("branch"),
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
    manual_workflow.reset(
        issue_key=payload.get("issue_key") or manual_workflow.issue_key,
        base_branch=payload.get("base_branch") or manual_workflow.base_branch,
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


@app.post("/work-on-ticket", response_model=GenerateResponse)
async def work_on_ticket(request: GenerateRequest) -> GenerateResponse:
    messages: list[AgentMessage] = []
    repo: RepoInfo | None = None
    branch: BranchResponse | None = None
    repo_files = []
    planning_result: PlanningResult | None = None

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            ticket_response = await client.get(
                f"{JIRA_SERVICE_URL}/tickets/{request.issue_key}"
            )
            ticket_response.raise_for_status()
            ticket = JiraTicket(**ticket_response.json())

            task = ticket_to_task(ticket)

            repo_response = await post_or_raise(
                client,
                f"{REPO_SERVICE_URL}/prepare-repo",
                PrepareRepoRequest().model_dump(),
                "Repo prepare",
            )
            repo = RepoInfo(**repo_response.json())
            messages.append(
                AgentMessage(
                    sender="orchestrator_agent",
                    receiver="repo_agent",
                    message_type="repo_prepared",
                    payload=repo.model_dump(),
                )
            )

            branch_response = await post_or_raise(
                client,
                f"{REPO_SERVICE_URL}/create-branch",
                CreateBranchRequest(
                    repo_url=repo.remote_url,
                    issue_key=ticket.key,
                    title=ticket.summary,
                    base_branch=request.base_branch,
                ).model_dump(),
                "Repo create-branch",
            )
            branch = BranchResponse(**branch_response.json())
            messages.append(
                AgentMessage(
                    sender="orchestrator_agent",
                    receiver="repo_agent",
                    message_type="repo_branch_created",
                    payload=branch.model_dump(),
                )
            )

            knowledge_response = await post_or_raise(
                client,
                f"{KNOWLEDGE_SERVICE_URL}/ensure-knowledge",
                {"repository_path": repo.path},
                "Knowledge ensure",
            )
            knowledge = knowledge_response.json()
            messages.append(
                AgentMessage(
                    sender="orchestrator_agent",
                    receiver="knowledge_agent",
                    message_type="knowledge_ensured",
                    payload=knowledge,
                )
            )

            planning_response = await post_or_raise(
                client,
                f"{PLANNER_SERVICE_URL}/plan",
                PlanningRequest(
                    jira_ticket=ticket,
                    project_knowledge=knowledge,
                ).model_dump(),
                "Planner plan",
            )
            planning_result = PlanningResult(**planning_response.json())
            messages.append(
                AgentMessage(
                    sender="orchestrator_agent",
                    receiver="planner_agent",
                    message_type="planning_completed",
                    payload=planning_result.model_dump(),
                )
            )

            planned_existing_files = list(dict.fromkeys(planning_result.likely_existing_files))
            planned_new_files = list(dict.fromkeys(planning_result.new_files))

            if planned_existing_files:
                files_response = await post_or_raise(
                    client,
                    f"{REPO_SERVICE_URL}/read-files",
                    ReadFilesRequest(
                        repo_url=repo.remote_url,
                        paths=planned_existing_files,
                    ).model_dump(),
                    "Repo read-files",
                )
                read_files = ReadFilesResponse(**files_response.json())
                repo_files = read_files.files
                messages.append(
                    AgentMessage(
                        sender="orchestrator_agent",
                        receiver="repo_agent",
                        message_type="repo_files_read",
                        payload={
                            "repo_id": read_files.repo_id,
                            "paths": [repo_file.path for repo_file in repo_files],
                        },
                    )
                )

            generation_response = await post_or_raise(
                client,
                f"{DEVELOPER_SERVICE_URL}/generate",
                AgentTaskRequest(
                    task=task,
                    ticket=ticket,
                    planning_result=planning_result,
                    likely_modules=list(dict.fromkeys(planning_result.likely_modules)),
                    likely_existing_files=planned_existing_files,
                    planned_new_files=planned_new_files,
                    repo_files=repo_files,
                ).model_dump(),
                "Developer generate",
            )
            original_output = DeveloperOutput(**generation_response.json())
            #validate_planned_changes(original_output, repo_files)

            review_request = AgentMessage(
                sender="orchestrator_agent",
                receiver="reviewer_agent",
                message_type="code_review_request",
                payload={
                    "task": task,
                    "ticket": ticket.model_dump(),
                    "planning_result": planning_result.model_dump() if planning_result else None,
                    "diff": build_review_diff(
                        [change.model_dump() for change in original_output.changes],
                        repo_files,
                    ),
                    "changes": [change.model_dump() for change in original_output.changes],
                    "explanation": original_output.explanation,
                    "repo_files": [
                        repo_file.model_dump() for repo_file in repo_files
                    ],
                },
            )
            messages.append(review_request)

            reviewer_response = await post_or_raise(
                client,
                f"{REVIEWER_SERVICE_URL}/review",
                review_request.model_dump(),
                "Reviewer review",
            )
            review_response = AgentMessage(**reviewer_response.json())
            messages.append(review_response)
            review_feedback = ReviewFeedback(**review_response.payload)

            should_regenerate = bool(review_feedback.requires_revision and review_feedback.blocking_issues)

            if should_regenerate:
                filtered_feedback = ReviewFeedback(
                    approved=False,
                    decision="request_changes",
                    summary="Address the blocking issues below while preserving the completed ticket behavior.",
                    issues=[issue.summary for issue in review_feedback.blocking_issues],
                    suggestions=[issue.recommendation for issue in review_feedback.blocking_issues],
                    security_notes=[issue.summary for issue in review_feedback.blocking_issues if issue.category == "security"],
                    quality_notes=[issue.summary for issue in review_feedback.blocking_issues if issue.category in {"bug", "performance", "missing_requirement"}],
                    blocking_issues=review_feedback.blocking_issues,
                    optional_suggestions=[],
                    requires_revision=True,
                    rationale="Only blocking issues were forwarded for revision.",
                )

                improvement_request = AgentMessage(
                    sender="orchestrator_agent",
                    receiver="developer_agent",
                    message_type="code_improvement_request",
                    payload={
                        "task": task,
                        "ticket": ticket.model_dump(),
                        "planning_result": planning_result.model_dump() if planning_result else None,
                        "likely_modules": list(dict.fromkeys(planning_result.likely_modules)),
                        "likely_existing_files": planned_existing_files,
                        "original_code": original_output.code,
                        "planned_new_files": planned_new_files,
                        "review_feedback": filtered_feedback.model_dump(),
                        "repo_files": [
                            repo_file.model_dump() for repo_file in repo_files
                        ],
                    },
                )
                messages.append(improvement_request)

                improvement_response = await post_or_raise(
                    client,
                    f"{DEVELOPER_SERVICE_URL}/improve",
                    improvement_request.model_dump(),
                    "Developer improve",
                )
                improvement_message = AgentMessage(**improvement_response.json())
                messages.append(improvement_message)
                improved_output = DeveloperOutput(**improvement_message.payload)
                #validate_planned_changes(improved_output, repo_files)
            else:
                improved_output = original_output

            applied_changes: ApplyChangesResponse | None = None
            diff: str | None = None
            commit: CommitResponse | None = None
            push: PushResponse | None = None
            pull_request: PullRequestResponse | None = None

            if repo and branch and improved_output.changes:
                apply_changes_request = ApplyChangesRequest(
                    repo_url=repo.remote_url,
                    changes=[change.model_dump() for change in improved_output.changes],
                    branch=branch.branch,
                    commit_message=f"{ticket.key} {ticket.summary}",
                )
                messages.append(
                    AgentMessage(
                        sender="orchestrator_agent",
                        receiver="repo_agent",
                        message_type="repo_apply_changes_request",
                        payload=apply_changes_request.model_dump(),
                    )
                )

                try:
                    apply_response = await post_or_raise(
                        client,
                        f"{REPO_SERVICE_URL}/apply-changes",
                        apply_changes_request.model_dump(),
                        "Repo apply-changes",
                    )
                except HTTPException as exc:
                    raise HTTPException(
                        status_code=exc.status_code,
                        detail=f"{exc.detail}\nRequest: {apply_changes_request.model_dump_json()}",
                    ) from exc

                applied_changes = ApplyChangesResponse(**apply_response.json())
                messages.append(
                    AgentMessage(
                        sender="orchestrator_agent",
                        receiver="repo_agent",
                        message_type="repo_changes_applied",
                        payload=applied_changes.model_dump(),
                    )
                )

                knowledge_response = await post_or_raise(
                    client,
                    f"{KNOWLEDGE_SERVICE_URL}/update-knowledge",
                    {
                        "repository_path": repo.path,
                        "changes": [change.model_dump() for change in improved_output.changes],
                    },
                    "Knowledge update",
                )
                knowledge_payload = knowledge_response.json()
                messages.append(
                    AgentMessage(
                        sender="orchestrator_agent",
                        receiver="knowledge_agent",
                        message_type="knowledge_updated",
                        payload=knowledge_payload,
                    )
                )

                diff = (
                    "Changes committed through GitHub API:\n"
                    + "\n".join(f"- {path}" for path in applied_changes.changed_files)
                )
                messages.append(
                    AgentMessage(
                        sender="orchestrator_agent",
                        receiver="repo_agent",
                        message_type="repo_diff_generated",
                        payload={"repo_id": repo.repo_id, "diff": diff},
                    )
                )

                commit = CommitResponse(
                    repo_id=repo.repo_id,
                    commit_sha=(
                        applied_changes.commit_shas[-1]
                        if applied_changes.commit_shas
                        else "no-commit-created"
                    ),
                    message=f"{ticket.key} {ticket.summary}",
                )
                messages.append(
                    AgentMessage(
                        sender="orchestrator_agent",
                        receiver="repo_agent",
                        message_type="repo_committed",
                        payload=commit.model_dump(),
                    )
                )

                push = PushResponse(repo_id=repo.repo_id, branch=branch.branch)
                messages.append(
                    AgentMessage(
                        sender="orchestrator_agent",
                        receiver="repo_agent",
                        message_type="repo_pushed",
                        payload=push.model_dump(),
                    )
                )

                pr_response = await post_or_raise(
                    client,
                    f"{REPO_SERVICE_URL}/open-pr",
                    PullRequestRequest(
                        repo_url=repo.remote_url,
                        issue_key=ticket.key,
                        title=ticket.summary,
                        summary=ticket.description or "Pull request created by orchestrator.",
                        base_branch=request.base_branch,
                        head_branch=branch.branch,
                        ticket_url=ticket.url,
                    ).model_dump(),
                    "Repo open-pr",
                )
                pull_request = PullRequestResponse(**pr_response.json())
                messages.append(
                    AgentMessage(
                        sender="orchestrator_agent",
                        receiver="repo_agent",
                        message_type="repo_pr_opened",
                        payload=pull_request.model_dump(),
                    )
                )

        return GenerateResponse(
            ticket=ticket,
            original_code=original_output,
            review_feedback=review_feedback,
            improved_code=improved_output,
            messages=messages,
            planning_result=planning_result,
            repo=repo,
            branch=branch,
            repo_files=repo_files,
            applied_changes=applied_changes,
            diff=RepoDiffResponse(repo_id=repo.repo_id, diff=diff) if diff is not None else None,
            commit=commit,
            push=push,
            pull_request=pull_request,
        )
    except httpx.HTTPStatusError as exc:
        logger.warning("Service API request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Service API request failed.") from exc
    except HTTPException:
        raise
    except ValueError as exc:
        logger.warning("A2A workflow validation failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Ticket workflow failed")
        raise HTTPException(status_code=500, detail="Ticket workflow failed.") from exc