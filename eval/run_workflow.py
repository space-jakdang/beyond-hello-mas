"""Reproducible regional workflow contract evaluation, not field validity."""
import argparse
import json
from datetime import date,datetime,timezone
from pathlib import Path
from uuid import uuid4
from pydantic import ValidationError
from backend.app.contracts import SegmentV3
from backend.tools.region_stage import classify
from backend.tools.regional_task import RegionalTask
from backend.tools.regional_resources import candidates
from backend.tools.regional_statistics import summary
from backend.tools.catalog import load_catalog
from backend.tools.indicators import digest
from scripts.generate_workflow_cases import generate


def fraction(n,d):return {'numerator':n,'denominator':d,'value':n/d if d else None}


def score(results):
    labeled=[r for r in results if r['expected'] is not None]
    paired=[r for r in labeled if r['predicted'] is not None]
    priority=[r for r in labeled if r['expected']>=4]
    missing=[r for r in results if r['expected'] is None]
    return {'grade_agreement':fraction(sum(r['predicted']==r['expected'] for r in labeled),len(labeled)),
            'ordinal_mae':{'value':sum(abs(r['predicted']-r['expected']) for r in paired)/len(paired) if paired else None,'denominator':len(paired)},
            'missing_predictions':len(labeled)-len(paired),
            'priority_miss':fraction(sum(r['predicted'] is None or r['predicted']<4 for r in priority),len(priority)),
            'correct_abstention':fraction(sum(r['predicted'] is None for r in missing),len(missing)),
            'confusion':{f'{a}->{b}':sum(r['expected']==a and r['predicted']==b for r in labeled) for a in range(1,6) for b in [None,1,2,3,4,5]}}


def evaluate(dataset,classifier=classify):
    if dataset['input_hash']!=digest(dataset['inputs']) or dataset['label_hash']!=digest(dataset['labels']):raise ValueError('dataset checksum mismatch')
    protocol=json.loads(Path(__file__).with_name('workflow_contract.json').read_text())
    if dataset['version']!=protocol['generator_version'] or len(dataset['inputs'])!=protocol['cases']:raise ValueError('evaluation protocol mismatch')
    labels={r['id']:r for r in dataset['labels']}
    if len(labels)!=len(dataset['labels']) or len({r['id'] for r in dataset['inputs']})!=len(dataset['inputs']) or set(labels)!={r['id'] for r in dataset['inputs']}:raise ValueError('case IDs must match uniquely')
    families={split:{r['family'] for r in dataset['inputs'] if r['split']==split} for split in ('development','test')}
    if not all(families.values()):raise ValueError('both development and test splits required')
    if families['development']&families['test']:raise ValueError('family leakage')
    base=load_catalog(Path(__file__).resolve().parents[1]/'data/sample/resources.csv')[0]
    results=[];violations=0;recommendations=0;covered=0;eligible_cases=0;replays=[]
    for case in dataset['inputs']:
        label=labels[case['id']];error=None;predicted=None;selected=[]
        expected_available=case['segment']['index_name'] in ('S1','v3') and case['segment']['value'] is not None
        eligible_cases+=expected_available
        try:
            # Only input segments cross into the production classifier.
            output=classifier([SegmentV3.model_validate(case['segment'])])
            repeated=classifier([SegmentV3.model_validate(case['segment'])])
            replays.append(output==repeated)
            row={**output['segments'][0],'evidence_id':case['id']};predicted=row['stage']
            task={'sgg':row['sgg'],'ym':row['ym'],'as_of':row['ym']+'-28'}
            assessment={'segments':[row],'task':task,'metadata':{'input_hash':digest(case['segment'])}}
            stats=summary(assessment);stats['status']='reviewed'
            valid=base.model_copy(update={'id':'eligible','jurisdiction':['KR'],'age_min':0,'age_max':120,'needs':['relationship'],
                'eligibility':'unrestricted','eligibility_tags':[],'collected_at':datetime(2024,1,1,tzinfo=timezone.utc),
                'valid_until':None,'active':True,'stage_min':1,'stage_max':5})
            # Every decoy violates one independently known mandatory constraint.
            catalog=[valid,valid.model_copy(update={'id':'future','collected_at':datetime(2030,1,1,tzinfo=timezone.utc)}),
                valid.model_copy(update={'id':'expired','valid_until':date(2024,12,31)}),
                valid.model_copy(update={'id':'wrong_region','jurisdiction':['32010' if row['sgg']=='11230' else '11230']}),
                valid.model_copy(update={'id':'narrow_age','age_min':20,'age_max':29}),
                valid.model_copy(update={'id':'unverified','eligibility_tags':['resident']})]
            matched=candidates(assessment,stats,catalog)[0]
            selected=[r['id'] for r in matched['recommendations']]
            covered+=bool(selected) and expected_available
            violations+=sum(r!='eligible' or not expected_available for r in selected)
            recommendations+=len(selected)
        except Exception as exc:error=type(exc).__name__;replays.append(False)
        results.append({'id':case['id'],'split':case['split'],'family':case['family'],'sgg':case['segment']['sgg'],
            'ym':case['segment']['ym'],'basis':label['basis'],'expected':label['stage'],'predicted':predicted,
            'resource_ids':selected,'error':error})
    contract={'classification_mixed_contract':score(results),'by_basis':{b:score([r for r in results if r['basis']==b]) for b in sorted({r['basis'] for r in results})},
        'resource_constraints':{'violations':violations,'recommended':recommendations,'recommendation_coverage':fraction(covered,eligible_cases)},
        'splits':{s:score([r for r in results if r['split']==s]) for s in ('development','test')},
        'periods':{m:score([r for r in results if r['ym']==m]) for m in sorted({r['ym'] for r in results})}}
    probe=RegionalTask(sgg='11230',ym='2025-09',as_of='2025-09-28',sex='M',age_group='youth',goal='synthetic unsupported region')
    try:RegionalTask.model_validate({**probe.model_dump(),'sgg':'99999'})
    except ValidationError as exc:unsupported=all(e['loc']==('sgg',) for e in exc.errors())
    else:unsupported=False
    ok=not any(r['error'] for r in results) and all(replays) and all(r['predicted']==r['expected'] for r in results) and violations==0 and covered==eligible_cases and unsupported
    return {'protocol':protocol,'protocol_hash':digest(protocol),'contract_passed':ok,'contract':contract,'results':results,'reproducible':all(replays),'unsupported_region_rejected':unsupported,
        'external_classification_validity':None,'expert_resource_suitability':None,'real_region_transfer':None,
        'collaboration_effect':None,'adoption_decision':'not_evaluated'}


def run(seed=20261021):
    dataset=generate(seed);outcome=evaluate(dataset);now=datetime.now(timezone.utc);rid=str(uuid4())
    root=Path(__file__).resolve().parents[1];directory=root/'eval/reports'/now.strftime('%Y%m%d')/rid;directory.mkdir(parents=True)
    for name in ('inputs','labels'):(directory/f'{name}.json').write_text(json.dumps(dataset[name],ensure_ascii=False,indent=2)+'\n')
    report={'schema_version':'5','id':rid,'created_at':now.isoformat(),'data_mode':'sample','llm_mode':'fake',
        'status':'contract_passed' if outcome['contract_passed'] else 'contract_failed','evaluated_scenarios':len(dataset['inputs']),
        'metrics':outcome['contract'],'workflow':outcome,'metadata':{k:v for k,v in dataset.items() if k not in ('inputs','labels')},
        'stage_reproducibility':{'identical':outcome['reproducible'],'repetitions':2},'results':[],
        'uncompleted':['independent regional ratings','resource suitability ratings','real third-region transfer','new-workflow A/B/C live comparison'],
        'limitations':['AI-assisted synthetic contract cases; not observed people or independent field labels.',
            'Development/test families and periods do not overlap; both are hand-designed synthetic examples, not external generalization.',
            'Provided non-youth stages test preservation only. Youth examples test provisional rule implementation.',
            'Matching uses synthetic decoys and no actual capacity or budget. No LLM calls were made.',
            'Repeated runs are reproducibility checks, not additional independent cases. Existing temporal and A/B/C reports remain separate.']}
    report['metadata'].update({'methodology_version':'regional-workflow-1','mapping_version':'regional-needs-1','reference_source':'AI-assisted hand-specified rule examples','family_count':len({r['family'] for r in dataset['inputs']}),'llm_calls':0,
        'code_hash':digest({p:(root/p).read_text(encoding='utf-8') for p in ['eval/run_workflow.py','scripts/generate_workflow_cases.py','backend/tools/region_stage.py','backend/tools/regional_resources.py','backend/tools/matching.py','backend/tools/regional_statistics.py','backend/tools/regional_task.py','backend/tools/segments_v3.py','backend/tools/indicators.py','backend/tools/catalog.py','backend/app/contracts.py','data/sample/resources.csv','eval/workflow_contract.json']})})
    (directory/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--seed',type=int,default=20261021)
    report=run(parser.parse_args().seed);print(json.dumps({'id':report['id'],'status':report['status'],'cases':report['evaluated_scenarios']}))
    raise SystemExit(0 if report['workflow']['contract_passed'] else 1)
