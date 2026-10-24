"""Run frozen regional interpretation and candidate tasks; never read reference labels during inference."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import time
from uuid import UUID
from backend.app.config import Settings
from backend.app.contracts import Resource,Scenario,SegmentV3
from backend.events import EventStore
from backend.graph import GraphService,crisis_evidence
from backend.tools.indicators import digest
from backend.tools.regional_task import RegionalTask,assess
from eval.quality_contracts import load_frozen,resolve_labels
from eval.quality_metrics import validate_predictions

VERSION='regional-quality-1'
TOOLS='frozen-regional-statistics-and-catalog-1'
METHODS=('rules','single','mas')


def capture(settings,tasks):
    from backend.tools.catalog import load_catalog
    from eval.quality_contracts import freeze
    policies={r.id:r.model_dump(mode='json') for r in load_catalog(settings.catalog_path)};cases=[]
    for body in tasks:
        assessment=assess(settings,RegionalTask.model_validate(body));task=assessment['task']
        for row in assessment['segments']:
            cases.append({'id':digest([task,row['evidence_id']]),
                'family_id':digest([row['source_file'],row['dong_cd'],row['index_name']]),
                'region':task['sgg'],'neighborhood':row['dong_cd'],'cohort':task['sex']+'/'+task['age_group'],
                'period':task['ym'],'methodology':assessment['methodology_version'],'split':'dev',
                'source':'synthetic' if settings.data_mode=='sample' else 'observed','policy_as_of':task['as_of'],
                'facts':{'assessment':assessment,'evidence_id':row['evidence_id']},'policies':policies})
    return freeze({'id':'regional-quality-capture','version':VERSION,'cases':cases})


def frozen_assessment(case,settings):
    assessment=deepcopy(case.facts['assessment']);task=RegionalTask.model_validate(assessment['task'])
    if crisis_evidence(task.model_dump(mode='json')):raise ValueError('personal crisis routes are outside this regional comparison')
    if task.future_id or assessment['metadata'].get('synthetic_future'):raise ValueError('future scenarios require a separate evaluation')
    if (case.region,case.cohort,case.period,case.policy_as_of,case.methodology)!=(task.sgg,task.sex+'/'+task.age_group,task.ym,str(task.as_of),assessment['methodology_version']):
        raise ValueError('case and task scope differ')
    if (case.source=='observed')!=(assessment['data_mode']=='local') or assessment['data_mode']!=settings.data_mode:
        raise ValueError('case data mode differs')
    source=[SegmentV3.model_validate(row) for row in assessment['source_observations']]
    expected=assess(settings,task,source_data=(source,assessment['metadata']['source']))
    if assessment['metadata'].get('statistics_version')=='2':expected['metadata']['statistics_version']='2'
    if any(expected[key]!=assessment[key] for key in ('segments','period_aggregate','metadata')):
        raise ValueError('frozen assessment differs from recorded source calculation')
    selected=[r for r in assessment['segments'] if r['evidence_id']==case.facts['evidence_id'] and r['dong_cd']==case.neighborhood]
    if len(selected)!=1:raise ValueError('case evidence not in frozen assessment')
    resources=[Resource.model_validate(body) for body in case.policies.values()]
    if any(body['id']!=identifier for identifier,body in case.policies.items()):raise ValueError('catalog IDs differ')
    from backend.tools.catalog import validate_catalog
    validate_catalog(resources)
    assessment['catalog_snapshot']=[r.model_dump(mode='json') for r in sorted(resources,key=lambda r:r.id)]
    return assessment


class QualityGraph(GraphService):
    """Keep the production graph and approval gate; substitute only evaluation arm nodes."""
    def __init__(self,store,settings,assessment,method):
        super().__init__(store,settings);self.assessment=assessment;self.method=method
        self.evaluation_protocol=VERSION;self.evaluation_method=method;self.evaluation_input_hash=digest(assessment)

    def classify_node(self,state):
        started=time.monotonic();result=deepcopy(self.assessment)
        self.node_event(state,'classify',result,started)
        return {'classification':result}

    def workflow_analyze(self,state):
        if self.method=='mas':return super().workflow_analyze(state)
        started=time.monotonic()
        if self.method=='single':
            from backend.agents.workflow_single import run
            plan,stats=run(self.agents,self.settings,state['run_id'],state['scenario']['sim_time'],state['classification'],self.regional_emit(state),state['workflow_deadline'])
        else:
            from backend.tools.regional_statistics import summary
            base=summary(state['classification'])
            plan={'summary':'규칙 계산 기준선입니다. 지역 해석의 내용 검토는 수행하지 않았습니다.',
                  'priority_evidence_ids':[r['evidence_id'] for r in state['classification']['segments'] if r['evidence_id'] not in base['blocked_evidence_ids']][:5]}
            stats={'status':'reviewed','reason':'deterministic_bounds_only','review_mode':'rules','summary':base,'observations':[],
                   'blocked_evidence_ids':base['blocked_evidence_ids']}
        result={'analysis':plan,'status':stats['status'],'_statistics':stats}
        self.node_event(state,'regional_analyst',{'status':result['status'],'method':self.method},started)
        return {'workflow':result}

    def workflow_statistics(self,state):
        if self.method=='mas':return super().workflow_statistics(state)
        started=time.monotonic();workflow=dict(state['workflow']);stats=workflow.pop('_statistics')
        workflow.update(statistics=stats,status=stats['status'])
        self.node_event(state,'statistics',stats,started)
        return {'workflow':workflow}


def prediction(case,proposal):
    from backend.tools.matching import MatchRequest,filter_catalog
    segment=next(r for r in proposal['assessment']['segments'] if r['evidence_id']==case.facts['evidence_id'])
    row=next(a for a in proposal['assignments'] if a['evidence_id']==segment['evidence_id'])
    workflow=proposal['workflow'];failed=any(part.get('failure_kind') or part.get('error_type') for part in (workflow,workflow['statistics'],workflow.get('matching') or {}))
    pool=[]
    if row['catalog_filter_performed'] and not failed:
        # Reconstruct the full eligible pool from the recorded request, before the three-slot cutoff.
        resources=[Resource.model_validate(r) for r in proposal['assessment']['catalog_snapshot']]
        pool=filter_catalog(resources,MatchRequest.model_validate(row['decision_evidence']['filter_request']),regional_ages=row['source_age_ranges'])[0]
    selected=[] if failed else [r['id'] for r in row['recommendations']]
    return {'case_id':case.id,'grade':segment['stage'],'status':'predicted' if segment['stage'] is not None else 'abstained',
        'resources':{'status':'failed' if failed else 'completed','retrieved_ids':sorted(r.id for r in pool),'recommended_ids':selected,
                     'suitability':{identifier:'conditional' for identifier in selected}}}


def execute(frozen,settings,store):
    dataset=load_frozen(frozen)
    prepared={case.id:frozen_assessment(case,settings) for case in dataset.cases}
    if settings.llm_mode=='live' and settings.llm_run_budget_usd is None:raise ValueError('live comparison requires a per-run budget')
    conditions={'model':settings.openai_model if settings.llm_mode=='live' else 'fake-v1','tools_version':TOOLS,
        'catalog_hash':digest({case.id:case.policies for case in dataset.cases}),'max_calls':settings.llm_max_calls,
        'max_usd':float(settings.llm_run_budget_usd or 0)}
    records=[];arms=[]
    for method in METHODS:
        predictions=[];telemetry=[];runs={}
        for case in dataset.cases:
            assessment=prepared[case.id];key=digest(assessment)
            if key not in runs:
                service=QualityGraph(store,settings,assessment,method)
                scenario=Scenario(id='quality-regional-'+method,type='monthly',sim_time=case.period+'-01T09:00:00+09:00',
                    payload={'evaluation_protocol':VERSION,'evaluation_method':method,'evaluation_input_hash':key,
                             'workflow_version':'regional-workflow-1','policy_proposal_version':'batch-child','research_gaps':False,'task':assessment['task']})
                started=time.monotonic();run=service.register(scenario)
                try:run=service.drive(run.id)
                except Exception:run=store.get_run(run.id)
                proposal=service.approval(run.id)['proposal'] if run.status=='awaiting_approval' else None
                with store.connection() as db:
                    calls=[dict(r) for r in db.execute('SELECT status,reserve_usd,body FROM llm_calls WHERE run_id=?',(run.id,))]
                bodies=[json.loads(r['body']) for r in calls];known=all(b.get('cost_usd') is not None for b in bodies)
                timing={'run_id':run.id,'cost_usd':sum(b['cost_usd'] for b in bodies) if known else None,'latency_seconds':time.monotonic()-started}
                telemetry.append(timing)
                record={'method':method,'run_id':run.id,'assessment_hash':key,'case_ids':[],'run_status':run.status,'proposal':proposal,
                    'calls':len(calls),'reserved_usd':sum(r['reserve_usd'] for r in calls),'unknown_cost_calls':sum(b.get('cost_usd') is None for b in bodies),
                    'returned_models':sorted({b['returned_model'] for b in bodies if b.get('returned_model')}),'telemetry':timing}
                records.append(record);runs[key]=record
            record=runs[key];record['case_ids'].append(case.id)
            result=prediction(case,record['proposal']) if record['proposal'] else {'case_id':case.id,'grade':None,'status':'failed',
                'resources':{'status':'failed','retrieved_ids':[],'recommended_ids':[],'suitability':{}}}
            predictions.append({**result,'run_id':record['run_id']})
        body={'dataset_hash':frozen['dataset_hash'],'version':VERSION,'model':'rules' if method=='rules' else conditions['model'],'method':method,'predictions':predictions}
        validate_predictions(frozen,body)
        arms.append({'conditions':conditions,'predictions':body,'telemetry':telemetry})
    root=Path(__file__).resolve().parents[1]
    paths=['backend/prompts/workflow_analyst.txt','backend/prompts/workflow_statistics.txt','backend/prompts/workflow_single.txt',
           'backend/agents/workflow.py','backend/agents/workflow_single.py','backend/tools/regional_resources.py','backend/tools/matching.py','eval/run_regional_quality.py']
    return {'version':VERSION,'dataset_hash':frozen['dataset_hash'],'mode':settings.llm_mode,'conditions':conditions,'arms':arms,'records':records,
        'code_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
        'code_dirty':bool(subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=root,text=True)),
        'file_hashes':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in paths},
        'evaluation_scope':'regional_interpretation_and_conditional_catalog_candidates',
        'policy_research_and_design':'not_in_comparison','field_effects':'not_evaluated','independent_quality':'not_evaluated'}


def study_for(frozen,labels,report):
    validate_report(frozen,report)
    return {'version':VERSION,'dataset_hash':frozen['dataset_hash'],'label_hash':resolve_labels(frozen,labels)['label_hash'],
        'development_regions':['11230','32010'],'conditions':report['conditions'],'arms':report['arms']}


def validate_report(frozen,report):
    from eval.quality_study import Conditions
    dataset=load_frozen(frozen);cases={case.id:case for case in dataset.cases}
    if report['version']!=VERSION or report['dataset_hash']!=frozen['dataset_hash']:raise ValueError('run report dataset mismatch')
    conditions=Conditions.model_validate(report['conditions'])
    if conditions.catalog_hash!=digest({case.id:case.policies for case in dataset.cases}) or conditions.tools_version!=TOOLS:
        raise ValueError('comparison tool or catalog snapshot differs')
    if [arm['predictions']['method'] for arm in report['arms']]!=list(METHODS):raise ValueError('comparison methods differ')
    records={r['run_id']:r for r in report['records']}
    if len(records)!=len(report['records']):raise ValueError('duplicate source run')
    linked=set()
    for arm in report['arms']:
        body=validate_predictions(frozen,arm['predictions'])
        if body.model!=('rules' if body.method=='rules' else conditions.model):raise ValueError('configured comparison model differs')
        if arm['conditions']!=report['conditions'] or {p.case_id for p in body.predictions}!=set(cases):raise ValueError('comparison conditions or cases differ')
        actual={}
        for row in body.predictions:
            record=records.get(row.run_id)
            if not record or record['method']!=body.method:raise ValueError('source run reused across methods')
            actual.setdefault(row.run_id,[]).append(row.case_id);linked.add(row.run_id)
            case=cases[row.case_id]
            assessment=frozen_assessment(case,Settings(_env_file=None,data_mode='sample' if case.source=='synthetic' else 'local'))
            if record['assessment_hash']!=digest(assessment):raise ValueError('source assessment mismatch')
            if record['proposal']:
                if record['proposal']['assessment']!=assessment:raise ValueError('source snapshot mismatch')
                expected={**prediction(case,record['proposal']),'run_id':row.run_id}
                if row.model_dump()!=expected:raise ValueError('prediction differs from source run')
            elif row.status!='failed' or row.grade is not None or row.resources.status!='failed':raise ValueError('failed run promoted to prediction')
        if any(sorted(records[rid]['case_ids'])!=sorted(ids) for rid,ids in actual.items()):raise ValueError('source case links differ')
        if arm['telemetry']!=[r['telemetry'] for r in report['records'] if r['method']==body.method]:raise ValueError('telemetry differs from linked runs')
    if linked!=set(records):raise ValueError('unlinked source run')
    return cases


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folder',type=Path)
    parser.add_argument('--live',action='store_true',help='Use explicitly configured paid model and persistent dataset ledger')
    args=parser.parse_args();folder=args.folder
    if any((folder/name).exists() for name in ('workflow-runs.json','study.json','predictions.json')):parser.error('results already exist; preserve the recorded runs and ledger')
    frozen=json.loads((folder/'inputs.json').read_text());dataset=load_frozen(frozen)
    mode='sample' if all(c.source=='synthetic' for c in dataset.cases) else 'local'
    settings=Settings(data_mode=mode,llm_mode='live' if args.live else 'fake',evaluation_id=UUID(folder.name))
    store=EventStore(settings.runtime_dir/'events.sqlite3')
    report=execute(frozen,settings,store)
    # Labels are first opened after all predictions are fixed.
    labels=json.loads((folder/'labels.json').read_text())
    outputs={'workflow-runs':report,'study':study_for(frozen,labels,report),'predictions':report['arms'][-1]['predictions']}
    for name,value in outputs.items():(folder/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    print(folder)


if __name__=='__main__':main()
