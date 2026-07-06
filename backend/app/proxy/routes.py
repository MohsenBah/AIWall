"""OpenAI-compatible proxy routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.proxy.chat import ChatCompletionProxy
from app.proxy.models import list_models

router = APIRouter(prefix="/v1", tags=["openai-compatible"])


@router.get("/models")
async def models(request: Request) -> dict[str, object]:
    return await list_models(
        request.app.state.config,
        request.app.state.http_client,
        request.app.state.cost_estimator,
    )


@router.post("/chat/completions")
async def chat_completions(request: Request):
    proxy = ChatCompletionProxy(
        request.app.state.config,
        request.app.state.http_client,
        request.app.state.audit_writer,
        request.app.state.policy_engine,
        request.app.state.cost_estimator,
    )
    return await proxy.forward(request)
