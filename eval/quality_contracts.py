"""Frozen evaluation inputs and private reference labels, independent of inference."""
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.tools.indicators import digest
from eval.rate_comparison import Reviewer as ComparisonReviewer


class Reviewer(ComparisonReviewer):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)


class Case(Contract):
    id: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    region: str = Field(min_length=1)
    neighborhood: str = Field(min_length=1)
    cohort: str = Field(min_length=1)
    period: str = Field(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
    methodology: str = Field(min_length=1)
    split: Literal['dev', 'calibration', 'test']
    source: Literal['observed', 'synthetic']
    policy_as_of: str
    facts: dict
    policies: dict[str, dict]

    @model_validator(mode='after')
    def valid_date(self):
        date.fromisoformat(self.policy_as_of)
        if any(not key.strip() for key in self.policies):
            raise ValueError('empty policy ID')
        return self


class Dataset(Contract):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    cases: list[Case] = Field(min_length=1)

    @model_validator(mode='after')
    def unique_and_isolated(self):
        ids = set()
        families = {}
        units = set()
        for case in self.cases:
            unit = (case.neighborhood, case.region, case.cohort, case.period, case.methodology)
            if case.id in ids or unit in units:
                raise ValueError('duplicate case or observation unit')
            ids.add(case.id)
            units.add(unit)
            if case.family_id in families and families[case.family_id] != case.split:
                raise ValueError('source family crosses evaluation splits')
            families[case.family_id] = case.split
        return self


class Judgment(Contract):
    case_id: str = Field(min_length=1)
    policy_id: str | None = None  # None identifies the regional grade task.
    reviewer: str = Field(min_length=1)
    value: Literal['1', '2', '3', '4', '5', 'suitable', 'conditional', 'unsuitable', 'unknown']
    reason: str = Field(min_length=1)
    reviewed_at: str
    provenance: Literal['independent_review', 'rule_oracle', 'observed_outcome', 'synthetic_reference']
    policy_as_of: str
    adjudication: bool = False

    @model_validator(mode='after')
    def valid_value(self):
        allowed = {'1', '2', '3', '4', '5', 'unknown'} if self.policy_id is None else {'suitable', 'conditional', 'unsuitable', 'unknown'}
        if self.value not in allowed:
            raise ValueError('label does not match task')
        date.fromisoformat(self.reviewed_at)
        date.fromisoformat(self.policy_as_of)
        return self


class Labels(Contract):
    dataset_hash: str
    reviewers: list[Reviewer]
    judgments: list[Judgment]


def freeze(dataset):
    dataset = Dataset.model_validate(dataset)
    body = dataset.model_dump()
    return {'schema_version': '6', 'dataset_hash': digest(body), 'dataset': body}


def load_frozen(body):
    if set(body) != {'schema_version', 'dataset_hash', 'dataset'} or body['schema_version'] != '6':
        raise ValueError('invalid frozen dataset envelope')
    frozen = freeze(body['dataset'])
    if frozen != body:
        raise ValueError('frozen dataset changed')
    return Dataset.model_validate(body['dataset'])


def stage_scope(case):
    assessment=case.facts.get('assessment') or {}
    return next((r.get('stage_scale') for r in assessment.get('segments',[]) if r.get('evidence_id')==case.facts.get('evidence_id')),None)


def resolve_labels(frozen, labels):
    """Resolve only agreed or separately adjudicated labels; preserve missingness."""
    dataset = load_frozen(frozen)
    labels = Labels.model_validate(labels)
    if labels.dataset_hash != frozen['dataset_hash']:
        raise ValueError('labels refer to a different dataset')
    reviewers = {r.id: r for r in labels.reviewers}
    if len(reviewers) != len(labels.reviewers):
        raise ValueError('duplicate reviewer')
    cases = {c.id: c for c in dataset.cases}
    grouped = {}
    seen = set()
    for row in labels.judgments:
        case = cases.get(row.case_id)
        if case is None or row.reviewer not in reviewers or (row.policy_id is not None and row.policy_id not in case.policies):
            raise ValueError('unknown case, reviewer or policy ID')
        if row.policy_as_of != case.policy_as_of:
            raise ValueError('policy snapshot date mismatch')
        if row.provenance == 'independent_review' and reviewers[row.reviewer].development_participant:
            raise ValueError('developer rating cannot be independent_review')
        if case.source == 'synthetic' and row.provenance == 'observed_outcome':
            raise ValueError('synthetic case cannot have observed outcome reference')
        key = (row.case_id, row.policy_id)
        pair = (*key, row.reviewer)
        if pair in seen:
            raise ValueError('duplicate rating or adjudicator is an original reviewer')
        seen.add(pair)
        grouped.setdefault(key, []).append(row)
    resolved = []
    for case in dataset.cases:
        for policy_id in [None, *case.policies]:
            rows = grouped.get((case.id, policy_id), [])
            ratings = [r for r in rows if not r.adjudication]
            adjudications = [r for r in rows if r.adjudication]
            disagreement = len({r.value for r in ratings}) > 1
            if len(adjudications) > 1 or (adjudications and (len(ratings) < 2 or not disagreement)):
                raise ValueError('adjudication requires disagreement between at least two reviewers')
            chosen = adjudications[0] if adjudications else (ratings[0] if ratings and not disagreement else None)
            independent = (chosen is not None and len(ratings) >= 2
                and all(r.provenance == 'independent_review' for r in rows))
            state = 'missing' if not rows else 'disagreement' if chosen is None else 'unknown' if chosen.value == 'unknown' else 'resolved'
            resolved.append({'case_id': case.id, 'policy_id': policy_id, 'state': state,
                'value': chosen.value if chosen else None, 'independent': independent,
                'review_count': len(ratings), 'adjudicated': bool(adjudications),
                'provenance': sorted({r.provenance for r in rows})})
    return {'dataset_hash': frozen['dataset_hash'], 'label_hash': digest(labels.model_dump()), 'references': resolved}


def readiness_report(frozen, labels):
    resolved = resolve_labels(frozen, labels)
    refs = resolved['references']
    return {'schema_version': '6', **resolved,
        'status': 'not_evaluated', 'metrics': None,
        'readiness': {'reference_items': len(refs), 'missing': sum(r['state'] == 'missing' for r in refs),
            'unknown': sum(r['state'] == 'unknown' for r in refs),
            'disagreements': sum(r['state'] == 'disagreement' for r in refs),
            'independent_resolved': sum(r['independent'] and r['state'] == 'resolved' for r in refs)},
        'reason': 'Reference readiness only; no predictions have been evaluated.'}


def blind_packet(frozen):
    """Hide case/split identifiers from raters; input wording can still identify places."""
    from uuid import uuid4
    dataset = load_frozen(frozen)
    import random
    items = []
    mapping = {}
    cases = list(dataset.cases)
    random.SystemRandom().shuffle(cases)
    for case in cases:
        blind_id = str(uuid4())
        mapping[blind_id] = case.id
        items.append({'blind_id': blind_id, 'source': case.source, 'period': case.period,
            'methodology': case.methodology, 'policy_as_of': case.policy_as_of,
            'facts': case.facts, 'policies': case.policies})
    packet = {'dataset_hash': frozen['dataset_hash'], 'items': items,
        'limitations': ['Input wording may identify regions; this is not guaranteed anonymity.']}
    return packet, {'dataset_hash': frozen['dataset_hash'], 'mapping': mapping}


def unblind_judgments(frozen, key, judgments):
    dataset = load_frozen(frozen)
    mapping = key.get('mapping', {})
    if (set(key) != {'dataset_hash', 'mapping'} or key['dataset_hash'] != frozen['dataset_hash']
            or len(mapping) != len(dataset.cases) or set(mapping.values()) != {c.id for c in dataset.cases}):
        raise ValueError('invalid blinding key or dataset mismatch')
    result = []
    for row in judgments:
        if row.get('case_id') not in mapping:
            raise ValueError('unknown blind case ID')
        result.append({**row, 'case_id': mapping[row['case_id']]})
    return result
