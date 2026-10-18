from datetime import date
from typing import Literal

from pydantic import Field
from backend.app.contracts import Contract, District, Nonempty
from backend.tools.catalog import validate_catalog
from backend.tools.indicators import digest


class MatchRequest(Contract):
    sgg: District
    age_min: int = Field(ge=0, le=120)
    age_max: int = Field(ge=0, le=120)
    needs: list[Nonempty] = Field(min_length=1)
    intensity: Literal['low', 'medium', 'high']
    eligibility: dict[str, bool | None] = Field(default_factory=dict)
    as_of: date


class MatchPolicy(Contract):
    version: Nonempty = 'provisional-1'
    stage_intensity: dict[int, Literal['low', 'medium', 'high']] = Field(
        default_factory=lambda: {1: 'low', 2: 'low', 3: 'medium', 4: 'high', 5: 'high'})
    cause_needs: dict[str, list[str]] = Field(default_factory=lambda: {
        'activity_deficit': ['relationship'], 'school_gap': ['relationship', 'employment'],
        'economic': ['economic'], 'housing': ['housing'], 'loneliness': ['emotional', 'relationship']})


def map_needs(causes, policy=None):
    policy = policy or MatchPolicy()
    return sorted({need for cause in causes for need in policy.cause_needs.get(cause, [])})


def map_intensity(stage, policy=None):
    return (policy or MatchPolicy()).stage_intensity.get(stage)


def filter_catalog(resources, request):
    if request.sgg not in {'11230', '32010'}:
        raise ValueError('unsupported jurisdiction')
    if request.age_min > request.age_max:
        raise ValueError('invalid requested age range')
    allowed = {'KR', request.sgg[:2], request.sgg}
    candidates, excluded = [], []
    for resource in validate_catalog(resources):
        reasons = []
        if not resource.active or (resource.valid_until and resource.valid_until < request.as_of):
            reasons.append('inactive_or_expired')
        if resource.collected_at.date() > request.as_of:
            reasons.append('not_yet_collected')
        if not allowed.intersection(resource.jurisdiction):
            reasons.append('jurisdiction')
        if resource.age_min > request.age_min or resource.age_max < request.age_max:
            reasons.append('age')
        if resource.intensity != request.intensity:
            reasons.append('intensity')
        if not set(request.needs).intersection(resource.needs):
            reasons.append('needs')
        if not resource.eligibility_tags and resource.eligibility != 'unrestricted':
            reasons.append('unstructured_eligibility')
        for tag in resource.eligibility_tags:
            if request.eligibility.get(tag) is not True:
                reasons.append(f'eligibility_unconfirmed:{tag}')
        if reasons:
            excluded.append({'id': resource.id, 'reasons': reasons})
        else:
            candidates.append(resource)
    return candidates, excluded


def rank(resources, request):
    return sorted(resources, key=lambda r: (-len(set(request.needs).intersection(r.needs)), r.id))


def match(resources, request, policy=None):
    policy = policy or MatchPolicy()
    candidates, excluded = filter_catalog(resources, request)
    selected = rank(candidates, request)[:3]
    return {'recommendations': [r.model_dump(mode='json') for r in selected],
            'excluded': excluded, 'eligible_count': len(candidates), 'shortfall': 3 - len(selected),
            'uncovered_needs': sorted(set(request.needs) - {n for r in selected for n in r.needs}),
            'metadata': {'policy_version': policy.version, 'policy_hash': digest(policy.model_dump(mode='json')),
                         'catalog_version': resources[0].catalog_version if resources else None,
                         'catalog_hash': digest([r.model_dump(mode='json') for r in sorted(resources, key=lambda r: r.id)]),
                         'input_hash': digest(request.model_dump(mode='json')), 'provisional': True}}
