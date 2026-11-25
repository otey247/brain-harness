"""HTTP API (FastAPI). Install the ``api`` extra.

POST /ask        {"question": "..."}           -> Answer
GET  /tools/{name}?...                         -> one read primitive
GET  /healthz
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from brain_harness.agent.loop import Harness
from brain_harness.agent.output import Answer
from brain_harness.tools.knowledge import ToolError

TOOL_NAMES = {"list", "glob", "grep", "read", "frontmatter_query", "links", "search"}


class AskRequest(BaseModel):
    question: str


def create_app(harness: Harness) -> Any:
    from fastapi import FastAPI, HTTPException, Request

    app = FastAPI(title="brain-harness", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"ok": True, "bundle": harness.bundle_name, "concepts": len(harness.bundle.concepts)}

    @app.post("/ask", response_model=Answer)
    async def ask(body: AskRequest) -> Answer:
        result = await harness.ask(body.question)
        return result.answer

    @app.get("/tools/{name}")
    def tool(name: str, request: Request) -> dict[str, str]:
        if name not in TOOL_NAMES:
            raise HTTPException(404, f"unknown tool {name}")
        kwargs = dict(request.query_params)
        for key in ("offset", "limit", "context", "depth", "k", "head_limit"):
            if key in kwargs:
                kwargs[key] = int(kwargs[key])  # type: ignore[assignment]
        try:
            return {"result": getattr(harness.tools(), name)(**kwargs)}
        except (ToolError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    return app
