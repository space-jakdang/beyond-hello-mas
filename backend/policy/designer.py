"""Supervisor-delegated, two-decision policy drafting with durable tool evidence."""
import json
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from backend.policy.design_contracts import Gap,PolicyDraft,validate_draft


class DesignDecision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:Literal['research','finish','human']
    query:str=Field(max_length=200)
    reason:str=Field(min_length=1,max_length=1000)
    draft:PolicyDraft|None


def fake_design(payload):
    if not payload['observation']:
        return {'action':'research','query':'관계','reason':'fake: 공식 참고 사례 조회','draft':None}
    source=payload['observation']['analogues'][0]['source'] if payload['observation'].get('analogues') else None
    if not source:return {'action':'human','query':'','reason':'참고 근거 부족','draft':None}
    draft={'status':'draft','title':'fake: 지역 관계 연결 시범안','problem_evidence_ids':[r['evidence_id'] for r in payload['needs']],
        'target_group':payload['target_group'],'proposed_service':'담당자와 지역 기관이 방문·연결 활동의 시범 운영 가능성을 검토합니다.',
        'adaptations':[{'source_policy_ids':[source['policy_id']],'local_difference':'원 정책과 현지 관할·대상집단의 적합성은 미확인입니다.',
            'proposed_change':'현지 대상 요건과 운영기관을 확인한 뒤 참여 방식과 안내 절차를 조정합니다.','verification_needed':['대상 요건','현지 운영기관']}],
        'citations':[{'policy_id':source['policy_id'],'field':'title','quote':source['title']}],
        'operating_steps':['현지 수요·대상 확인','협력기관·예산 확인','검토 승인 후 시범 운영 계획 수립'],
        'required_roles':['정책 담당자','지역 협력기관'],
        'feasibility_checks':['예산·법적 근거·수용량 미확인'],'equity_risks':['참여 낙인과 접근성 격차 확인'],
        'evaluation':{'outcome':'연결 서비스 참여와 유지','baseline_needed':'실제 참여 기준선·대상 분모',
            'comparison_method':'유사 집단과 사전·사후 비교 가능성 검토','observation_period':'담당자와 합의 필요',
            'success_criterion_to_agree':'참여 유지 기준 합의','stop_criterion_to_agree':'부담·민원 발생 시 중단 기준 합의'},
        'reviewer_questions':['현지 시행 근거와 운영 주체를 확인했습니까?']}
    return {'action':'finish','query':'','reason':'fake: 실제 정책 효과가 아닌 계약 검증용 초안','draft':draft}


class PolicyDesigner:
    def __init__(self,store,settings,agents,policy_agent):
        self.store,self.settings,self.agents,self.policy_agent=store,settings,agents,policy_agent
        with store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS policy_alternative_research (owner_id TEXT NOT NULL,cache_key TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(owner_id,cache_key))')
            db.execute('CREATE TABLE IF NOT EXISTS policy_alternative_sets (owner_id TEXT NOT NULL,dong_cd TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(owner_id,dong_cd))')
            db.execute('CREATE TABLE IF NOT EXISTS policy_designs (run_id TEXT PRIMARY KEY REFERENCES runs(id), body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS policy_design_observations (run_id TEXT PRIMARY KEY REFERENCES runs(id), body TEXT NOT NULL)')

    def run(self,run_id,sim_ts,proposal):
        with self.store.connection() as db:
            saved=db.execute('SELECT body FROM policy_designs WHERE run_id=?',(run_id,)).fetchone()
            observation=db.execute('SELECT body FROM policy_design_observations WHERE run_id=?',(run_id,)).fetchone()
        if saved:return json.loads(saved[0])
        research=proposal.get('policy_research') or {};task=proposal['task']
        gaps=[a for a in proposal['assignments'] if a.get('catalog_filter_performed') and a.get('shortfall',0)>0]
        scope=research.get('search_scope') or {}
        complete=research.get('search_complete_within_scope') is True and research.get('status')=='no_verified_candidates'
        gap=Gap(state='candidate_found' if research.get('candidates') else 'no_verified_candidates' if complete else 'search_incomplete',
            catalog_shortfall=sum(a['shortfall'] for a in gaps),search_scope=[json.dumps(scope,ensure_ascii=False)] if scope else ['검색 범위 미확인'],
            checked_at=(research.get('coverage') or {}).get('fetched_at') or task['as_of'],complete_within_scope=complete,limitations=['API 등록과 검색어 범위 안의 공백이며 현실의 정책 부재를 뜻하지 않습니다.'])
        # Keep original source time and tool observations stable across checkpoint replay.
        observation=json.loads(observation[0]) if observation else None
        if observation:gap=Gap.model_validate(observation['gap'])
        result={'status':'needs_evidence','reason':'policy_search_incomplete','gap':gap.model_dump(),
                'human_review_required':True,'allocation_performed':False}
        if not gaps or not complete:
            result['reason']='existing_candidates_require_review' if research.get('candidates') else 'policy_search_incomplete'
            return self.save(run_id,sim_ts,result)
        local_scope={'11230':'gangnam','32010':'chuncheon'}[task['sgg']]
        needs=[{'evidence_id':a['evidence_id'],'dong_nm':a['dong_nm'],'stage':a['stage'],'needs':a['needs'],
                'uncovered_needs':a.get('uncovered_needs',[]),'statistical_context':{k:v for k,v in (a.get('statistical_context') or {}).items() if k in ('priority_midrank','need_basis','measured_components','base_stage_stable')}} for a in gaps[:5]]
        target=f"{task['sgg']} / {task['sex']} / {dict(youth='청년',midlife='중년',prime='장년',elderly='노년')[task['age_group']]} / {task['ym']}"
        try:
            for step in range(1 if observation else 0,2):
                view=None
                if observation:
                    tool=observation['result']
                    view={k:v for k,v in tool.items() if k!='analogues'}
                    view['analogues']=[{**a,'source':{**a['source'],'fields':{k:v for k,v in a['source']['fields'].items() if len(v)<=200},
                        'previews':{k:v[:200] for k,v in a['source']['fields'].items() if len(v)>200 and k in ('support','eligibility','criteria')}}} for a in tool.get('analogues',[])[:5]]
                payload={'gap':gap.model_dump(),'target_group':target,'needs':needs,'observation':view,'omitted_gap_segments':max(0,len(gaps)-len(needs)),'steps_remaining':2-step}
                decision=self.agents.call(run_id,sim_ts,'policy_design',payload)
                self.store.append_trace(run_id,sim_ts,'agent_message',{'sender':'policy_design','recipient':'supervisor','decision':decision.model_dump(mode='json')},'policy_design')
                if decision.action=='research':
                    if observation or not decision.query.strip():raise ValueError('invalid_design_research')
                    args={'local_scope':local_scope,'query':decision.query,'target_group':target}
                    self.store.append_trace(run_id,sim_ts,'tool_call',{'tool':'policy_analogues','arguments':args},'policy_design')
                    tool=self.policy_agent.call_tool('policy_analogues',args)
                    observation={'gap':gap.model_dump(),'result':tool}
                    with self.store.connection(write=True) as db:
                        db.execute('INSERT INTO policy_design_observations VALUES (?,?)',(run_id,json.dumps(observation,ensure_ascii=False)))
                        self.store._trace(db,run_id,sim_ts,'tool_result',{'tool':'policy_analogues','result':tool},'policy_design')
                    if tool.get('status')!='evidence_available':
                        result.update(reason='analogue_evidence_unavailable',research=tool);break
                    continue
                if decision.action=='human':
                    result.update(status='needs_human',reason=decision.reason);break
                if not observation or observation['result'].get('status')!='evidence_available' or decision.draft is None:
                    raise ValueError('missing_design_evidence')
                sources=[a['source'] for a in observation['result']['analogues']]
                validated=validate_draft(decision.draft.model_dump(),[a['evidence_id'] for a in gaps],gap.model_dump(),sources)
                result={**validated,'status':validated['draft']['status'],'research':observation['result'],
                    'target_group':target,'considered_evidence_ids':[a['evidence_id'] for a in needs],
                    'omitted_gap_segments':max(0,len(gaps)-len(needs)),'mode':self.settings.llm_mode,'allocation_performed':False}
                break
        except Exception as exc:
            result.update(status='needs_evidence',reason='design_model_tool_or_validation_failed',error_type=type(exc).__name__)
        return self.save(run_id,sim_ts,result)

    def save(self,run_id,sim_ts,result):
        with self.store.connection(write=True) as db:
            db.execute('INSERT INTO policy_designs VALUES (?,?)',(run_id,json.dumps(result,ensure_ascii=False)))
            self.store._trace(db,run_id,sim_ts,'agent_message',{'sender':'policy_design','recipient':'supervisor','result_kind':'policy_design','result':result},'policy_design')
        return result

    def propose(self,owner_id,run_id,scope,dongs,proposals):
        from backend.policy.alternatives import generate
        return generate(self,owner_id,run_id,scope,dongs,proposals)
