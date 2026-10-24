"""Offline acceptance of a private package with isolated disposable state (no paid calls)."""
import argparse
from datetime import date
import json
from pathlib import Path
import tempfile
from uuid import uuid4

from backend.app.config import Settings
from backend.app.contracts import Scenario
from backend.events import EventStore
from backend.graph import GraphService
from backend.future import FutureRequest, create_batch, future_router
from backend.tools.regional_task import RegionalTask, assess
from backend.tools.neighborhoods import group_analysis, boundaries
from scripts.runtime_package import verify


def check(root):
    root = Path(root).absolute()
    before = verify(root)
    results = []
    with tempfile.TemporaryDirectory(prefix='regional-acceptance-') as state:
        settings = Settings(_env_file=None, data_mode='local', input_root=root,
                            runtime_storage_root=Path(state), resource_catalog='v3',
                            llm_mode='fake', person_mcp_mode='stub', openai_api_key=None,
                            llm_max_calls=10, **{'GOV24_API_KEY': None})
        if settings.openai_api_key is not None or settings.gov24_service_key is not None or settings.llm_mode != 'fake' or settings.person_mcp_mode != 'stub':
            raise ValueError('offline acceptance must not inherit credentials or live mode')
        view = group_analysis(settings, week='all', card_age='all')
        if view['coverage']['unmatched_codes']:
            raise ValueError('unmatched real geography')
        expected = {f['properties']['dong_cd'] for f in boundaries()[0]['features']}
        if {r['dong_cd'] for r in view['neighborhoods']} != expected:
            raise ValueError('package does not cover all supplied neighborhood boundaries')
        preserved = {}
        service = GraphService(EventStore(settings.runtime_dir/'events.sqlite3', settings.data_mode), settings)
        future_router(service)
        day = date.today()
        for sgg in ('11230', '32010'):
            candidates = [r for r in view['segments'] if r['sgg'] == sgg and r['preferred']
                          and r['sex'] == 'M' and r['age_group'] == 'youth']
            if not candidates:
                raise ValueError('required regional baseline unavailable')
            row = sorted(candidates, key=lambda r: (r['dong_cd'], r['ym'] or ''))[-1]
            task = RegionalTask(sgg=sgg, dong_cd=row['dong_cd'], sex='M', age_group='youth',
                                ym=row['ym'] or day.strftime('%Y-%m'), as_of=day)
            scenario = Scenario(id=f'offline-private-acceptance-{sgg}', type='monthly',
                                sim_time=f'{day.isoformat()}T09:00:00+09:00',
                                payload={'workflow_version':'regional-workflow-1',
                                         'statistics_version':'2', 'policy_proposal_version':'three-1',
                                         'research_gaps':False, 'task':task.model_dump(mode='json')})
            run = service.start(scenario)
            if run.status != 'awaiting_approval':
                raise ValueError('regional flow did not reach human review')
            proposal = service.approval(run.id)
            preserved[run.id] = proposal
            if service.store.get_run(run.id).status != 'awaiting_approval':
                raise ValueError('proposal read unexpectedly advanced review')
            observed = assess(settings, task)
            saved = proposal['proposal']['assessment']
            if not saved['segments'] or saved['task'] != task.model_dump(mode='json') or saved['metadata']['input_hash'] != observed['metadata']['input_hash']:
                raise ValueError('workflow lost the requested input scope')
            restored = GraphService(EventStore(settings.runtime_dir/'events.sqlite3', settings.data_mode), settings)
            if restored.approval(run.id) != proposal:
                raise ValueError('stored proposal changed across service instances')
            future = create_batch(service, FutureRequest(request_id=uuid4(), sgg=sgg))
            future_task = RegionalTask(future_id=future['id'], sgg=sgg, sex='M', age_group='youth',
                                      ym=future['months'][0], as_of=future['as_of'])
            derived = assess(settings, future_task)
            if not derived['metadata']['synthetic_future']:
                raise ValueError('future scenario lost synthetic identity')
            if assess(settings, task)['metadata']['synthetic_future']:
                raise ValueError('observed input contaminated by future scenario')
            with service.store.connection() as db:
                if db.execute('SELECT count(*) FROM linkages').fetchone()[0]:
                    raise ValueError('offline check unexpectedly linked a resource')
            results.append({'sgg':sgg, 'human_review_reached':True,
                            'proposal_preserved':True, 'future_isolated':True})
        restored = GraphService(EventStore(settings.runtime_dir/'events.sqlite3', settings.data_mode), settings)
        if any(restored.approval(identifier) != proposal for identifier, proposal in preserved.items()):
            raise ValueError('another region changed a stored proposal')
        after = verify(root)
        if before != after:
            raise ValueError('input package changed during acceptance')
    return {'check':'offline-private-release-1', 'llm_mode':'fake', 'external_api_tested':False,
            'neighborhoods':view['coverage']['matched'], 'regions':results,
            'input_unchanged':True, 'state':'disposable',
            'not_verified':['live_api', 'policy_quality', 'production_restart', 'ux_m_integration']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.root), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
