import pytest
from eval.run_comparison import run
from eval.rate_comparison import packet,aggregate


def test_blinding_missing_and_disagreement_preserved():
    report=run('dev');public,key=packet(report)
    assert all('method' not in item and 'calls' not in item for item in public['items'])
    empty=aggregate(report,key,{'reviewers':[],'ratings':[]})
    assert len(empty['missing'])==16 and empty['metrics'] is None
    assert empty['adoption_decision']=='not_evaluated'
    reviewers=[{'id':id,'expertise':'fixture','development_participant':False} for id in ('a','b')]
    def rating(blind_id,reviewer,executable):
        return {'blind_id':blind_id,'reviewer':reviewer,'executable':executable,'major_errors':[], 'reason':'fixture',
                'supported_claims':0,'reviewed_claims':0,'omitted_constraints':False,'appropriate_hold':None,
                'excessive_hold':False,'edits':None,'task_seconds':None}
    rows=[rating(id,r,True) for id in key['mapping'] for r in ('a','b')]
    rows[0]['executable']=False
    output=aggregate(report,key,{'reviewers':reviewers,'ratings':rows})
    assert len(output['disagreements'])==1 and output['metrics'] is None
    with pytest.raises(ValueError,match='duplicate'):aggregate(report,key,{'reviewers':reviewers,'ratings':rows+[rows[0]]})
    rows[0]['executable']=True
    output=aggregate(report,key,{'reviewers':reviewers,'ratings':rows})
    assert output['metrics'] is not None and output['adoption_decision']=='not_evaluated'
    report['status']='tampered'
    with pytest.raises(ValueError,match='changed'):aggregate(report,key,{'reviewers':[],'ratings':[]})


def test_study_pairs_repeats_without_inflating_cases():
    report=run('dev',study=True)
    assert report['case_count']==8 and report['repetitions']==3
    assert len(report['results'])==72
    for case in {r['case_id'] for r in report['results']}:
        rows=[r for r in report['results'] if r['case_id']==case]
        assert len({r['input_hash'] for r in rows})==1
        assert {r['method'] for r in rows}=={'deterministic','single','collaboration'}
    assert report['quality'] is None


def test_live_preflight_uses_existing_budget_and_makes_no_model_call(tmp_path,monkeypatch):
    import backend.app.config as config
    import eval.run_comparison as module
    from backend.app.config import Settings
    from backend.events import EventStore,utcnow
    from backend.app.contracts import Run
    from backend.agents.llm import Agents
    monkeypatch.setattr(config,'ROOT',tmp_path)
    settings=Settings(_env_file=None,data_mode='local',llm_mode='live',openai_api_key='fixture',openai_model='fixture',
        llm_budget_usd=.1,input_usd_per_million=1,output_usd_per_million=1,price_version='fixture')
    store=EventStore(settings.runtime_dir/'events.sqlite3','local');agents=Agents(store,settings)
    store.create_run(Run(id='existing',thread_id='existing',scenario_id='fixture',status='completed',data_mode='local',llm_mode='live',
        input_version='fixture',rule_version='fixture',model_version='fixture',prompt_version='fixture',catalog_version='fixture',started_at=utcnow()))
    with store.connection(write=True) as db:db.execute("INSERT INTO llm_calls VALUES ('existing','old','analysis','error',.03,'{}')")
    monkeypatch.setattr(module,'Settings',lambda **kw:settings)
    monkeypatch.setattr(Agents,'call',lambda *a:pytest.fail('budget preflight must block model calls'))
    report=module.run('test',study=True,live=True)
    assert report['status']=='budget_blocked' and len(report['results'])==216
    assert report['budget_preflight']['available_usd']==pytest.approx(.07)
    assert report['budget_preflight']['required_reservation_usd']==pytest.approx(2.88)
    assert sum(r['output']['reason']=='budget_preflight' for r in report['results'] if r['method']!='deterministic')==144
    with store.connection() as db:assert db.execute('SELECT SUM(reserve_usd) FROM llm_calls').fetchone()[0]==.03
