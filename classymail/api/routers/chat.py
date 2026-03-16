from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from classymail.services.azure_clients import Clients, get_clients
from classymail.services.chat_agent import agent as chat_agent
# from classymail.core.rate_limit import limiter  # TODO: Re-enable for rate limiting
import logging

router = APIRouter(tags=["chat"])
logger = logging.getLogger("ClassyMail.chat")


class ChatRequest(BaseModel):
    messages: list[dict]  # [{"role": "user", "content": "..."}]
    session_id: str | None = None


class ChatResponse(BaseModel):
    role: str
    content: str
    sources: list[dict] | None = None


@router.post("/api/chat", response_model=ChatResponse)
# @limiter.limit("60/hour")  # TODO: Re-enable once slowapi integration is completed
async def chat_completion(
    req: ChatRequest,
    clients: Clients = Depends(get_clients),
):
    """
    Simple chatbot endpoint that uses Azure AI Inference SDK to answer questions
    and call tools (search_emails) if needed.
    """
    if not req.messages:
        raise HTTPException(status_code=400, detail="Messages list cannot be empty")

    response = await chat_agent.run(req.messages, clients=clients, session_id=req.session_id)
    return ChatResponse(role=response["role"], content=response["content"], sources=response.get("sources"))
