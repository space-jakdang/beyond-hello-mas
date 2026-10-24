"""Create three new sample/fake runs. No source files, old runs or cost ledgers are reset."""
import json
from pathlib import Path
from uuid import uuid4
from backend.app.config import Settings
from backend.app.contracts import SegmentV3
from backend.events import EventStore
from backend.graph import GraphService
from backend.regional_batch import BatchRequest,create,execute
from backend.tools.indicators import digest
from backend.tools.regional_task import RegionalTask,assess


def prepare(service):
    if service.settings.data_mode!='sample' or service.settings.llm_mode!='fake' or service.settings.llm_max_calls<4:
        raise ValueError('demo requires sample/fake and at least four calls per run')
    tasks=json.loads((Path(__file__).resolve().parents[1]/'eval/fixtures/regional-quality-tasks.json').read_text())
    results=[]
    for name,task in [('conditional',tasks[0]),('revision',tasks[0]),('unconfirmed_need',tasks[1])]:
        body=create(service,BatchRequest(request_id=uuid4(),task=task,sex=task['sex'],age_group=task['age_group']))
        run_id=body['children'][0]['run_id']
        if name=='revision':
            with service.store.connection(write=True) as db:
                frozen=json.loads(db.execute('SELECT assessment FROM regional_batch_children WHERE run_id=?',(run_id,)).fetchone()[0])
                rows=[SegmentV3.model_validate(row).model_copy(update={'value':None,'flags':list(dict.fromkeys(row.get('flags',[])+['synthetic_missing_demo']))}) if row['dong_cd']==task['dong_cd'] and row['ym']==task['ym'] else SegmentV3.model_validate(row) for row in frozen['source_observations']]
                source={**frozen['metadata']['source'],'original_input_hash':frozen['metadata']['source']['input_hash'],'input_hash':digest([row.model_dump(mode='json') for row in rows]),'demo_source_role':'synthetic_missing_observation'}
                revised=assess(service.settings,RegionalTask.model_validate(task),source_data=(rows,source))
                revised['catalog_snapshot']=frozen['catalog_snapshot']
                body.update(source=source,input_hash=digest([revised]),demo_case=name)
                status=json.loads(db.execute('SELECT body FROM runs WHERE id=?',(run_id,)).fetchone()[0])['status']
                if status!='pending' or db.execute('SELECT COUNT(*) FROM llm_calls WHERE run_id=?',(run_id,)).fetchone()[0]:raise ValueError('demo already started; preserve its snapshot')
                db.execute('UPDATE regional_batch_children SET assessment=? WHERE run_id=?',(json.dumps(revised,ensure_ascii=False),run_id))
                db.execute('UPDATE regional_batches SET body=? WHERE id=?',(json.dumps(body,ensure_ascii=False),body['id']))
        execute(service,body['id'])
        proposal=service.approval(run_id)['proposal'];stats=proposal['workflow']['statistics']
        with service.store.connection() as db:
            matching_calls=db.execute("SELECT COUNT(*) FROM llm_calls WHERE run_id=? AND role='workflow_matching'",(run_id,)).fetchone()[0]
        results.append({'case':name,'batch_id':body['id'],'run_id':run_id,'url':'/workspace?batch='+body['id']+'&run='+run_id,
            'statistics_status':stats['status'],'revision_check':stats.get('revision_check'),'matching_calls':matching_calls,
            'candidate_rows':sum(bool(row['recommendations']) for row in proposal['assignments']),
            'initial_priorities':(stats.get('initial_plan') or {}).get('priority_evidence_ids'),
            'revised_priorities':(stats.get('revised_plan') or {}).get('priority_evidence_ids')})
    assert results[0]['candidate_rows'] and results[0]['revised_priorities'] is None
    assert results[1]['revision_check']=='final_statistics_review' and results[1]['initial_priorities']!=results[1]['revised_priorities']
    assert results[2]['candidate_rows']==0 and all(row['matching_calls']==0 for row in results)
    return {'mode':'sample/fake','replay':False,'description':'새 합성 실행입니다. revision은 관측 결측을 주입한 절차 시연이며 품질 평가가 아닙니다.','cases':results}


def main():
    settings=Settings(_env_file=None,data_mode='sample',llm_mode='fake',resource_catalog='fixture',llm_max_calls=4,
                      openai_api_key=None,GOV24_SERVICE_KEY='',person_mcp_mode='stub')
    result=prepare(GraphService(EventStore(settings.runtime_dir/'events.sqlite3'),settings))
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
