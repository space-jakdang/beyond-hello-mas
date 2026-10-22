"""Offline, source-reviewed manual curation. This does not claim human review or live extraction."""
from collections import Counter, defaultdict
import csv
import io
import json
from pathlib import Path
from urllib.parse import urlparse

from backend.app.contracts import Resource
from backend.tools.catalog import JURISDICTIONS, validate_catalog
from backend.tools.indicators import digest


def curate(entries):
    accepted, rejected, urls = [], [], defaultdict(list)
    ids = Counter(e.get('resource', {}).get('id') for e in entries)
    identities = Counter((e.get('resource', {}).get('name', '').strip(), tuple(e.get('resource', {}).get('jurisdiction', []))) for e in entries)
    for entry in entries:
        raw = entry.get('resource', {})
        try:
            if entry.get('status') != 'source_reviewed':
                raise ValueError('source review pending')
            resource = Resource.model_validate(raw)
            if ids[resource.id] > 1 or identities[(resource.name.strip(), tuple(resource.jurisdiction))] > 1:
                raise ValueError('duplicate ID or service identity')
            if not entry.get('reviewed_by') or not entry.get('field_notes'):
                raise ValueError('review evidence missing')
            required = {'eligibility', 'age', 'activity', 'delivery', 'mapping'}
            if not all(entry['field_notes'].get(f) for f in required):
                raise ValueError('field evidence missing')
            host = urlparse(str(resource.source_url)).hostname or ''
            if host.endswith('.invalid') or resource.id.startswith('synthetic-'):
                raise ValueError('synthetic resource in real catalog')
            if f'confirmed:{resource.id}' not in resource.eligibility_tags:
                raise ValueError('provider eligibility confirmation gate missing')
            validate_catalog([resource])
            accepted.append(resource)
            urls[str(resource.source_url)].append(resource.id)
        except (ValueError, TypeError) as exc:
            rejected.append({'id': raw.get('id'), 'error': str(exc)})
    accepted = validate_catalog(accepted)
    counts = Counter(code for r in accepted for code in r.jurisdiction)
    needs = Counter(need for r in accepted for need in r.needs)
    report = {'method': 'manual-source-review', 'human_reviewed': False, 'llm_calls': 0, 'llm_cost_usd': 0,
              'input_hash': digest(entries), 'catalog_hash': digest([r.model_dump(mode='json') for r in accepted]),
              'accepted_count': len(accepted), 'program_count': len({e.get('program', e['resource']['id']) for e in entries if e.get('resource', {}).get('id') in {r.id for r in accepted}}), 'rejected': rejected,
              'jurisdictions': {code: counts[code] for code in sorted(JURISDICTIONS)},
              'needs': dict(sorted(needs.items())), 'target_shortfall': max(0,30-len(accepted)),
              'shared_source_urls': {url: ids for url,ids in urls.items() if len(ids)>1}}
    return accepted, report


def export(entries, destination: Path):
    resources, report = curate(entries)
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(Resource.model_fields))
    writer.writeheader()
    for resource in resources:
        row = resource.model_dump(mode='json')
        for field in ('jurisdiction', 'needs', 'eligibility_tags', 'provenance'):
            row[field] = json.dumps(row[field], ensure_ascii=False)
        writer.writerow(row)
    outputs = {'resources.csv': stream.getvalue(), 'manifest.json': json.dumps(report, ensure_ascii=False, indent=2)+'\n'}
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in outputs.items():
        path = destination/name
        if path.exists() and path.read_text() != content.replace('\r\n','\n'):
            raise ValueError('catalog version output already exists with different contents')
    for name, content in outputs.items():
        path = destination/name
        if not path.exists():
            with path.open('x', newline='', encoding='utf-8') as output:
                output.write(content)
    return report
