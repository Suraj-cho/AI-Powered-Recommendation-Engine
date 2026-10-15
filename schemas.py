
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class RecommendationRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)


class FilterCondition(BaseModel):
    field: str = Field(min_length=1, max_length=100)
    operator: Literal[
        "eq", "contains", "gte", "lte", "gt", "lt", "in"
    ] = "eq"
    value: Any


class SearchFilters(BaseModel):
    category: Optional[str] = None
    constraints: list[FilterCondition] = Field(
        default_factory=list, max_length=20
    )
    preference_terms: list[str] = Field(
        default_factory=list, max_length=10
    )
    available_only: bool = True


class RecommendationResponse(BaseModel):
    query: str
    filters: dict
    recommendations: list[dict]
    message: str
