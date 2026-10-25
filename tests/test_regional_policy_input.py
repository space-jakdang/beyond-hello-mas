"""The default whole-region flow must fit the unchanged model input contract."""
import json
from copy import deepcopy
from tests.test_graph import service,scenario
from tests.test_regional_task import task


# /ship Step 7 pass 2 addition
# Value: protects=whole-region statistics fits 24000-byte real packets, restores canonical notes/blocked IDs and preserves raw snapshots;
# fails_when=regional facts repeat/expand past the cap or short references leak into stored results;
# why_new=single-dong fixtures missed the all-region overflow; no permanent GraphService packet regression covered it;
# seam=none; no_claim=real fake-mode GraphService and scripted model decisions, not live model or provider acceptance.
def test_whole_region_statistics_packets_fit_and_restore_frozen_references(service,monkeypatch):
    import backend.agents.llm as llm
    from backend.agents.workflow import StatisticsDecision
    from backend.context.analysis import FACT_COLUMNS,observed_ids
    from backend.policy.alternative_review import initialize
    initialize(service.store)
    assert service.settings.llm_max_input_bytes==24000
    original_fake=llm.fake;original_call=service.agents.call;packets=[];frozen=[]
    def capture(run_id,sim,role,payload):
        if role=='workflow_statistics':
            packets.append(deepcopy(payload))
            with service.store.connection() as db:
                raw=db.execute('SELECT body FROM regional_context_snapshots WHERE owner_id=?',(run_id,)).fetchone()[0]
            if not frozen:frozen.append(raw)
            assert raw==frozen[0]
        return original_call(run_id,sim,role,payload)
    def decide(role,payload):
        if role!='workflow_statistics':return original_fake(role,payload)
        visible=observed_ids(payload['regional_context'])
        for observation in payload['observations']:
            if observation['tool']=='regional_profile':visible.update(observed_ids(observation))
        assert visible
        facts=[dict(zip(payload['fact_columns'],f)) for f in payload['facts']] if 'fact_columns' in payload else payload['facts']
        blocked=next(f['evidence_id'] for f in facts if f['evidence_id'] not in payload['plan']['priority_evidence_ids'])
        step=len(packets)-1
        return {'action':'lookup' if step==0 else 'finish','tool':'trend',
            'reason':'고정 지역 사실과 실제 관측 추이를 확인합니다.','blocked_evidence_ids':[blocked],
            'regional_notes':[{'fact_ids':[sorted(visible)[0]],'implication':'지역 구성에 맞는 접점 검토',
                'hypothesis':'실제 접근성 차이는 현장 확인이 필요한 가설','missing_evidence':['실제 접점 이용 현황']} ]}
    monkeypatch.setattr(service.agents,'call',capture)
    monkeypatch.setattr(llm,'fake',decide)
    run=service.start(scenario('monthly',workflow_version='regional-workflow-1',policy_context_version='regional-policy-2',
        task=task(goal='지역 전체의 관측 추이를 확인하세요.').model_dump(mode='json')))
    proposal=service.approval(run.id)['proposal'];assessment=proposal['assessment'];statistics=proposal['workflow']['statistics']
    assert statistics['status']=='reviewed',statistics
    assert [o['tool'] for o in statistics['observations']]==['trend']
    assert len(packets)==2 and len(assessment['regional_context'])>3
    raw_profiles=json.loads(frozen[0]);canonical={f['fact_id'] for p in raw_profiles.values() for f in p['facts']}
    evidence={f['evidence_id'] for f in assessment['segments']}
    assert statistics['regional_notes'] and set(statistics['regional_notes'][0]['fact_ids'])<=canonical
    assert statistics['blocked_evidence_ids'] and set(statistics['blocked_evidence_ids'])<=evidence
    for decision in statistics['review_history']:
        assert set(decision['blocked_evidence_ids'])<=evidence
        assert all(set(n['fact_ids'])<=canonical for n in decision['regional_notes'])
    for packet in packets:
        encoded=json.dumps({'prompt':(llm.PROMPTS/'workflow_statistics.txt').read_text(),
            'payload':packet,'schema':StatisticsDecision.model_json_schema()},ensure_ascii=False).encode()
        assert len(encoded)<=24000
        views=[packet['regional_context'],*[o for o in packet['observations'] if o['tool']=='regional_profile']]
        area_keys=[]
        for view in views:
            assert view['fact_columns']==list(FACT_COLUMNS) and len(view['fact_columns'])==18
            for area in view['areas']:
                area_keys.append((area['dong_cd'],area['input_hash']))
                for row in area['facts']:
                    fact=dict(zip(view['fact_columns'],row))
                    assert any(all(fact[key]==raw[key] for key in FACT_COLUMNS if key!='fact_id')
                               for p in raw_profiles.values() for raw in p['facts'])
            if 'available_dongs' in view:
                assert set(view.get('unshown_dongs',[]))<=set(view['available_dongs'])
        assert len(area_keys)==len(set(area_keys))
    assert any(f['evidence_id'].startswith('E') and f['evidence_id'] not in evidence for p in packets
        for f in ([dict(zip(p['fact_columns'],row)) for row in p['facts']] if 'fact_columns' in p else p['facts']))
    assert assessment['regional_context']==raw_profiles
    with service.store.connection() as db:
        assert db.execute('SELECT body FROM regional_context_snapshots WHERE owner_id=?',(run.id,)).fetchone()[0]==frozen[0]
