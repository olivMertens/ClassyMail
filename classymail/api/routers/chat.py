from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from classymail.services.azure_clients import Clients, get_clients
from classymail.services.chat_agent import agent as chat_agent
# from classymail.core.rate_limit import limiter  # TODO: Re-enable for rate limiting
import json
import logging

router = APIRouter(tags=["chat"])
logger = logging.getLogger("ClassyMail.chat")


class ChatRequest(BaseModel):
    messages: list[dict]  # [{"role": "user", "content": "..."}]
    session_id: str | None = None
    locale: str = "en"


class ChatResponse(BaseModel):
    role: str
    content: str
    sources: list[dict] | None = None
    suggested_actions: list[str] | None = None


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

    response = await chat_agent.run(req.messages, clients=clients, session_id=req.session_id, locale=req.locale)
    return ChatResponse(
        role=response["role"],
        content=response["content"],
        sources=response.get("sources"),
        suggested_actions=response.get("suggested_actions"),
    )


def _sse_event(event_type: str | None, payload: dict) -> str:
    """Encode a payload as a Server-Sent Events frame.

    JSON-encoding escapes newlines/unicode so every ``data:`` stays single-line.
    """
    data = json.dumps(payload, ensure_ascii=False)
    if event_type:
        return f"event: {event_type}\ndata: {data}\n\n"
    return f"data: {data}\n\n"


@router.post("/api/chat/stream")
async def chat_completion_stream(
    req: ChatRequest,
    clients: Clients = Depends(get_clients),
):
    """Streaming (SSE) variant of /api/chat.

    Emits per-token ``data: {"delta": "..."}`` frames followed by a terminal
    ``event: done`` frame carrying the full clean content, sources and suggested
    actions. On failure an ``event: error`` frame is emitted. This endpoint is
    additive — the default-off ``CHAT_STREAMING`` flag gates whether the frontend
    uses it; /api/chat behaviour is unchanged.
    """
    if not req.messages:
        raise HTTPException(status_code=400, detail="Messages list cannot be empty")

    async def event_stream():
        try:
            async for evt in chat_agent.run_stream(
                req.messages, clients=clients, session_id=req.session_id, locale=req.locale
            ):
                etype = evt.get("type")
                if etype == "delta":
                    yield _sse_event(None, {"delta": evt.get("text", "")})
                elif etype == "done":
                    yield _sse_event("done", {
                        "content": evt.get("content", ""),
                        "sources": evt.get("sources") or [],
                        "suggested_actions": evt.get("suggested_actions") or [],
                    })
                elif etype == "error":
                    yield _sse_event("error", {"error": evt.get("message", "stream error")})
        except Exception as ex:  # pragma: no cover - defensive guard
            logger.error("Chat stream failed: %s", ex, exc_info=True)
            yield _sse_event("error", {"error": str(ex)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
