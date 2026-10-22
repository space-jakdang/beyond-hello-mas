"""Run 60 sample/fake protocol scenarios twice; never presents stubs as clinical evaluation."""
import json
import hashlib
import subprocess
import time
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
from backend.app.config import ROOT,Settings
from backend.app.contracts import Scenario,EvaluationLabel
from backend.events import EventStore
from backend.graph import GraphService
from backend.tools.catalog import load_catalog
from backend.tools.indicators import digest
from backend.tools.segments_v3 import load_segments
from backend.tools.weekly_signals import load as load_weekly
from eval.metrics import fraction,percentile
from eval.oracle_v2 import regional


def inputs():
    scenarios=[Scenario.model_validate(s) for s in json.loads((ROOT/'scenarios/inputs-v2.json').read_text())]
    raw_labels=json.loads((ROOT/'scenarios/labels-v2.json').read_text())
    for row in raw_labels:EvaluationLabel.model_validate(row)
    labels={r['scenario_id']:r['expected'] for r in raw_labels}
    if len(raw_labels)!=len(labels):raise ValueError('duplicate labels')
    if len(scenarios)!=60 or len(labels)!=60 or {s.id for s in scenarios}!=set(labels):raise ValueError('sixty unique scenarios and labels required')
    return scenarios,labels


def run():
    scenarios,labels=inputs();id=str(uuid4())
    settings=Settings(_env_file=None,data_mode='sample',llm_mode='fake',person_mcp_mode='stub',resource_catalog='fixture',evaluation_id=id)
    store=EventStore(settings.runtime_dir/'events.sqlite3');service=GraphService(store,settings)
    source,_=load_segments(settings);weekly=load_weekly(settings)
    catalog={r.id for r in load_catalog(settings.catalog_path)}
    results=[];latencies=[];region_correct=region_count=outside=cardinality_errors=0
    youth_correct=youth_count=provided_correct=provided_count=0
    for scenario in scenarios:
        expected=labels[scenario.id];started=time.monotonic();error=None;proposal={}
        registered=service.register(scenario)
        try:
            current=service.drive(registered.id)
            if current.status=='awaiting_approval':
                review=service.approval(current.id);proposal=review['proposal']
                current=service.decide(current.id,review['approval']['snapshot_version'],'approved','synthetic-v2-evaluation')
        except Exception as exc:error=type(exc).__name__
        current=store.get_run(registered.id);latencies.append((time.monotonic()-started)*1000)
        traces=store.traces(current.id,limit=10000)
        path=[t['agent'] for t in traces if t['kind']=='node_end']
        classification=next((t['payload'] for t in traces if t['kind']=='node_end' and t['agent']=='classify'),{})
        stage=(classification.get('result') or {}).get('stage')
        alerts=[t['payload']['type'] for t in traces if t['kind']=='alert']
        recommended={r['id'] for a in proposal.get('assignments',[]) for r in a.get('recommendations',[])}
        outside+=len(recommended-catalog)
        if scenario.type=='monthly':
            month=scenario.payload['ym'];week=max(w for w in weekly['weeks'] if w[:7]==month)
            signal={(r['sgg'],r['sex']):r for r in weekly['rows'] if r['week']==week and r['age_band']=='20s'}
            actual={(r['dong_cd'],r['sex'],r['age_group']):r['stage'] for r in classification.get('segments',[])}
            expected_rows=[r for r in source if r.ym==month and r.preferred]
            expected_keys={(r.dong_cd,r.sex,r.age_group) for r in expected_rows}
            cardinality_errors+=int(set(actual)!=expected_keys or len(actual)!=len(classification.get('segments',[])))
            for row in expected_rows:
                youth=row.index_name in ('S1','v3');card=signal.get((row.sgg,row.sex)) if youth else None
                target=regional(row,[m['signal'] for m in card['metrics'].values()] if card else (),bool(card and row.sex=='M'))
                key=(row.dong_cd,row.sex,row.age_group);region_count+=1
                correct=int(current.status=='completed' and key in actual and actual[key]==target)
                region_correct+=correct
                if youth:youth_count+=1;youth_correct+=correct
                else:provided_count+=1;provided_correct+=correct
        route=next((t['payload'].get('output',{}).get('route') for t in traces if t['kind']=='llm_result' and t['payload'].get('role')=='route'),None)
        results.append({'route':route,'route_correct':route==expected.get('route') if 'route' in expected else None,'scenario_id':scenario.id,'status':current.status,'error':error,'path':path,
            'path_correct':current.status=='completed' and path==expected['path'],'receipt_ms':None,
            'protocol_stage':stage,'protocol_stage_correct':stage==expected.get('protocol_stage') if 'protocol_stage' in expected else None,
            'regional_stage_hash':digest(classification.get('segments',[])) if scenario.type=='monthly' else None,
            'handoff':'human_handoff' in alerts,'crisis':'crisis' in alerts,'recommendations':sorted(recommended)})
    cases=[r for r in results if r['scenario_id'].startswith('S2')]
    critical=[r for r in cases if labels[r['scenario_id']]['protocol_stage']>=4]
    positive=[r for r in results if labels[r['scenario_id']].get('crisis') is True]
    negative=[r for r in results if labels[r['scenario_id']].get('crisis') is False]
    questions=[r for r in results if r['scenario_id'].startswith('S4')]
    metrics={'question_routing':fraction(sum(r['route_correct'] for r in questions),len(questions)),'path_accuracy':fraction(sum(r['path_correct'] for r in results),60),
        'protocol_stage_accuracy':fraction(sum(r['protocol_stage_correct'] for r in cases),len(cases)),
        'clinical_person_stage_accuracy':fraction(0,0),'llm_response_extraction_accuracy':fraction(0,0),
        'youth_regional_rule_agreement':fraction(youth_correct,youth_count),'provided_stage_preservation':fraction(provided_correct,provided_count),
        'regional_rule_agreement':fraction(region_correct,region_count),'regional_cardinality_errors':cardinality_errors,
        'high_stage_handoff':fraction(sum(r['handoff'] for r in critical),len(critical)),
        'fixed_phrase_crisis_recall':fraction(sum(r['crisis'] for r in positive),len(positive)),
        'fixed_phrase_false_positive':fraction(sum(r['crisis'] for r in negative),len(negative)),
        'outside_catalog_recommendations':outside,'intervention_suitability_review':fraction(0,0),
        'cost':{'known_usd':0,'basis':'fake only; no provider calls'},
        'execution_latency':{'p50_ms':percentile(latencies,.5),'p95_ms':percentile(latencies,.95),'definition':'in-process execution including MCP; not browser receipt latency'}}
    code_files=sorted((ROOT/'backend').rglob('*.py'))+[ROOT/'eval/run_v2.py',ROOT/'eval/oracle_v2.py',ROOT/'scripts/generate_v2_scenarios.py']
    code_hash=digest({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in code_files})
    summary={'schema_version':'2','id':id,'created_at':datetime.now(timezone.utc).isoformat(),'data_mode':'sample','llm_mode':'fake',
        'status':'executed_protocol' if all(r['status']=='completed' for r in results) else 'partial','evaluated_scenarios':60,
        'metrics':metrics,'results':results,'stage_reproducibility':{},'uncompleted':[r['scenario_id'] for r in results if r['status']!='completed'],
        'metadata':{'suite':'synthetic-protocol-2','input_hash':digest([s.model_dump(mode='json') for s in scenarios]),'label_hash':digest(labels),
            'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'path_definition':'ordered node_end trace events; question output is tool_result and route is evaluated separately','oracle':'independent regional decision table','result_hash':digest(results),'code_hash':code_hash,
            'code_dirty':bool(subprocess.check_output(['git','status','--porcelain','--','backend','eval/run_v2.py','eval/oracle_v2.py','scripts/generate_v2_scenarios.py'],cwd=ROOT,text=True).strip())},
        'limitations':['개인 단계는 합성 MCP 계약 fixture이며 실제 판정 정확도가 아닙니다.','비청년 지역 단계는 제공 단계 보존, 청년은 별도 결정표 일치 검사입니다.','새 문항·실제 MCP v0.2·LLM 응답 추출 미검증.','고정 위기 표현 6양성/2음성 결과이며 일반 자연어 탐지 성능이 아닙니다.','자격·개입 적합성 전문가 검수 및 브라우저 수신 지연은 미평가.']}
    folder=ROOT/'eval/reports'/datetime.now(timezone.utc).strftime('%Y%m%d')/id
    folder.mkdir(parents=True,exist_ok=False)
    (folder/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    return folder,summary


if __name__=='__main__':
    first,a=run();second,b=run()
    identical=all(a['metadata'][key]==b['metadata'][key] for key in ('result_hash','code_hash','input_hash','label_hash'))
    for folder,summary in ((first,a),(second,b)):
        summary['stage_reproducibility']={'repetitions':2,'identical':identical,'hashes':[a['metadata']['result_hash'],b['metadata']['result_hash']]}
        (folder/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'reports':[str(first.relative_to(ROOT)),str(second.relative_to(ROOT))],'identical':identical,'metrics':a['metrics']},ensure_ascii=False))
    if not identical or any(s['status']!='executed_protocol' or s['metrics']['question_routing']['value']!=1 or s['metrics']['protocol_stage_accuracy']['value']!=1 or s['metrics']['path_accuracy']['value']!=1 or s['metrics']['high_stage_handoff']['value']!=1 or s['metrics']['fixed_phrase_crisis_recall']['value']!=1 or s['metrics']['fixed_phrase_false_positive']['value']!=0 or s['metrics']['regional_rule_agreement']['value']!=1 or s['metrics']['regional_cardinality_errors'] or s['metrics']['outside_catalog_recommendations'] for s in (a,b)):raise SystemExit(2)
