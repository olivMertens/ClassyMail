from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from classificationg2s.services.azure_clients import Clients, get_clients
from classificationg2s.services.chat_agent import agent as chat_agent
import logging

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = logging.getLogger("classimail.chat")


class ChatRequest(BaseModel):
    messages: list[dict]  # [{"role": "user", "content": "..."}]


class ChatResponse(BaseModel):
    role: str
    content: str


@router.post("/", response_model=ChatResponse)
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

    response = await chat_agent.run(req.messages, clients=clients)
    return ChatResponse(role=response["role"], content=response["content"])
