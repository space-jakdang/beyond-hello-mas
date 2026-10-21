"""Policy proposals are reviewable drafts, never existing benefits or allocations."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.tools.indicators import digest


class Contract(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,str_strip_whitespace=True)


class Gap(Contract):
    state:Literal['candidate_found','no_verified_candidates','search_incomplete']
    catalog_shortfall:int=Field(ge=0)
    search_scope:list[str]=Field(min_length=1)
    checked_at:str=Field(min_length=1)
    complete_within_scope:bool
    limitations:list[str]=Field(min_length=1)

    @model_validator(mode='after')
    def complete(self):
        if self.state=='no_verified_candidates' and not self.complete_within_scope:
            raise ValueError('incomplete search cannot establish a scoped gap')
        return self


class Analogue(Contract):
    policy_id:str=Field(min_length=1)
    title:str=Field(min_length=1)
    scope:str=Field(min_length=1)
    source_url:str=Field(min_length=1)
    checked_at:str=Field(min_length=1)
    fields:dict[str,str]
    local_eligibility:Literal['not_established']='not_established'


class Citation(Contract):
    policy_id:str=Field(min_length=1)
    field:Literal['title','support','eligibility','criteria','deadline']
    quote:str=Field(min_length=1)


class Adaptation(Contract):
    source_policy_ids:list[str]=Field(min_length=1,max_length=5)
    local_difference:str=Field(min_length=1)
    proposed_change:str=Field(min_length=1)
    verification_needed:list[str]=Field(min_length=1)


class EvaluationPlan(Contract):
    outcome:str=Field(min_length=1)
    baseline_needed:str=Field(min_length=1)
    comparison_method:str=Field(min_length=1)
    observation_period:str=Field(min_length=1)
    success_criterion_to_agree:str=Field(min_length=1)
    stop_criterion_to_agree:str=Field(min_length=1)


class PolicyDraft(Contract):
    status:Literal['draft','needs_evidence','needs_human']
    title:str=Field(min_length=1,max_length=200)
    problem_evidence_ids:list[str]=Field(min_length=1)
    target_group:str=Field(min_length=1)
    proposed_service:str=Field(min_length=1)
    adaptations:list[Adaptation]=Field(max_length=5)
    citations:list[Citation]=Field(max_length=15)
    operating_steps:list[str]=Field(min_length=1,max_length=10)
    required_roles:list[str]=Field(min_length=1,max_length=10)
    budget_confirmed:Literal[False]=False
    capacity_confirmed:Literal[False]=False
    legal_basis_confirmed:Literal[False]=False
    feasibility_checks:list[str]=Field(min_length=1)
    equity_risks:list[str]=Field(min_length=1)
    evaluation:EvaluationPlan
    reviewer_questions:list[str]=Field(min_length=1)
    allocation_performed:Literal[False]=False


def validate_draft(body,evidence_ids,gap,analogues):
    draft=PolicyDraft.model_validate(body);gap=Gap.model_validate(gap)
    sources=[Analogue.model_validate(a) for a in analogues]
    by_id={a.policy_id:a for a in sources}
    if len(by_id)!=len(sources):raise ValueError('duplicate analogue source')
    if not set(draft.problem_evidence_ids)<=set(evidence_ids):raise ValueError('unknown regional evidence')
    cited=set()
    for citation in draft.citations:
        source=by_id.get(citation.policy_id)
        actual=source.fields.get(citation.field) if source else None
        normalize=lambda text:text.replace('\r\n','\n').replace('\r','\n')
        if actual is None or normalize(actual)!=normalize(citation.quote):
            raise ValueError('citation differs from verified policy field')
        citation.quote=actual
        cited.add(citation.policy_id)
    for adaptation in draft.adaptations:
        if not set(adaptation.source_policy_ids)<=cited:raise ValueError('adaptation needs verified citations')
    if draft.status=='draft' and (gap.state!='no_verified_candidates' or not draft.adaptations):
        raise ValueError('draft requires scoped gap and cited analogue adaptation')
    result=draft.model_dump()
    return {'draft':result,'version':digest({'draft':result,'gap':gap.model_dump(),'analogues':[a.model_dump() for a in sources]}),
        'gap':gap.model_dump(),'analogues':[a.model_dump() for a in sources],
        'review_status':'pending','approval_meaning':'policy_review_only_not_budget_or_implementation',
        'all_policies_known':False,'human_review_required':True}
