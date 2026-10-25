from datetime import date
from zoneinfo import ZoneInfo
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
    stage: int | None = Field(default=None, ge=1, le=5)
    arrears: bool = False
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


def filter_catalog(resources, request, *, regional_ages=None):
    if request.sgg not in {'11230', '32010'}:
        raise ValueError('unsupported jurisdiction')
    if request.age_min > request.age_max:
        raise ValueError('invalid requested age range')
    if regional_ages is not None and (not regional_ages or any(
            type(low) is not int or type(high) is not int or not request.age_min <= low <= high <= request.age_max
            for low, high in regional_ages)):
        raise ValueError('invalid regional age ranges')
    allowed = {'KR', request.sgg[:2], request.sgg}
    candidates, excluded, checks = [], [], {}
    for resource in validate_catalog(resources):
        reasons = []; conditions = {}; overlaps = []
        if not resource.active or (resource.valid_until and resource.valid_until < request.as_of):
            reasons.append('inactive_or_expired')
        if resource.collected_at.astimezone(ZoneInfo('Asia/Seoul')).date() > request.as_of:
            reasons.append('not_yet_collected')
        if not allowed.intersection(resource.jurisdiction):
            reasons.append('jurisdiction')
        if regional_ages is None:
            if resource.age_min > request.age_min or resource.age_max < request.age_max:
                reasons.append('age')
        else:
            overlaps = [(max(low, resource.age_min), min(high, resource.age_max))
                        for low, high in regional_ages if low <= resource.age_max and high >= resource.age_min]
            full_age = all(resource.age_min <= low and high <= resource.age_max for low, high in regional_ages)
            conditions['age'] = 'pass' if full_age else 'unknown' if overlaps else 'fail'
            if not overlaps:reasons.append('age')
        # Catalog stage ranges replace intensity in the personal policy.
        if regional_ages is not None:
            conditions['support_stage' if resource.stage_min is not None else 'support_intensity']='unknown'
        elif request.stage is not None and resource.stage_min is not None:
            if not resource.stage_min <= request.stage <= resource.stage_max:reasons.append('stage')
        elif resource.intensity != request.intensity:
            reasons.append('intensity')
        if not set(request.needs).intersection(resource.needs) and not (request.arrears and resource.arrears_link):
            reasons.append('needs')
        if not resource.eligibility_tags and resource.eligibility != 'unrestricted':
            if regional_ages is None:reasons.append('unstructured_eligibility')
            else:conditions['unstructured_eligibility'] = 'unknown'
        for tag in resource.eligibility_tags:
            value = request.eligibility.get(tag)
            if regional_ages is not None:
                conditions[f'eligibility:{tag}'] = 'pass' if value is True else 'fail' if value is False else 'unknown'
                if value is False:reasons.append(f'eligibility_mismatch:{tag}')
            elif value is not True:
                reasons.append(f'eligibility_unconfirmed:{tag}')
        if regional_ages is not None:
            unknown = sorted(key for key, value in conditions.items() if value == 'unknown')
            checks[resource.id] = {'candidate_status':'conditional' if unknown else 'matched',
                'condition_checks':conditions, 'unknown_conditions':unknown,
                'rank_factors':{'need_hypotheses_matched':len(set(request.needs).intersection(resource.needs)),
                                'unknown_conditions':len(unknown),'tie_breaker':'resource_id'},
                'age_coverage':'full' if conditions['age'] == 'pass' else 'partial' if overlaps else 'none',
                'eligible_age_ranges':overlaps}
        if reasons:
            excluded.append({'id': resource.id, 'reasons': reasons})
        else:
            candidates.append(resource)
    return candidates, excluded, checks


def rank(resources, request, checks=None):
    checks=checks or {}
    return sorted(resources, key=lambda r: (-int(request.arrears and r.arrears_link), -len(set(request.needs).intersection(r.needs)),
        len(checks.get(r.id,{}).get('unknown_conditions',[])),r.id))


def match(resources, request, policy=None, *, regional_ages=None):
    policy = policy or MatchPolicy(version='regional-candidates-3' if regional_ages is not None else
                                  'seohee-match-3' if request.stage is not None else 'provisional-1')
    candidates, excluded, checks = filter_catalog(resources, request, regional_ages=regional_ages)
    ranked = rank(candidates, request, checks)
    selected = ranked[:3]
    if request.arrears:
        arrears = next((r for r in ranked if r.arrears_link),None)
        ordinary = [r for r in ranked if set(request.needs).intersection(r.needs) and (arrears is None or r.id != arrears.id)]
        selected = ordinary[:2]+[arrears] if arrears else ordinary[:3]
    return {'recommendations': [{**r.model_dump(mode='json'), **checks.get(r.id, {})} for r in selected],
            'excluded': excluded, 'eligible_count': len(candidates), 'shortfall': 3 - len(selected),
            'uncovered_needs': sorted(set(request.needs) - {n for r in selected for n in r.needs}),
            'metadata': {'policy_version': policy.version, 'policy_hash': digest(policy.model_dump(mode='json')),
                         'catalog_version': resources[0].catalog_version if resources else None,
                         'catalog_hash': digest([r.model_dump(mode='json') for r in sorted(resources, key=lambda r: r.id)]),
                         'input_hash': digest(request.model_dump(mode='json') if regional_ages is None else
                                              {'request':request.model_dump(mode='json'),'regional_ages':regional_ages}), 'provisional': True}}
