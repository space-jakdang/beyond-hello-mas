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

from backend.agents.regional import RegionalPlan,RegionalReview
SCHEMAS.update(regional_analyst=RegionalPlan,regional_reviewer=RegionalReview)

from backend.agents.regional_worker import RegionalDecision
SCHEMAS["regional_worker"] = RegionalDecision

from backend.agents.regional_team import RegionalAudit
SCHEMAS.update(regional_planner=RegionalDecision, regional_audit=RegionalAudit)

from backend.agents.workflow import AnalystPlan,StatisticsDecision
from backend.agents.workflow_matching import MatchingPlan
SCHEMAS.update(workflow_analyst=AnalystPlan,workflow_statistics=StatisticsDecision,workflow_matching=MatchingPlan)
from backend.agents.workflow_single import SingleDecision
SCHEMAS['workflow_single']=SingleDecision

from backend.policy.designer import DesignDecision
SCHEMAS["policy_design"] = DesignDecision

from backend.policy.alternative_contracts import Alternatives
SCHEMAS['policy_alternatives']=Alternatives
