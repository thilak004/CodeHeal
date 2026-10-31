"""Optional FastAPI adapter for read-only/proposal-only review operations."""
from __future__ import annotations

from typing import Any

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover - exercised when optional dependency is absent
    FastAPI = None
    BaseModel = object
    Field = None
    HTTPException = RuntimeError

from agent import fix_code
from languages import detect_language
from review import review_source
from test_generation import generate_tests

MAX_API_SOURCE_BYTES = 512 * 1024


if FastAPI is not None:

    class ReviewRequest(BaseModel):
        source: str = Field(..., max_length=MAX_API_SOURCE_BYTES)
        filename: str = Field(default="code.py", max_length=255)
        mode: str = Field(default="review_quality", max_length=32)
        provider: str | None = Field(default=None, max_length=16)


if FastAPI is not None:
    app = FastAPI(title="AI Code Reviewer API", version="1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/review")
    def review(request: ReviewRequest) -> dict[str, Any]:
        if detect_language(request.filename) is None:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {request.filename}")
        if request.mode == "fix_syntax":
            return fix_code(
                request.source,
                request.filename,
                provider_name=request.provider,
                include_explanation=False,
            )
        if request.mode == "tests":
            return generate_tests(request.source, request.filename, provider_name=request.provider)
        result = review_source(
            request.source,
            request.filename,
            request.mode,
            provider_name=request.provider,
        )
        if result.get("status") == "failed":
            raise HTTPException(status_code=400, detail=result.get("error", "Review failed."))
        return result
else:
    app = None


def create_app() -> Any:
    """Return the FastAPI app or explain that the optional dependency is absent."""
    if app is None:
        raise RuntimeError("FastAPI is not installed. Install the optional API dependencies first.")
    return app
