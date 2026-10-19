"""Single regional agent with bounded evidence lookup and self-review."""
from copy import deepcopy
import time
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.agents.regional import RegionalPlan, issues


class RegionalDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['lookup', 'finish', 'human']
    targets: list[str] = Field(max_length=4)
    reason: str = Field(min_length=1, max_length=1000)
    plan: RegionalPlan | None

    @model_validator(mode='after')
    def shape(self):
        if self.action == 'lookup' and (not self.targets or self.plan is not None):
            raise ValueError('lookup requires targets and no plan')
        if self.action != 'lookup' and self.targets:
            raise ValueError('only lookup has targets')
        if (self.action == 'finish') != (self.plan is not None):
            raise ValueError('only finish requires a plan')
        return self


def lookup(observations, snapshots, targets):
    allowed = {r['id'] for r in observations['facts']}
    if not targets or len(targets) > 4 or len(set(targets)) != len(targets) or not set(targets) <= allowed:
        raise ValueError('lookup targets must be unique observed cohort IDs')
    return [{'target': target, 'status': 'available' if target in snapshots else 'unavailable',
             'evidence': deepcopy(snapshots.get(target))} for target in targets]


def single(agents, run_id, sim_ts, observations, snapshots, emit, max_calls=6, timeout_seconds=120):
    observations = deepcopy(observations); retrieved = []; proposals = []; feedback = []; previous = None
    started = time.monotonic()
    for step in range(1, max_calls + 1):
        if time.monotonic() - started >= timeout_seconds:
            return {'status': 'needs_human', 'plan': None, 'reason': 'deadline', 'proposals': proposals, 'retrieved': retrieved}
        try:
            decision = agents.call(run_id, sim_ts, 'regional_worker', {
                'observations': observations, 'retrieved': retrieved, 'previous_plan': previous,
                'feedback': feedback, 'step': step, 'remaining_calls': max_calls-step,
                'self_review_required': True}).model_dump()
            emit(f'single-{step}', 'regional_analyst', 'supervisor', decision)
            if time.monotonic() - started >= timeout_seconds:
                return {'status': 'needs_human', 'plan': None, 'reason': 'deadline', 'proposals': proposals, 'retrieved': retrieved}
            if decision['action'] == 'human':
                return {'status': 'needs_human', 'plan': None, 'reason': decision['reason'], 'proposals': proposals, 'retrieved': retrieved}
            if decision['action'] == 'lookup':
                result = lookup(observations, snapshots, decision['targets']); retrieved.extend(result)
                emit(f'lookup-{step}', 'supervisor', 'regional_analyst', {'results': result})
                feedback = ['Use returned evidence, and self-review any subsequent plan.']
                # New evidence requires a fresh proposal before the final self-review.
                previous = None
                continue
            plan = decision['plan']; checks = issues(plan, observations)
            has_previous = previous is not None
            proposals.append(plan); previous = plan
            if not checks and has_previous:
                return {'status': 'submitted', 'plan': plan, 'proposals': proposals, 'retrieved': retrieved,
                        'human_review_required': True}
            feedback = checks or ['Self-review your proposal against observations and retrieved evidence before finishing.']
        except Exception as exc:
            return {'status': 'needs_human', 'plan': None, 'reason': type(exc).__name__, 'proposals': proposals, 'retrieved': retrieved}
    return {'status': 'needs_human', 'plan': None, 'reason': 'call_limit', 'proposals': proposals, 'retrieved': retrieved}


def deterministic(observations):
    ids = [r['id'] for r in observations['facts'] if r.get('stage') is not None][:3]
    if not ids:
        return {'status': 'needs_human', 'plan': None, 'reason': 'no_classified_cohorts'}
    return {'status': 'submitted', 'plan': {'summary': '결정적 도구의 후보 집단입니다. 담당자가 근거와 자격을 확인해야 합니다.',
        'focus_ids': ids, 'limitations': list(observations['required_limitations'])}, 'human_review_required': True}
