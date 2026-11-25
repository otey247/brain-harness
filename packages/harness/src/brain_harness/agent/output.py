"""Typed results: the answer the loop must end with, and a searcher's report."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Citation(BaseModel):
    path: str = Field(description="Bundle-relative path of the concept, as shown by the tools")
    start_line: int = Field(ge=1, description="First file line that supports the claim")
    end_line: int = Field(ge=1, description="Last file line that supports the claim")
    quote: str = Field(description="Short exact quote from those lines (under 200 characters)")
    claim: str = Field(description="The sentence in the answer this citation supports")


class ConceptUsed(BaseModel):
    path: str
    tier: str
    status: str
    stale: bool = False


class Answer(BaseModel):
    """Final output. The loop stops only when the model returns this."""

    answer: str = Field(description="Direct answer first, in plain sentences")
    citations: list[Citation] = Field(default_factory=list)
    concepts_used: list[ConceptUsed] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list, description="What the bundle does not answer")
    abstained: bool = Field(default=False, description="True when the bundle does not contain the answer")


class SearchReport(BaseModel):
    """What a searcher subagent hands back: findings, never its transcript."""

    sub_question: str
    findings: list[Citation] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
