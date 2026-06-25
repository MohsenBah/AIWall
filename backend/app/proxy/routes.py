"""OpenAI-compatible proxy routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.proxy.chat import ChatCompletionProxy

router = APIRouter(prefix="/v1", tags=["openai-compatible"])


@router.post("/chat/completions")
async def chat_completions(request: Request):
    proxy = ChatCompletionProxy(
        request.app.state.config,
        request.app.state.http_client,
        request.app.state.audit_writer,
    )
    return await proxy.forward(request)
