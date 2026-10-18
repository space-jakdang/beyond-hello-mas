from typing import Literal
from pydantic import BaseModel, ConfigDict


class Output(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Analysis(Output):
    summary: str
    causes: list[Literal['activity_deficit', 'school_gap', 'economic', 'housing', 'loneliness']]
    needs: list[Literal['relationship', 'emotional', 'employment', 'economic', 'housing', 'health']]
    review_required: bool


class Evidence(Output):
    field: str
    value: str


class Recommendation(Output):
    resource_id: str
    explanation: str
    evidence: list[Evidence]


class Recommendations(Output):
    items: list[Recommendation]


class Draft(Output):
    text: str
    resource_ids: list[str]


class Route(Output):
    route: Literal['classify', 'match', 'link', 'history', 'human']
    reason: str


SCHEMAS = {'analysis': Analysis, 'recommendations': Recommendations, 'draft': Draft, 'route': Route}

from backend.policy.agent import PolicyDecision
SCHEMAS["policy_decision"] = PolicyDecision
