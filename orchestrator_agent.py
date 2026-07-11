import asyncio
import json
import logging
from difflib import unified_diff

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# WebSocket connection manager for live dashboard updates
# ---------------------------------------------------------------------------
class ConnectionManager:
    """Manages active WebSocket connections and broadcasts events."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)
        logger.info("WebSocket client connected (%d total)", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.remove(websocket)
        logger.info("WebSocket client disconnected (%d remaining)", len(self._connections))

    async def broadcast(self, event: dict) -> None:
        """Send a JSON event to all connected WebSocket clients."""
        message = json.dumps(event, default=str)
        stale: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        # Keep the connection open; the client may send pings
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


def broadcast_event(event_type: str, agent: str | None = None, **extra: object) -> None:
    """Fire-and-forget helper to broadcast a pipeline event to all WS clients."""
    event: dict = {"type": event_type, "timestamp": __import__("datetime").datetime.now().isoformat()}
    if agent is not None:
        event["agent"] = agent
    event.update(extra)
    asyncio.ensure_future(manager.broadcast(event))


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


@app.post("/work-on-ticket", response_model=GenerateResponse)
async def work_on_ticket(request: GenerateRequest) -> GenerateResponse:
    messages: list[AgentMessage] = []
    repo: RepoInfo | None = None
    branch: BranchResponse | None = None
    repo_files = []
    planning_result: PlanningResult | None = None

    broadcast_event("workflow_started", message=f"Workflow started for {request.issue_key}")

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            ticket_response = await client.get(
                f"{JIRA_SERVICE_URL}/tickets/{request.issue_key}"
            )
            ticket_response.raise_for_status()
            ticket = JiraTicket(**ticket_response.json())

            task = ticket_to_task(ticket)

            broadcast_event("agent_started", agent="repo_agent", message="Preparing repository...")
            repo_response = await post_or_raise(
                client,
                f"{REPO_SERVICE_URL}/prepare-repo",
                PrepareRepoRequest().model_dump(),
                "Repo prepare",
            )
            repo = RepoInfo(**repo_response.json())
            broadcast_event("agent_completed", agent="repo_agent", message="Repository prepared")
            messages.append(
                AgentMessage(
                    sender="orchestrator_agent",
                    receiver="repo_agent",
                    message_type="repo_prepared",
                    payload=repo.model_dump(),
                )
            )

            broadcast_event("agent_started", agent="knowledge_agent", message="Ensuring knowledge base...")
            knowledge_response = await post_or_raise(
                client,
                f"{KNOWLEDGE_SERVICE_URL}/ensure-knowledge",
                {"repository_path": repo.path},
                "Knowledge ensure",
            )
            knowledge = knowledge_response.json()
            broadcast_event("agent_completed", agent="knowledge_agent", message="Knowledge base ready")
            messages.append(
                AgentMessage(
                    sender="orchestrator_agent",
                    receiver="knowledge_agent",
                    message_type="knowledge_ensured",
                    payload=knowledge,
                )
            )

            broadcast_event("agent_started", agent="planner_agent", message="Planning...")
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
            broadcast_event("agent_completed", agent="planner_agent", message="Planning completed")
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

            broadcast_event("agent_started", agent="repo_agent", message="Creating branch...")
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
            broadcast_event("agent_completed", agent="repo_agent", message=f"Branch {branch.branch} created")
            messages.append(
                AgentMessage(
                    sender="orchestrator_agent",
                    receiver="repo_agent",
                    message_type="repo_branch_created",
                    payload=branch.model_dump(),
                )
            )

            if planned_existing_files:
                broadcast_event("agent_started", agent="repo_agent", message="Reading existing files...")
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
                broadcast_event("agent_completed", agent="repo_agent", message=f"Read {len(repo_files)} files")
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

            broadcast_event("agent_started", agent="developer_agent", message="Generating code...")
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
            validate_planned_changes(original_output, repo_files)
            broadcast_event("agent_completed", agent="developer_agent", message="Code generated")

            broadcast_event("agent_started", agent="reviewer_agent", message="Reviewing code...")
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
            broadcast_event("agent_completed", agent="reviewer_agent", message="Review completed")

            should_regenerate = bool(review_feedback.requires_revision and review_feedback.blocking_issues)

            if should_regenerate:
                broadcast_event("agent_started", agent="developer_agent", message="Improving code based on review...")
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
                validate_planned_changes(improved_output, repo_files)
                broadcast_event("agent_completed", agent="developer_agent", message="Code improved")
            else:
                improved_output = original_output

            applied_changes: ApplyChangesResponse | None = None
            diff: str | None = None
            commit: CommitResponse | None = None
            push: PushResponse | None = None
            pull_request: PullRequestResponse | None = None

            if repo and branch and improved_output.changes:
                broadcast_event("agent_started", agent="repo_agent", message="Applying changes...")
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
                broadcast_event("agent_completed", agent="repo_agent", message="Changes applied")
                messages.append(
                    AgentMessage(
                        sender="orchestrator_agent",
                        receiver="repo_agent",
                        message_type="repo_changes_applied",
                        payload=applied_changes.model_dump(),
                    )
                )

                broadcast_event("agent_started", agent="knowledge_agent", message="Updating knowledge base...")
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
                broadcast_event("agent_completed", agent="knowledge_agent", message="Knowledge base updated")
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

                broadcast_event("agent_started", agent="repo_agent", message="Opening pull request...")
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
                broadcast_event("agent_completed", agent="repo_agent", message=f"PR #{pull_request.number} opened")
                messages.append(
                    AgentMessage(
                        sender="orchestrator_agent",
                        receiver="repo_agent",
                        message_type="repo_pr_opened",
                        payload=pull_request.model_dump(),
                    )
                )

        broadcast_event("pipeline_finished", message="Pipeline completed successfully")
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
        broadcast_event("pipeline_failed", message=f"Service API request failed: {exc}")
        raise HTTPException(status_code=502, detail="Service API request failed.") from exc
    except HTTPException:
        broadcast_event("pipeline_failed", message="HTTP error during pipeline execution")
        raise
    except ValueError as exc:
        logger.warning("A2A workflow validation failed: %s", exc)
        broadcast_event("pipeline_failed", message=f"Validation failed: {exc}")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Ticket workflow failed")
        broadcast_event("pipeline_failed", message=f"Pipeline failed: {exc}")
        raise HTTPException(status_code=500, detail="Ticket workflow failed.") from exc
