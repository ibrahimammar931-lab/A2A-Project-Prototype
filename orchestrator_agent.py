import json
import logging

import httpx
from fastapi import FastAPI, HTTPException

from config import (
    DEVELOPER_SERVICE_URL,
    JIRA_SERVICE_URL,
    REPO_SERVICE_URL,
    REVIEWER_SERVICE_URL,
    configure_logging,
)
from schemas import (
    AgentMessage,
    AgentTaskRequest,
    ApplyChangesRequest,
    BranchResponse,
    CommitRequest,
    CommitResponse,
    CreateBranchRequest,
    DeveloperOutput,
    GenerateRequest,
    GenerateResponse,
    JiraTicket,
    PrepareRepoRequest,
    PushRequest,
    PushResponse,
    PullRequestRequest,
    PullRequestResponse,
    ReadFilesRequest,
    ReadFilesResponse,
    RepoDiffRequest,
    RepoInfo,
    ReviewFeedback,
)

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Orchestrator Agent Service", version="1.0.0")


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


@app.post("/work-on-ticket", response_model=GenerateResponse)
async def work_on_ticket(request: GenerateRequest) -> GenerateResponse:
    messages: list[AgentMessage] = []
    repo: RepoInfo | None = None
    branch: BranchResponse | None = None
    repo_files = []

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            ticket_response = await client.get(
                f"{JIRA_SERVICE_URL}/tickets/{request.issue_key}"
            )
            ticket_response.raise_for_status()
            ticket = JiraTicket(**ticket_response.json())

            task = ticket_to_task(ticket)

            if request.files_to_read or request.repo_url:
                repo_response = await client.post(
                    f"{REPO_SERVICE_URL}/prepare-repo",
                    json=PrepareRepoRequest(repo_url=request.repo_url).model_dump(),
                )
                repo_response.raise_for_status()
                repo = RepoInfo(**repo_response.json())
                messages.append(
                    AgentMessage(
                        sender="orchestrator_agent",
                        receiver="repo_agent",
                        message_type="repo_prepared",
                        payload=repo.model_dump(),
                    )
                )

                branch_response = await client.post(
                    f"{REPO_SERVICE_URL}/create-branch",
                    json=CreateBranchRequest(
                        repo_url=repo.remote_url,
                        issue_key=ticket.key,
                        title=ticket.summary,
                        base_branch=request.base_branch,
                    ).model_dump(),
                )
                branch_response.raise_for_status()
                branch = BranchResponse(**branch_response.json())
                messages.append(
                    AgentMessage(
                        sender="orchestrator_agent",
                        receiver="repo_agent",
                        message_type="repo_branch_created",
                        payload=branch.model_dump(),
                    )
                )

                if request.files_to_read:
                    files_response = await client.post(
                        f"{REPO_SERVICE_URL}/read-files",
                        json=ReadFilesRequest(
                            repo_url=repo.remote_url,
                            paths=request.files_to_read,
                        ).model_dump(),
                    )
                    files_response.raise_for_status()
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

            generation_response = await client.post(
                f"{DEVELOPER_SERVICE_URL}/generate",
                json=AgentTaskRequest(
                    task=task,
                    ticket=ticket,
                    repo_files=repo_files,
                ).model_dump(),
            )
            generation_response.raise_for_status()
            original_output = DeveloperOutput(**generation_response.json())

            review_request = AgentMessage(
                sender="orchestrator_agent",
                receiver="reviewer_agent",
                message_type="code_review_request",
                payload={
                    "task": task,
                    "ticket": ticket.model_dump(),
                    "code": original_output.code,
                    "explanation": original_output.explanation,
                    "repo_files": [
                        repo_file.model_dump() for repo_file in repo_files
                    ],
                },
            )
            messages.append(review_request)

            reviewer_response = await client.post(
                f"{REVIEWER_SERVICE_URL}/review",
                json=review_request.model_dump(),
            )
            reviewer_response.raise_for_status()
            review_response = AgentMessage(**reviewer_response.json())
            messages.append(review_response)
            review_feedback = ReviewFeedback(**review_response.payload)

            improvement_request = AgentMessage(
                sender="orchestrator_agent",
                receiver="developer_agent",
                message_type="code_improvement_request",
                payload={
                    "task": task,
                    "ticket": ticket.model_dump(),
                    "original_code": original_output.code,
                    "review_feedback": review_feedback.model_dump(),
                    "repo_files": [
                        repo_file.model_dump() for repo_file in repo_files
                    ],
                },
            )
            messages.append(improvement_request)

            improvement_response = await client.post(
                f"{DEVELOPER_SERVICE_URL}/improve",
                json=improvement_request.model_dump(),
            )
            improvement_response.raise_for_status()
            improvement_message = AgentMessage(**improvement_response.json())
            messages.append(improvement_message)
            improved_output = DeveloperOutput(**improvement_message.payload)

            applied_changes: ApplyChangesResponse | None = None
            diff: str | None = None
            commit: CommitResponse | None = None
            push: PushResponse | None = None
            pull_request: PullRequestResponse | None = None

            if repo and branch and improved_output.changes:
                apply_changes_request = ApplyChangesRequest(
                    repo_url=repo.remote_url,
                    changes=[change.model_dump() for change in improved_output.changes],
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
                    apply_response = await client.post(
                        f"{REPO_SERVICE_URL}/apply-changes",
                        json=apply_changes_request.model_dump(),
                    )
                    apply_response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    detail = exc.response.text if exc.response is not None else str(exc)
                    raise HTTPException(
                        status_code=502,
                        detail=(
                            f"Repo apply-changes failed: {detail}\n"
                            f"Request: {apply_changes_request.model_dump_json()}"
                        ),
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

                diff_response = await client.post(
                    f"{REPO_SERVICE_URL}/diff",
                    json=RepoDiffRequest(repo_url=repo.remote_url).model_dump(),
                )
                diff_response.raise_for_status()
                diff = RepoDiffResponse(**diff_response.json()).diff
                messages.append(
                    AgentMessage(
                        sender="orchestrator_agent",
                        receiver="repo_agent",
                        message_type="repo_diff_generated",
                        payload={"repo_id": repo.repo_id, "diff": diff},
                    )
                )

                commit_response = await client.post(
                    f"{REPO_SERVICE_URL}/commit",
                    json=CommitRequest(
                        repo_url=repo.remote_url,
                        issue_key=ticket.key,
                        summary=ticket.summary,
                        body=ticket.description,
                    ).model_dump(),
                )
                commit_response.raise_for_status()
                commit = CommitResponse(**commit_response.json())
                messages.append(
                    AgentMessage(
                        sender="orchestrator_agent",
                        receiver="repo_agent",
                        message_type="repo_committed",
                        payload=commit.model_dump(),
                    )
                )

                push_response = await client.post(
                    f"{REPO_SERVICE_URL}/push",
                    json=PushRequest(repo_url=repo.remote_url, branch=branch.branch).model_dump(),
                )
                push_response.raise_for_status()
                push = PushResponse(**push_response.json())
                messages.append(
                    AgentMessage(
                        sender="orchestrator_agent",
                        receiver="repo_agent",
                        message_type="repo_pushed",
                        payload=push.model_dump(),
                    )
                )

                pr_response = await client.post(
                    f"{REPO_SERVICE_URL}/open-pr",
                    json=PullRequestRequest(
                        repo_url=repo.remote_url,
                        issue_key=ticket.key,
                        title=ticket.summary,
                        summary=ticket.description or "Pull request created by orchestrator.",
                        base_branch=request.base_branch,
                        head_branch=branch.branch,
                        ticket_url=ticket.url,
                    ).model_dump(),
                )
                pr_response.raise_for_status()
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
    except ValueError as exc:
        logger.warning("A2A workflow validation failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Ticket workflow failed")
        raise HTTPException(status_code=500, detail="Ticket workflow failed.") from exc
