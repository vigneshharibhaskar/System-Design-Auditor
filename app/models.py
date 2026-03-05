from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    source_file: str
    page: int
    quote: str


class FindingItem(BaseModel):
    title: str
    severity: Literal["low", "medium", "high"]
    details: str
    impact: str
    evidence: list[EvidenceItem] = Field(default_factory=list)


class RecommendationItem(BaseModel):
    title: str
    effort: Literal["low", "medium", "high"]
    steps: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)


class TriageOutput(BaseModel):
    high_risk_areas: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    recommended_modules_to_run: list[str] = Field(default_factory=list)
    top_questions_for_author: list[str] = Field(default_factory=list)


class ModuleReviewOutput(BaseModel):
    score: float
    risk: Literal["low", "medium", "high"]
    findings: list[FindingItem] = Field(default_factory=list)
    recommendations: list[RecommendationItem] = Field(default_factory=list)
    questions_for_author: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    collection: str = "default"
    query: str = "Review this design for production readiness"
    mode: Literal["triage", "targeted", "deep"] = "triage"
    top_k: int = Field(default=6, ge=1, le=20)
    file_filter: str | None = None
    budget_modules: int = Field(default=3, ge=1, le=9)


class HealthResponse(BaseModel):
    status: str


class AnalyzeResponse(BaseModel):
    overall: dict
    triage: dict
    modules: dict
    meta: dict = Field(default_factory=dict)
