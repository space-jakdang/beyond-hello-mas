import csv
import json
from pathlib import Path

from backend.app.contracts import Resource

JURISDICTIONS = {'KR', '11', '11230', '32', '32010'}


def validate_catalog(resources):
    ids = [r.id for r in resources]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate resource ID')
    versions = {r.catalog_version for r in resources}
    if len(versions) > 1:
        raise ValueError('mixed catalog versions')
    for resource in resources:
        if not set(resource.jurisdiction) <= JURISDICTIONS:
            raise ValueError(f'unknown jurisdiction: {resource.id}')
        if resource.valid_until and resource.valid_until < resource.collected_at.date():
            raise ValueError(f'valid_until precedes collection: {resource.id}')
    return sorted(resources, key=lambda r: r.id)


def load_catalog(path: Path):
    with path.open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        required = {name for name, field in Resource.model_fields.items() if field.is_required()}
        headers = reader.fieldnames or []
        if not required <= set(headers) or len(headers) != len(set(headers)):
            raise ValueError('missing or duplicate CSV columns')
        resources = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError('malformed CSV row')
            for name in ('jurisdiction', 'needs', 'eligibility_tags', 'provenance'):
                if name in row:
                    row[name] = json.loads(row[name])
            for name in ('valid_until','source_url','stage_min','stage_max'):
                if row.get(name) == '':row[name] = None
            resources.append(Resource.model_validate(row))
    return validate_catalog(resources)
