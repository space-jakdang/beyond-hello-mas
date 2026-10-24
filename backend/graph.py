"""Durable approval graph with Supervisor-delegated policy research. No external notifications."""
from contextlib import contextmanager
from datetime import timedelta
import json
import time
from threading import RLock
from typing import TypedDict
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from langsmith import tracing_context

from backend.app.contracts import Alert, Approval, Run, Scenario, PersonCase, person_age_group
from backend.agents.llm import Agents
from backend.agents.scale import ScaleAdapter
from backend.agents.person import PersonAdapter
from backend.policy.agent import PolicyAgent, PolicyTask
from backend.events import utcnow
from backend.tools.catalog import load_catalog
from backend.tools.indicators import digest
from backend.tools.matching import MatchRequest, map_intensity, match
from backend.tools.segments import load_segments
from backend.tools.staging import classify


class State(TypedDict, total=False):
    run_id: str
    scenario: dict
    crisis: list[str]
    classification: dict
    proposal: dict
    decision: dict
    question_route: str
    local_action: str
    regional: dict
    workflow: dict
    workflow_deadline: float


def crisis_evidence(payload):
    if isinstance(payload, dict):
        return sorted({hit for value in payload.values() for hit in crisis_evidence(value)})
    if isinstance(payload, list):
        return sorted({hit for value in payload for hit in crisis_evidence(value)})
    if not isinstance(payload, str):
        return []
    text = payload.replace('죽고 싶지 않', '').replace('자살 예방', '')
    for negative in ('끝내고 사라지고 싶지 않','끝내고 사라지고 싶지는 않','더 이상 이 세상에 없을 것 같지 않','더 이상 이 세상에 없을 것 같지는 않'):
        text=text.replace(negative,'')
    return [phrase for phrase in ('죽고 싶', '목숨을 끊', '자살할', '죽을 거야', '나를 해치고 싶', '끝내고 사라지고 싶', '더 이상 이 세상에 없을 것 같') if phrase in text]


class GraphService:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        from backend.regional_batch import initialize
        initialize(store)
        self.agents = Agents(store, settings)
        self.scale = ScaleAdapter(store, settings)
        self.person = PersonAdapter(store, settings)
        self.policy_agent = PolicyAgent(store, settings, self.agents)
        from backend.policy.designer import PolicyDesigner
        self.policy_designer=PolicyDesigner(store,settings,self.agents,self.policy_agent)
        self.locks = {}
        self.lock_guard = RLock()
        with store.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS workflows (run_id TEXT PRIMARY KEY REFERENCES runs(id), scenario TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE REFERENCES runs(id), body TEXT NOT NULL, proposal TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS linkages (run_id TEXT PRIMARY KEY REFERENCES runs(id), body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions (parent_run_id TEXT PRIMARY KEY REFERENCES runs(id), child_run_id TEXT NOT NULL UNIQUE REFERENCES runs(id), request_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS effects (run_id TEXT NOT NULL REFERENCES runs(id), name TEXT NOT NULL, PRIMARY KEY(run_id,name));
            ''')

    def lock(self, run_id):
        with self.lock_guard:
            return self.locks.setdefault(run_id, RLock())

    def update_run(self, db, run_id, **changes):
        row = db.execute('SELECT body FROM runs WHERE id=?', (run_id,)).fetchone()
        run = Run.model_validate({**json.loads(row['body']), **changes})
        db.execute('UPDATE runs SET body=? WHERE id=?', (run.model_dump_json(), run_id))

    def once(self, db, state, name, kind, payload, agent='system', **metrics):
        inserted = db.execute('INSERT OR IGNORE INTO effects VALUES (?,?)', (state['run_id'], name)).rowcount
        if inserted:
            self.store._trace(db, state['run_id'], state['scenario']['sim_time'], kind, payload, agent, **metrics)

    def node_event(self, state, node, payload, started):
        with self.store.connection(write=True) as db:
            self.once(db, state, node, 'node_end', payload, node, latency_ms=(time.monotonic()-started)*1000)

    def supervisor(self, state):
        started = time.monotonic()
        evidence = crisis_evidence(state['scenario']['payload'])
        self.node_event(state, 'supervisor', {'crisis_rule_version': 'crisis-expression-2', 'evidence': evidence}, started)
        route = None
        if not evidence and state['scenario']['payload'].get('workflow_version'):
            from backend.tools.regional_task import task_from
            task=task_from(state['scenario']['payload'])
            self.regional_emit(state)('task','supervisor','regional_analyst',{'task':task.model_dump(mode='json'),'goal':task.goal})
        if not evidence and state['scenario']['type'] == 'question':
            route = self.agents.call(state['run_id'], state['scenario']['sim_time'], 'route', state['scenario']['payload']).route
        if not evidence and state['scenario']['type'] == 'policy':
            task = PolicyTask.model_validate(state['scenario']['payload'])
            with self.store.connection(write=True) as db:
                self.once(db, state, 'policy-delegation', 'route', {'worker': 'policy', 'task': task.model_dump()}, 'supervisor')
        return {'crisis': evidence, 'question_route': route, 'workflow_deadline':time.time()+120}

    def classify_node(self, state):
        started = time.monotonic()
        scenario = Scenario.model_validate(state['scenario'])
        if scenario.payload.get('workflow_version'):
            from backend.tools.regional_task import assess, task_from
            with self.store.connection() as db:
                frozen=db.execute('SELECT assessment FROM regional_batch_children WHERE run_id=?',(state['run_id'],)).fetchone()
            result=json.loads(frozen[0]) if frozen else assess(self.settings,task_from(scenario.payload))
            if scenario.payload.get('statistics_version')=='2':result['metadata']['statistics_version']='2'
            self.node_event(state, 'classify', result, started)
            return {'classification':result}
        elif scenario.type == 'admin' or 'person' in scenario.payload:
            person = PersonCase.model_validate(scenario.payload['person'])
            group = person_age_group(person.age)
            if scenario.type == 'admin':
                result = self.person.priority(state['run_id'], scenario.sim_time, group, {**person.features, **person.admin_flags})
                result['screening'] = {'status': 'verified_questions_required', 'external_delivery': False,
                    'message': '검증된 문항을 준비하여 담당자가 선별 질문을 확인해야 합니다.'}
                action = 'screening_requested'
            elif not person.consent or not person.responses_confirmed:
                result = {'status': 'assessment_pending', 'result': None, 'reason': 'consent_and_person_confirmation_required'}
                action = 'human_handoff'
            else:
                result = self.person.assess(state['run_id'], scenario.sim_time, {'age': person.age, 'age_group': group,
                    'responses': person.responses, 'admin_flags': person.admin_flags})
                assessment = result.get('result') or {}
                action = 'human_handoff' if result['status'] != 'assessed' or assessment.get('human_handoff') or assessment.get('crisis') or (group in ('midlife','prime') and assessment.get('stage') == 3) else ''
            result['age_group'] = group
            result['response_category'] = 'human_connection' if action == 'human_handoff' else 'screening' if scenario.type == 'admin' else 'referral'
            self.node_event(state, 'classify', result, started)
            return {'classification': result, 'local_action': action}
        if scenario.type == 'monthly' and scenario.payload.get('analysis_version') != 'legacy-v1':
            from backend.tools.neighborhoods import group_analysis
            month = scenario.payload.get('ym')
            week = scenario.payload.get('week')
            if not week and month:
                from backend.tools.weekly_signals import load as load_weekly
                week = next((w for w in reversed(load_weekly(self.settings)['weeks']) if w[:7]==month),None)
            result = group_analysis(self.settings,week,scenario.payload.get('card_age','20s'))
            if not result['period_aggregate'] and month not in result['months']:raise ValueError('requested month missing from dataset')
            result['segments'] = [r for r in result['segments'] if r['preferred'] and r['ym'] in (None,month)]
            result['dongs'] = [r for r in result['dongs'] if r['ym'] in (None,month)]
            result['metadata']['analysis_version'] = 'v3'
        elif scenario.type == 'monthly':
            month = scenario.payload.get('ym')
            rows, source = load_segments(self.settings)
            if month not in {r.ym for r in rows}:
                raise ValueError('requested month missing from dataset')
            result = classify(rows)
            result['segments'] = [r for r in result['segments'] if r['ym'] == month]
            result['dongs'] = [r for r in result['dongs'] if r['ym'] == month]
            result['metadata']['source'] = source
            locations = {r.dong_cd: r for r in rows if r.ym == month}
            for dong in result['dongs']:
                row = locations[dong['dong_cd']]
                dong.update(dong_nm=row.dong_nm, x=row.x, y=row.y, crs=row.crs, coordinate_source=row.coordinate_source)
        elif scenario.type in ('case', 'crisis', 'question'):
            result = self.scale.score(state['run_id'], scenario.sim_time, scenario.payload.get('responses'))
            result['stage'] = None
        else:
            raise ValueError('non-crisis question routing is not implemented yet')
        summary_input = {'type': scenario.type, 'text': scenario.payload.get('text', ''),
                         'assessment': result.get('result'), 'aggregate_metadata': result.get('metadata')}
        if scenario.type == 'monthly' and scenario.payload.get('collaboration') is True and result.get('metadata',{}).get('analysis_version') == 'v3':
            pass  # Regional work runs in separately checkpointed graph nodes.
        else:
            result['analysis'] = self.agents.call(state['run_id'], scenario.sim_time, 'analysis', summary_input).model_dump()
        self.node_event(state, 'classify', result, started)
        return {'classification': result}

    def regional_emit(self, state):
        def emit(key,sender,recipient,payload):
            with self.store.connection(write=True) as db:
                self.once(db,state,'regional-'+key,'agent_message',{'sender':sender,'recipient':recipient,**payload},sender)
        return emit

    def workflow_analyze(self, state):
        from backend.agents.workflow import analyze,WorkflowError
        started=time.monotonic()
        try:
            if time.time()>=state['workflow_deadline']:raise WorkflowError('deadline')
            plan=analyze(self.agents,state['run_id'],state['scenario']['sim_time'],state['classification'],state['scenario']['payload'].get('revision'))
            if time.time()>=state['workflow_deadline']:raise WorkflowError('deadline')
            result={'analysis':plan,'status':'analyzed'}
            self.regional_emit(state)('workflow-analysis','regional_analyst','statistics',{'plan':plan})
        except Exception as exc:
            result={'analysis':None,'status':'needs_human','reason':str(exc) if isinstance(exc,WorkflowError) else 'model_or_tool_unavailable','error_type':type(exc).__name__}
        self.node_event(state,'regional_analyst',result,started)
        return {'workflow':result}

    def workflow_statistics(self, state):
        from backend.agents.workflow import statistical_review
        started=time.monotonic();workflow=dict(state['workflow'])
        if workflow['analysis'] is None:
            stats={'status':'needs_human','reason':'analysis_unavailable','blocked_evidence_ids':[]}
        else:
            stats=statistical_review(self.agents,self.settings,state['run_id'],state['scenario']['sim_time'],
                state['classification'],workflow['analysis'],self.regional_emit(state),state['workflow_deadline'],
                [t['payload']['observation'] for t in self.store.traces(state['run_id'],limit=1000)
                 if t['kind']=='agent_message' and t['agent']=='statistics' and 'observation' in t['payload']])
        workflow['statistics']=stats;workflow['status']=stats['status']
        if stats['status']=='reviewed' and stats.get('revised_plan'):workflow['analysis']=stats['revised_plan']
        self.node_event(state,'statistics',stats,started)
        return {'workflow':workflow}

    def workflow_match(self,state):
        from backend.tools.regional_resources import candidates,select_candidates
        from backend.agents.workflow_matching import select
        started=time.monotonic();workflow=dict(state['workflow']);rows=[]
        cached=next((t['payload']['candidates'] for t in self.store.traces(state['run_id'],limit=1000)
                     if t['kind']=='agent_message' and t['payload'].get('result_kind')=='workflow_candidates'),None)
        try:
            if time.time()>=state['workflow_deadline']:raise ValueError('deadline')
            if cached is None:
                from backend.app.contracts import Resource
                frozen=state['classification'].get('catalog_snapshot')
                resources=[Resource.model_validate(r) for r in frozen] if frozen is not None else load_catalog(self.settings.catalog_path)
                rows=candidates(state['classification'],workflow['statistics'],resources)
            else:rows=cached
            self.regional_emit(state)('workflow-candidates','statistics','match',{'result_kind':'workflow_candidates','candidates':rows})
            rows,matching=select_candidates(rows) if state['classification']['metadata'].get('matching_mode')=='deterministic-regional-1' else select(self.agents,state['run_id'],state['scenario']['sim_time'],rows,workflow['statistics'])
            if time.time()>=state['workflow_deadline']:raise ValueError('deadline')
        except Exception as exc:
            if not rows:rows=candidates(state['classification'],{'status':'needs_human'},[])
            rows=[{**r,'recommendations':[],'shortfall':3,'uncovered_needs':r['needs'],'reason':'matching_unavailable','status':'needs_human'} for r in rows]
            matching={'status':'needs_human','summary':'매칭을 완료하지 못했습니다. 담당자 확인이 필요합니다.','error_type':type(exc).__name__}
            if state['classification']['metadata'].get('matching_mode')=='deterministic-regional-1':
                matching.update(matching_mode='deterministic-regional-1',model_calls=0)
                rows=[{**r,'matching_mode':'deterministic-regional-1',
                       'decision_evidence':{**r['decision_evidence'],'matching_mode':'deterministic-regional-1'}} for r in rows]
        if state['classification']['metadata'].get('policy_gap_version')=='policy-gap-1':
            from backend.tools.regional_resources import policy_gap
            rows=[{**row,'policy_gap':policy_gap(row,state['scenario']['payload'].get('policy_research_requested') is True)} for row in rows]
        workflow.update(assignments=rows,matching=matching,status='reviewed' if matching['status']=='reviewed' and workflow['statistics']['status']=='reviewed' else 'needs_human')
        self.regional_emit(state)('workflow-match','match','supervisor',matching)
        self.node_event(state,'match',{'status':matching['status'],'assignment_count':len(rows)},started)
        return {'workflow':workflow}

    def workflow_proposal(self,state):
        started=time.monotonic();workflow=state['workflow']
        proposal={'scope':'regional_evidence_review','workflow_version':'regional-workflow-1',
            'task':state['classification']['task'],'assessment':state['classification'],
            'workflow':workflow,'assignments':workflow.get('assignments',[]),
            'human_review_required':True,'provisional':True,'external_delivery':False,
            'fake':self.settings.llm_mode=='fake','scenario_hash':digest(state['scenario']),
            'draft':{'text':'지역 분석·통계 근거와 조건부 자원을 담당자가 검토해야 합니다. 실제 배정이 아닙니다.',
                     'resource_ids':sorted({c['id'] for r in workflow.get('assignments',[]) for c in r['recommendations']})}}
        if state['scenario']['payload'].get('revision'):proposal['revision']=state['scenario']['payload']['revision']
        proposal['snapshot_version']=digest(proposal)
        self.regional_emit(state)('workflow-proposal','supervisor','approval',{'status':workflow['status'],'snapshot_version':proposal['snapshot_version']})
        with self.store.connection(write=True) as db:
            self.once(db,state,'workflow-proposal','node_end',{'snapshot_version':proposal['snapshot_version']},'supervisor')
        return {'proposal':proposal}

    def regional_prepare(self, state):
        from backend.agents.regional_team import from_classification
        regional=from_classification(state['classification'],self.settings.data_mode,self.settings.llm_max_calls)
        regional['observations']['verification_required']=state['scenario']['payload'].get('verify_sources') is True
        self.regional_emit(state)('delegate','supervisor','regional_analyst',{'goal':regional['observations']['goal'],'observations':regional['observations']})
        return {'regional':regional}

    def regional_step(self, state, action):
        from backend.agents.regional_team import advance
        return {'regional':advance(state['regional'],action,self.agents,state['run_id'],state['scenario']['sim_time'],self.regional_emit(state))}

    def regional_finalize(self, state):
        from backend.agents.regional_team import finish
        result=finish(state['regional'])
        self.regional_emit(state)('decision','supervisor','match',{'decision':'submit_for_human_approval' if result['plan'] else 'needs_human','reason':result['reason']})
        return {'classification':{**state['classification'],'collaboration':result}}

    def match_node(self, state):
        started = time.monotonic()
        result = state['classification']
        assignments = []
        if state['scenario']['type'] == 'monthly':
            resources = load_catalog(self.settings.catalog_path)
            for segment in result['segments']:
                if segment['stage'] is None:
                    assignments.append({**segment, 'recommendations': [], 'reason': 'unassessed'})
                    continue
                if 'age_group' in segment:
                    low,high = {'youth':(19,34),'midlife':(35,49),'prime':(50,64),'elderly':(65,120)}[segment['age_group']]
                else:
                    low = int(segment['age_band'][:2]);high = 120 if low == 60 else low+9
                request = MatchRequest(sgg=segment['dong_cd'][:5], age_min=low,
                    age_max=high, needs=['relationship'], stage=segment['stage'] if 'age_group' in segment else None,
                    intensity=map_intensity(segment['stage']), as_of=utcnow().date())
                recommendation = match(resources, request)
                assignments.append({'ym': segment['ym'], 'dong_cd': segment['dong_cd'], **({k:segment[k] for k in ('sex','age_group','index_name')} if 'age_group' in segment else {'age_band':segment['age_band']}),
                    'stage': segment['stage'], 'recommendations': recommendation['recommendations'],
                    'shortfall': recommendation['shortfall'], 'metadata': recommendation['metadata']})
        elif result.get('status') == 'assessed':
            payload = state['scenario']['payload']
            labels = {r['label'] for r in result['result'].get('matched', [])}
            needs = set(result.get('analysis', {}).get('needs', ['relationship']))
            if 'person' in payload:
                payload = {**payload, **payload['person']}
            flags = payload.get('admin_flags', {})
            if any(flags.get(k,False) for k in ('arrears_utility','arrears_rent','arrears_loan','hi_premium_unpaid')):needs.add('economic')
            if any(flags.get(k,False) for k in ('arrears_rent','eviction_risk','non_housing')):needs.add('housing')
            if '외로움 고위험군' in labels:
                needs.add('emotional')
            if '사회적 고립 고위험군' in labels:
                needs.add('relationship')
            if needs and payload.get('age') is not None and payload.get('sgg'):
                resources = load_catalog(self.settings.catalog_path)
                request = MatchRequest(sgg=payload['sgg'], age_min=payload['age'], age_max=payload['age'],
                    needs=sorted(needs), intensity='high' if labels else 'low',
                    eligibility=payload.get('eligibility', {}), stage=result['result'].get('stage'),
                    arrears=any(payload.get('admin_flags', {}).get(k,False) for k in ('arrears_utility','arrears_rent','arrears_loan','hi_premium_unpaid')), as_of=utcnow().date())
                assignments.append(match(resources, request))
        candidates = {r['id']: r for assignment in assignments for r in assignment.get('recommendations', [])}
        collaboration=result.get('collaboration')
        if collaboration is not None:
            # The reviewed summary replaces redundant explanation/draft model calls.
            plan=collaboration.get('plan') or {}
            explanations={'items':[], 'summary':plan.get('summary','협업 검토 미완료: 담당자가 원자료를 확인해야 합니다.')}
            draft={'text':'지역 검토안입니다. 담당자 승인 전에는 연계하지 않습니다.','resource_ids':sorted(candidates)}
        else:
            explanations = self.agents.call(state['run_id'], state['scenario']['sim_time'], 'recommendations',
                                            {'candidates': list(candidates.values())}).model_dump()
            draft = self.agents.call(state['run_id'], state['scenario']['sim_time'], 'draft',
                                    {'resource_ids': sorted(candidates), 'assessment': result.get('status')}).model_dump()
        proposal = {'scope': 'monthly_group_allocation' if state['scenario']['type'] == 'monthly' else ('case_referral_plan' if result.get('status') == 'assessed' else 'assessment_followup'),
                    'assignments': assignments, 'assessment': result.get('status'), 'fake': self.settings.llm_mode == 'fake',
                    'explanations': explanations, 'draft': draft,
                    'external_delivery': False, 'scenario_hash': digest(state['scenario'])}
        if collaboration is not None:
            proposal['collaboration']=collaboration
            proposal['priority_review_ids']=(collaboration.get('plan') or {}).get('focus_ids',[])
        proposal['snapshot_version'] = digest(proposal)
        self.node_event(state, 'match', {'snapshot_version': proposal['snapshot_version'], 'assignment_count': len(assignments)}, started)
        return {'proposal': proposal}

    def regional_policy_node(self, state):
        started=time.monotonic()
        proposal=dict(state['proposal'])
        current=(proposal.get('assessment') or {}).get('metadata',{}).get('policy_gap_version')=='policy-gap-1'
        gaps=[a for a in proposal['assignments'] if a.get('policy_gap',{}).get('research_needed')] if current else [a for a in proposal['assignments'] if a.get('shortfall',0)>0 and (not proposal.get('workflow_version') or a.get('catalog_filter_performed'))]
        scopes={'central'}
        jurisdiction={'11230':('seoul','gangnam'),'32010':('gangwon','chuncheon')}
        unsupported=any(a['dong_cd'][:5] not in jurisdiction for a in gaps)
        for assignment in gaps:
            scopes.update(jurisdiction.get(assignment['dong_cd'][:5],()))
        with self.store.connection() as db:
            calls=db.execute('SELECT COUNT(*) FROM llm_calls WHERE run_id=?',(state['run_id'],)).fetchone()[0]
        limit=self.settings.llm_max_calls if proposal.get('workflow_version')=='regional-workflow-1' else min(6,self.settings.llm_max_calls)
        remaining=max(0,limit-calls)
        task={'goal':'지역 집단 자원 부족을 보완할 정책 후보를 조사하세요. 개인 자격·정원·배정은 확정하지 마세요.',
              'scopes':sorted(scopes),'query':'','max_steps':max(1,remaining-2 if proposal.get('workflow_version') and remaining>=5 else remaining)}
        if current:
            task['goal']='필요 가설과 명시된 조사 사유에 따라 정책 후보를 확인하세요. 후보 수로 정책 부재를 추정하지 말고 개인 자격·정원·배정을 확정하지 마세요. 조사 사유: '+', '.join(sorted({reason for row in gaps for reason in row['policy_gap']['research_reasons']}))
        if proposal.get('workflow_version'):
            task['goal']+=' 검색 후 적합한 후보의 상세 원문을 확인하고 근거를 반환하세요. 욕구 가설: '+', '.join(sorted({n for a in gaps for n in a.get('needs',[])}))+'; 기준일: '+proposal['task']['as_of']
            task['goal']+=' 요청 집단(관측 모집단과 동등함을 뜻하지 않음): '+json.dumps({k:proposal['task'].get(k) for k in ('sgg','sex','age_group','ym','dong_cd')},ensure_ascii=False)
            task['goal']+=' 명백히 대상 연령·관할이 다른 정책은 현행 후보에서 제외하고 대상 조건을 설명하세요.'
        else:
            groups=sorted({str(a.get('sex','미분류'))+'/'+str(a.get('age_group',a.get('age_band','미분류'))) for a in gaps})
            task['goal']+=' 요청 집단(성별/연령; 개별 자격 미확인): '+', '.join(groups)
            task['goal']+=' 요청 집단에 명백히 해당하지 않는 정책은 제외하세요.'
        emit=self.regional_emit(state)
        emit('policy-delegate','supervisor','policy',{'goal':task['goal'],'task':task,'gap_count':len(gaps),'remaining_calls':remaining})
        cached=next((t['payload']['result'] for t in self.store.traces(state['run_id'],limit=1000)
                     if t['kind']=='agent_message' and t['payload'].get('result_kind')=='regional_policy_candidates'),None)
        result=cached
        if result is None:
            result=self.policy_agent.run(state['run_id'],state['scenario']['sim_time'],task) if remaining and not unsupported else {
                'status':'unsupported_scope' if unsupported else 'call_limit','recommendations':[],'human_review_required':True,'allocation_performed':False}
            emit('policy-result','policy','supervisor',{'result_kind':'regional_policy_candidates','result':result})
        self.node_event(state,'policy',result,started)
        proposal['policy_research']={'candidate_funnel':result.get('candidate_funnel'),'status':result['status'],'candidates':result.get('recommendations',[]),
            'search_complete_within_scope':result.get('search_complete_within_scope',False),'search_scope':result.get('search_scope'),
            'gap_count':len(gaps),'task':task,'coverage':result.get('coverage'),'steps':result.get('steps',0),'eligibility_verified':False,'remaining_capacity':None,
            'allocation_performed':False,'human_review_required':True}
        if current:
            from backend.tools.regional_resources import policy_gap
            proposal['policy_research']['research_request_count']=len(gaps)
            proposal['policy_research']['gap_count_definition']='segments_requiring_research_not_verified_field_gaps'
            proposal['policy_research']['research_reasons']=sorted({reason for row in gaps for reason in row['policy_gap']['research_reasons']})
            proposal['assignments']=[{**row,'policy_gap':policy_gap(row,state['scenario']['payload'].get('policy_research_requested') is True,proposal['policy_research'])} if row['policy_gap']['research_needed'] else row for row in proposal['assignments']]
            proposal['workflow']={**proposal['workflow'],'assignments':proposal['assignments']}
        proposal.pop('snapshot_version',None);proposal['snapshot_version']=digest(proposal)
        return {'proposal':proposal}

    def policy_alternatives_node(self,state):
        started=time.monotonic()
        proposal=dict(state['proposal']);task=proposal['task']
        dongs=list({r['dong_cd']:{'dong_cd':r['dong_cd'],'dong_nm':r['dong_nm']} for r in proposal['assessment']['segments']}.values())
        scope={'sgg':task['sgg'],'ym':task['ym'],'as_of':task['as_of'],'target_groups':[task['sex']+'/'+task['age_group']],'synthetic_future':bool(task.get('future_id'))}
        self.regional_emit(state)('alternatives-delegate','supervisor','policy_design',{'goal':'기존 후보 유무와 무관하게 동별 정책 대안 세 개를 작성하세요.','scope':scope})
        result=self.policy_designer.propose(state['run_id'],state['run_id'],scope,dongs,[proposal])
        proposal['policy_alternatives']={'owner_id':state['run_id'],'dong_count':len(result),'alternatives_per_dong':3}
        self.regional_emit(state)('alternatives-result','policy_design','supervisor',{'dong_count':len(result),'alternatives_per_dong':3,'template_sets':sum(r['generation_mode']=='template_fallback' for r in result)})
        self.node_event(state,'policy_design',{'status':'needs_evidence','dong_count':len(result)},started)
        proposal.pop('snapshot_version',None);proposal['snapshot_version']=digest(proposal)
        return {'proposal':proposal}

    def policy_design_node(self,state):
        started=time.monotonic();proposal=dict(state['proposal'])
        self.regional_emit(state)('design-delegate','supervisor','policy_design',{'goal':'확인된 검색 공백의 유사 사례를 조사하고 현지 적용 초안을 작성하세요.'})
        proposal['policy_design']=self.policy_designer.run(state['run_id'],state['scenario']['sim_time'],proposal)
        self.node_event(state,'policy_design',proposal['policy_design'],started)
        proposal.pop('snapshot_version',None);proposal['snapshot_version']=digest(proposal)
        return {'proposal':proposal}

    def approval_node(self, state):
        started = time.monotonic()
        decision = interrupt({'snapshot_version': state['proposal']['snapshot_version'], 'proposal': state['proposal']})
        self.node_event(state, 'approval', decision, started)
        return {'decision': decision}

    def link_node(self, state):
        started = time.monotonic()
        with self.store.connection(write=True) as db:
            existing = db.execute('SELECT body FROM linkages WHERE run_id=?', (state['run_id'],)).fetchone()
            if existing:
                self.update_run(db, state['run_id'], status='completed', ended_at=json.loads(existing['body'])['created_at'], error=None)
                return {}
            crisis = bool(state.get('crisis'))
            approval = None
            local_action = state.get('local_action', '')
            if not crisis and not local_action:
                row = db.execute('SELECT body FROM approvals WHERE run_id=?', (state['run_id'],)).fetchone()
                approval = Approval.model_validate_json(row['body']) if row else None
                if (not approval or approval.status != 'approved' or
                        approval.snapshot_version != state['proposal']['snapshot_version']):
                    raise ValueError('link requires approval of this exact snapshot')
            now = utcnow()
            kind = 'crisis' if crisis else local_action or state['proposal']['scope']
            local_text = '위기 신호를 담당자가 확인할 로컬 알림' if crisis else ('선별 질문 준비·담당자 확인 요청' if local_action == 'screening_requested' else '개인 판정·응답을 담당자가 확인할 인계 요청')
            linkage = {'run_id': state['run_id'], 'kind': kind,
                       'fake': self.settings.llm_mode == 'fake', 'external_delivery': False, 'created_at': now.isoformat(),
                       'draft': {'text': local_text, 'resource_ids': []} if crisis or local_action else state['proposal']['draft'],
                       'followup_at': None if crisis or local_action else (now + timedelta(days=7)).isoformat(),
                       'snapshot_version': approval.snapshot_version if approval else None}
            db.execute('INSERT INTO linkages VALUES (?,?)', (state['run_id'], json.dumps(linkage)))
            alert = Alert(id=f"link-{state['run_id']}", run_id=state['run_id'],
                approval_id=approval.id if approval else None, type=kind if crisis or local_action else 'linkage_completed',
                status='created', created_at=now)
            db.execute('INSERT INTO alerts(id,run_id,body) VALUES (?,?,?)', (alert.id, alert.run_id, alert.model_dump_json()))
            self.once(db, state, 'link', 'node_end', linkage, 'link', latency_ms=(time.monotonic()-started)*1000)
            self.once(db, state, 'link-alert', 'alert', alert.model_dump(mode='json'))
            self.once(db, state, 'run-end', 'run_end', {'status': 'completed'})
            self.update_run(db, state['run_id'], status='completed', ended_at=now, error=None)
        return {}

    def reject_node(self, state):
        with self.store.connection(write=True) as db:
            self.once(db, state, 'run-end', 'run_end', {'status': 'rejected'})
            self.update_run(db, state['run_id'], status='rejected', ended_at=utcnow(), error=None)
        return {}

    def question_node(self, state):
        route = state['question_route']
        payload = state['scenario']['payload']
        if route == 'history':
            result = {'runs': self.store.list_runs(20)}
        elif route == 'classify':
            result = self.agents.call(state['run_id'], state['scenario']['sim_time'], 'analysis', payload).model_dump()
        elif route == 'match' and payload.get('match_request'):
            result = match(load_catalog(self.settings.catalog_path), MatchRequest.model_validate(payload['match_request']))
        else:
            result = {'review_required': True, 'reason': '담당자 검토 또는 명시적 매칭 조건이 필요합니다.'}
        with self.store.connection(write=True) as db:
            self.once(db, state, 'question-result', 'tool_result', {'route': route, 'result': result}, 'supervisor')
            self.once(db, state, 'run-end', 'run_end', {'status': 'completed'})
            self.update_run(db, state['run_id'], status='completed', ended_at=utcnow(), error=None)
        return {}

    def policy_node(self, state):
        started = time.monotonic()
        # A completed worker result survives a crash before LangGraph checkpoints this node.
        with self.store.connection() as db:
            done = db.execute('SELECT 1 FROM effects WHERE run_id=? AND name=?', (state['run_id'], 'policy')).fetchone()
        if done:return {}
        result = self.policy_agent.run(state['run_id'], state['scenario']['sim_time'], state['scenario']['payload'])
        with self.store.connection(write=True) as db:
            self.once(db, state, 'policy', 'node_end', result, 'policy', latency_ms=(time.monotonic()-started)*1000)
            self.once(db, state, 'run-end', 'run_end', {'status': 'completed'})
            self.update_run(db, state['run_id'], status='completed', ended_at=utcnow(), error=None)
        return {}

    @contextmanager
    def graph(self):
        with SqliteSaver.from_conn_string(str(self.settings.runtime_dir / 'checkpoints.sqlite3')) as saver:
            builder = StateGraph(State)
            for name, action in [('supervisor', self.supervisor), ('classify', self.classify_node), ('match', self.match_node),
                                 ('approval', self.approval_node), ('link', self.link_node), ('reject', self.reject_node), ('question', self.question_node), ('policy', self.policy_node)]:
                builder.add_node(name, action)
            builder.add_node('workflow_analyze',self.workflow_analyze)
            builder.add_node('workflow_statistics',self.workflow_statistics)
            builder.add_node('workflow_proposal',self.workflow_proposal)
            builder.add_edge('workflow_analyze','workflow_statistics')
            builder.add_node('workflow_match',self.workflow_match)
            builder.add_edge('workflow_statistics','workflow_match')
            builder.add_edge('workflow_match','workflow_proposal')
            def after_research(s):
                if s['scenario']['payload'].get('policy_proposal_version')=='three-1':return 'policy_alternatives'
                return 'approval'
            builder.add_node('policy_alternatives',self.policy_alternatives_node)
            builder.add_edge('policy_alternatives','approval')
            def workflow_research(s):
                if s['classification']['metadata'].get('policy_gap_version')=='policy-gap-1':
                    return 'regional_policy' if (s['scenario']['payload'].get('research_gaps') is True or s['scenario']['payload'].get('policy_research_requested') is True) and any(a.get('policy_gap',{}).get('research_needed') for a in s['proposal']['assignments']) else after_research(s)
                return 'regional_policy' if s['scenario']['payload'].get('research_gaps') is True and any(a.get('catalog_filter_performed') and a.get('shortfall',0)>0 for a in s['proposal']['assignments']) else after_research(s)
            builder.add_conditional_edges('workflow_proposal',workflow_research)
            builder.add_node('regional_prepare',self.regional_prepare)
            builder.add_node('regional_analyst',lambda s:self.regional_step(s,'analyze'))
            builder.add_node('regional_reviewer',lambda s:self.regional_step(s,'review'))
            builder.add_node('regional_lookup',lambda s:self.regional_step(s,'lookup'))
            builder.add_node('regional_finalize',self.regional_finalize)
            for node in ('regional_prepare','regional_analyst','regional_reviewer','regional_lookup'):
                builder.add_conditional_edges(node,lambda s:s['regional']['next'])
            builder.add_edge('regional_finalize','match')
            builder.add_edge(START, 'supervisor')
            builder.add_conditional_edges('supervisor', lambda s: 'link' if s['crisis'] else 'policy' if s['scenario']['type'] == 'policy' else ('question' if s.get('question_route') in ('history', 'human', 'classify', 'match') else 'classify'))
            builder.add_conditional_edges('classify', lambda s: 'link' if s.get('local_action') else 'workflow_analyze' if s['scenario']['payload'].get('workflow_version') else 'regional_prepare' if s['scenario']['payload'].get('collaboration') is True and s['classification'].get('metadata',{}).get('analysis_version')=='v3' else 'match')
            builder.add_node('regional_policy',self.regional_policy_node)
            builder.add_conditional_edges('match',lambda s:'regional_policy' if s['scenario']['payload'].get('research_gaps') is True and s['proposal'].get('collaboration') and any(a.get('shortfall',0)>0 for a in s['proposal']['assignments']) else 'approval')
            builder.add_node('policy_design',self.policy_design_node)
            builder.add_conditional_edges('regional_policy',lambda s:'policy_alternatives' if s['scenario']['payload'].get('policy_proposal_version')=='three-1' else 'approval' if s['scenario']['payload'].get('policy_proposal_version')=='batch-child' else 'policy_design' if s['proposal'].get('workflow_version') and not s['proposal']['policy_research'].get('candidates') else 'approval')
            builder.add_edge('policy_design','approval')
            builder.add_conditional_edges('approval', lambda s: 'link' if s['decision']['status'] == 'approved' else 'reject')
            builder.add_edge('link', END)
            builder.add_edge('reject', END)
            builder.add_edge('question', END)
            builder.add_edge('policy', END)
            yield builder.compile(checkpointer=saver)

    def publish_approval(self, state):
        approval = Approval(id=f"approval-{state['run_id']}", run_id=state['run_id'],
                            snapshot_version=state['proposal']['snapshot_version'], status='pending')
        with self.store.connection(write=True) as db:
            if db.execute('SELECT 1 FROM approvals WHERE run_id=?', (state['run_id'],)).fetchone():
                return
            db.execute('INSERT INTO approvals VALUES (?,?,?,?)', (approval.id, approval.run_id, approval.model_dump_json(), json.dumps(state['proposal'])))
            now = utcnow()
            alert = Alert(id=approval.id, run_id=approval.run_id, approval_id=approval.id,
                          type='approval_requested', status='created', created_at=now)
            db.execute('INSERT INTO alerts(id,run_id,body) VALUES (?,?,?)', (alert.id, alert.run_id, alert.model_dump_json()))
            self.once(db, state, 'interrupt', 'interrupt', approval.model_dump(mode='json'), 'approval')
            self.once(db, state, 'approval-alert', 'alert', alert.model_dump(mode='json'))
            self.update_run(db, state['run_id'], status='awaiting_approval')

    def drive(self, run_id, initial=None):
        if self.store.get_run(run_id).llm_mode != self.settings.llm_mode:
            raise ValueError('restore the original LLM_MODE before resuming this run')
        config = {'configurable': {'thread_id': run_id}}
        with self.lock(run_id), self.graph() as graph, tracing_context(enabled=False):
            run=self.store.get_run(run_id)
            if run.status=='cancelled':return run
            if run.scenario_id=='regional-workflow-future' and run.status=='failed':return run
            if run.status=='pending':
                with self.store.connection(write=True) as db:self.update_run(db,run_id,status='running')
            snapshot = graph.get_state(config)
            with self.store.connection() as db:
                row = db.execute('SELECT body FROM approvals WHERE run_id=?', (run_id,)).fetchone()
            decision = Approval.model_validate_json(row['body']) if row else None
            command = initial
            if not snapshot.values and initial is None:
                with self.store.connection() as db:
                    row = db.execute('SELECT scenario FROM workflows WHERE run_id=?', (run_id,)).fetchone()
                if row is None:
                    raise KeyError(run_id)
                command = {'run_id': run_id, 'scenario': json.loads(row['scenario'])}
            if snapshot.next and decision and decision.status != 'pending' and 'approval' in snapshot.next:
                command = Command(resume=decision.model_dump(mode='json'))
            try:
                if command is not None or snapshot.next:
                    graph.invoke(command, config)
                snapshot = graph.get_state(config)
                if 'approval' in snapshot.next:
                    self.publish_approval(snapshot.values)
            except Exception as exc:
                with self.store.connection(write=True) as db:
                    self.update_run(db, run_id, status='failed', error=type(exc).__name__, ended_at=utcnow())
                    scenario = json.loads(db.execute('SELECT scenario FROM workflows WHERE run_id=?', (run_id,)).fetchone()[0])
                    self.store._trace(db, run_id, scenario['sim_time'], 'error', {'type': type(exc).__name__, 'message': 'run failed; see typed tool/agent error'})
                try:
                    from backend.policy.alternatives import failed_run
                    failed_run(self,run_id,scenario)
                except Exception:pass  # Preserve the original failure when source/DB recovery is unavailable.
                raise
        return self.store.get_run(run_id)

    def register(self, scenario):
        if 'revision' in scenario.payload:raise ValueError('use the revision endpoint for linked reruns')
        if scenario.payload.get('workflow_version'):
            from backend.tools.regional_task import task_from
            if scenario.type != 'monthly':raise ValueError('regional task requires monthly scenario')
            task_from(scenario.payload)
            scenario=scenario.model_copy(update={'payload':{'policy_proposal_version':'three-1',**scenario.payload,'statistics_version':'2'}})
        if 'person' in scenario.payload:
            person = PersonCase.model_validate(scenario.payload['person'])
            if person.reply_to:
                with self.store.connection() as db:
                    row = db.execute('SELECT scenario FROM workflows WHERE run_id=?', (person.reply_to,)).fetchone()
                parent = Scenario.model_validate_json(row['scenario']) if row else None
                if scenario.type != 'case' or parent is None or parent.type != 'admin' or self.store.get_run(person.reply_to).status != 'completed':
                    raise ValueError('reply_to requires completed admin run')
                original = PersonCase.model_validate(parent.payload['person'])
                if (person.person_id, person.age, person.sgg) != (original.person_id, original.age, original.sgg):
                    raise ValueError('reply_to person mismatch')
        run_id = str(uuid4())
        run = self.new_run(scenario,run_id)
        with self.lock(run_id):
            self.store.create_run(run)
            with self.store.connection(write=True) as db:
                db.execute('INSERT INTO workflows VALUES (?,?)', (run_id, scenario.model_dump_json()))
            return run

    def new_run(self,scenario,run_id):
        return Run(id=run_id, scenario_id=scenario.id, thread_id=run_id, status='running',
            data_mode=self.settings.data_mode, llm_mode=self.settings.llm_mode, input_version=digest(scenario.model_dump(mode='json')),
            rule_version='person-v02' if 'person' in scenario.payload else 'seohee-region-2' if scenario.type=='monthly' and scenario.payload.get('analysis_version')!='legacy-v1' else 'provisional-1', model_version=(self.settings.openai_model or 'unconfigured') if self.settings.llm_mode == 'live' else 'fake-v1', prompt_version='agents-v1', catalog_version='seohee-resources-3' if self.settings.resource_catalog == 'v3' else 'curated-20261018-1' if self.settings.resource_catalog == 'curated' else ('synthetic-1' if self.settings.data_mode == 'sample' else 'local'), started_at=utcnow())

    def start(self, scenario):
        return self.drive(self.register(scenario).id)

    def execute(self, run_id):
        try:
            self.drive(run_id)
        except Exception:
            pass  # drive persists failure; background work must not raise after the HTTP response.

    def approval(self, run_id):
        with self.store.connection() as db:
            row = db.execute('SELECT body,proposal FROM approvals WHERE run_id=?', (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return {'approval': json.loads(row['body']), 'proposal': json.loads(row['proposal'])}

    def decide(self, run_id, snapshot_version, status, operator, reason=None):
        if self.store.get_run(run_id).llm_mode != self.settings.llm_mode:
            raise ValueError('restore the original LLM_MODE before deciding this run')
        with self.lock(run_id), self.graph() as graph:
            current = self.approval(run_id)['approval']
            if current['snapshot_version'] != snapshot_version:
                raise ValueError('snapshot mismatch')
            if current['status'] != 'pending':
                if current['status'] != status:
                    raise ValueError('approval already decided differently')
                return self.drive(run_id)
            state = graph.get_state({'configurable': {'thread_id': run_id}})
            if 'approval' not in state.next or state.values['proposal']['snapshot_version'] != snapshot_version:
                raise ValueError('resumable approval checkpoint not ready')
            decision = Approval.model_validate({**current, 'status': status, 'operator': operator, 'reason': reason, 'decided_at': utcnow()})
            with self.store.connection(write=True) as db:
                changed=db.execute("UPDATE approvals SET body=? WHERE run_id=? AND json_extract(body,'$.status')='pending' AND json_extract(body,'$.snapshot_version')=?", (decision.model_dump_json(),run_id,snapshot_version))
                if changed.rowcount!=1:raise ValueError('approval changed; refresh before deciding')
                self.once(db, state.values, 'decision', 'approval', decision.model_dump(mode='json'), 'approval')
            return self.drive(run_id)

    def recover(self):
        with self.store.connection() as db:
            ids = [r[0] for r in db.execute('SELECT run_id FROM workflows WHERE run_id NOT IN (SELECT run_id FROM regional_batch_children) ORDER BY rowid')]
            batches=[r[0] for r in db.execute('SELECT id FROM regional_batches ORDER BY rowid')]
        for run_id in ids:
            try:
                self.drive(run_id)
            except Exception:
                pass  # Failure is persisted by drive; other runs must still recover.

        from backend.regional_batch import execute
        for identifier in batches:
            try:execute(self,identifier)
            except Exception:pass  # Keep other batches recoverable when a stored mode differs.

        from backend.policy.alternative_regeneration import recover
        recover(self)
