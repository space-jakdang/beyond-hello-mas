"""Three reviewable alternatives; never an entitlement or an allocation."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from backend.policy.design_contracts import Adaptation, Citation, EvaluationPlan


class Alternative(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    strategy:Literal['outreach','integrated_support','pilot']
    title:str=Field(min_length=1,max_length=150)
    target_groups:list[str]=Field(min_length=1,max_length=8)
    problem_evidence_ids:list[str]=Field(max_length=24)
    source_policy_ids:list[str]=Field(max_length=5)
    rationale:str=Field(min_length=1,max_length=600)
    proposed_service:str=Field(min_length=1,max_length=800)
    operating_steps:list[str]=Field(min_length=1,max_length=5)
    required_roles:list[str]=Field(min_length=1,max_length=5)
    budget_questions:list[str]=Field(min_length=1,max_length=5)
    equity_risks:list[str]=Field(min_length=1,max_length=5)
    evaluation_plan:str=Field(min_length=1,max_length=600)
    adaptations:list[Adaptation]=Field(default_factory=list,max_length=3)
    source_elements:list[Citation]=Field(default_factory=list,max_length=5)
    evaluation_design:EvaluationPlan | None = None
    missing_evidence:list[str]=Field(min_length=1,max_length=8)


class Alternatives(BaseModel):
    model_config=ConfigDict(extra='forbid')
    alternatives:list[Alternative]=Field(min_length=3,max_length=3)
