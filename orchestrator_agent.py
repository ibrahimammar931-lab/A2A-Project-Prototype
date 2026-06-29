import json
import logging

import httpx
from fastapi import FastAPI, HTTPException

from config import (
    DEVELOPER_SERVICE_URL,
    JIRA_SERVICE_URL,
    REVIEWER_SERVICE_URL,
    configure_logging,
)
from schemas import (
    AgentMessage,
    AgentTaskRequest,
    DeveloperOutput,
    GenerateRequest,
    GenerateResponse,
    JiraTicket,
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

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            ticket_response = await client.get(
                f"{JIRA_SERVICE_URL}/tickets/{request.issue_key}"
            )
            ticket_response.raise_for_status()
            ticket = JiraTicket(**ticket_response.json())

            task = ticket_to_task(ticket)
            generation_response = await client.post(
                f"{DEVELOPER_SERVICE_URL}/generate",
                json=AgentTaskRequest(task=task, ticket=ticket).model_dump(),
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

        return GenerateResponse(
            ticket=ticket,
            original_code=original_output,
            review_feedback=review_feedback,
            improved_code=improved_output,
            messages=messages,
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
