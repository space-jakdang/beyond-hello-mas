import json
import time
from pathlib import Path

from openai import OpenAI

from backend.agents.schemas import SCHEMAS
from backend.tools.indicators import digest

PROMPTS = Path(__file__).resolve().parents[1] / 'prompts'


def fake(role, payload):
    if role=='workflow_single':
        return {'action':'lookup' if not payload['observations'] and '추이' in payload['task']['goal'] else 'finish',
            'tool':'source_check' if payload['methodology']['period_role']!='observed month' else 'trend','reason':'fake: 동일 근거를 한 분석가가 자체 확인합니다.',
            'plan':{'summary':'fake: 관측 근거와 자료 한계를 바탕으로 한 지역 조사 가설입니다.',
                    'priority_evidence_ids':[r['evidence_id'] for r in payload['facts'] if r['evidence_id'] not in payload['summary']['blocked_evidence_ids']][:5]}}
    if role == 'workflow_analyst':
        blocked=set(((payload.get('feedback') or {}).get('statistics') or {}).get('blocked_evidence_ids',[]))
        return {'summary':'fake: 관측 근거와 자료 한계를 검토한 잠정 지역 분석입니다.',
                'priority_evidence_ids':[f['evidence_id'] for f in payload['facts'] if f['evidence_id'] not in blocked][:5]}
    if role == 'workflow_statistics':
        blocked=payload['summary']['blocked_evidence_ids']
        if payload.get('review_version')=='statistics-review-2':
            action='revise' if set(blocked)&set(payload['plan']['priority_evidence_ids']) else 'lookup' if payload['review_phase']=='initial' and not payload['observations'] and '추이' in payload['task']['goal'] else 'finish'
            return {'action':action,'tool':'source_check' if payload['period_aggregate'] or blocked else 'trend',
                    'reason':'fake: 제공된 요약과 보완된 분석의 범위를 검토합니다.','blocked_evidence_ids':blocked}
        return {'action':'lookup' if not payload['observations'] else 'revise' if set(blocked)&set(payload['plan']['priority_evidence_ids']) else 'finish',
                'tool':'source_check' if payload['period_aggregate'] or blocked else 'trend',
                'reason':'fake: 통계 도구의 관측값과 결측을 확인합니다.','blocked_evidence_ids':blocked}
    if role == 'workflow_matching':
        return {'selections':[{'evidence_id':r['evidence_id'],'resource_ids':[c[payload['candidate_columns'].index('id')] if 'candidate_columns' in payload else c['id'] for c in r['candidates']],
                              'reason':'fake: 관측 욕구 가설과 필수 필터를 통과한 조건부 후보'} for r in payload['choices']],
                'summary':'fake: 담당자 확인이 필요한 지역 자원 제안입니다.'}
    if role == 'policy_alternatives':
        if payload.get('design_version')=='pinpoint-1':
            from backend.policy.pinpoint import fixture_design
            return {'action':'draft','information_requests':[],**fixture_design(payload)}
        from backend.policy.alternatives import templates
        return templates(payload)
    if role == 'policy_design':
        from backend.policy.designer import fake_design
        return fake_design(payload)
    if role == 'policy_decision':
        from backend.policy.agent import fake_decision
        return fake_decision(payload)
    if role in ('regional_worker','regional_planner'):
        if role=='regional_worker' and not payload['retrieved']:
            return {'action':'lookup','targets':[payload['observations']['facts'][0]['id']],
                    'reason':'fake source verification','plan':None}
        return {'action':'finish','targets':[],'reason':'fake protocol fixture',
                'plan':{**fake('regional_analyst',payload),'summary':'fake: 추가 조회 근거를 반영한 검토안입니다.'} if payload.get('retrieved') else fake('regional_analyst',payload)}
    if role == 'regional_analyst':
        return {'summary':'fake: 관측 대표 집단의 검토안이며 실제 모델 판단이 아닙니다.',
                'focus_ids':[r['id'] for r in payload['observations']['facts'][:3]],
                'limitations':payload['observations']['required_limitations']}
    if role == 'regional_audit':
        if payload['observations'].get('verification_required') and not payload['retrieved']:
            return {'action':'lookup','targets':[payload['observations']['facts'][0]['id']],
                    'concerns':['원천 상세 확인 필요'],'reason':'요청된 원천 검증을 수행합니다.'}
        return {'action':'revise' if payload['validation_issues'] else 'accept','targets':[],
                'concerns':payload['validation_issues'],'reason':'fake protocol check'}
    if role == 'regional_reviewer':
        return {'decision':'revise' if payload['validation_issues'] else 'accept','concerns':payload['validation_issues']}
    if role == 'analysis':
        return {'summary': 'fake: 입력 근거를 담당자가 검토해야 합니다.', 'causes': [], 'needs': [], 'review_required': True}
    if role == 'recommendations':
        return {'items': [{'resource_id': r['id'], 'explanation': f"fake: {r['name']} — {r['eligibility']}",
                           'evidence': [{'field': 'eligibility', 'value': r['eligibility']}]} for r in payload['candidates']]}
    if role == 'draft':
        return {'text': 'fake: 승인된 범위 안에서 담당자가 후속 확인할 안내 초안입니다. 실제 전달되지 않았습니다.',
                'resource_ids': payload['resource_ids']}
    text = payload.get('text', '')
    route = next((route for word, route in [('이력', 'history'), ('기록', 'history'), ('연계', 'link'),
                 ('전달', 'link'), ('추천', 'match'), ('자원', 'match'), ('원인', 'classify'), ('왜', 'classify')] if word in text), 'human')
    return {'route': route, 'reason': 'fake keyword fixture; not model performance'}


def validate_output(role, output, payload):
    parsed = schema_for(role,payload).model_validate(output)
    if role == 'recommendations':
        candidates = {r['id']: r for r in payload['candidates']}
        ids = [r.resource_id for r in parsed.items]
        if len(ids) != len(set(ids)) or set(ids) != set(candidates):
            raise ValueError('recommendation IDs differ from fixed candidates')
        for item in parsed.items:
            if not item.evidence:
                raise ValueError('recommendation requires field evidence')
            for evidence in item.evidence:
                if candidates[item.resource_id].get(evidence.field) != evidence.value:
                    raise ValueError('recommendation evidence differs from catalog')
    if role == 'draft' and not set(parsed.resource_ids) <= set(payload['resource_ids']):
        raise ValueError('draft contains unapproved resource IDs')
    return parsed


def schema_for(role,payload):
    if role=='policy_alternatives' and payload.get('design_version')=='pinpoint-1':
        from backend.policy.alternative_contracts import PinpointDecision
        return PinpointDecision
    return SCHEMAS[role]


class Agents:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        with store.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS llm_calls (
                run_id TEXT NOT NULL REFERENCES runs(id), call_key TEXT NOT NULL, role TEXT NOT NULL,
                status TEXT NOT NULL, reserve_usd REAL NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY(run_id,call_key))''')

    def call(self, run_id, sim_ts, role, payload):
        prompt = (PROMPTS / f'{role}.txt').read_text()
        model = self.settings.openai_model if self.settings.llm_mode == 'live' else 'fake-v1'
        call_key = digest({'role': role, 'payload': payload, 'prompt': prompt, 'model': model})
        schema = schema_for(role,payload)
        metadata = {'role': role, 'model': model, 'prompt_hash': digest(prompt), 'prompt': prompt,
                    'input': payload, 'mode': self.settings.llm_mode, 'retry': 0}
        output_limit = self.settings.policy_design_max_output_tokens if role == 'policy_alternatives' else self.settings.llm_max_output_tokens
        metadata['max_output_tokens'] = output_limit
        reserve = 0.0
        encoded = json.dumps({'prompt': prompt, 'payload': payload, 'schema': schema.model_json_schema()}, ensure_ascii=False)
        if len(encoded.encode()) > self.settings.llm_max_input_bytes:
            raise ValueError('LLM input budget exceeded')
        if self.settings.llm_mode == 'live':
            if not all((model, self.settings.llm_budget_usd, self.settings.input_usd_per_million,
                        self.settings.output_usd_per_million, self.settings.price_version)):
                raise ValueError('live requires model, positive budget and verified price configuration')
            reserve = ((len(encoded.encode()) + 8192) * self.settings.input_usd_per_million +
                       output_limit * self.settings.output_usd_per_million) / 1_000_000
        with self.store.connection(write=True) as db:
            existing = db.execute('SELECT status,body FROM llm_calls WHERE run_id=? AND call_key=?', (run_id, call_key)).fetchone()
            if existing:
                if existing['status'] == 'ok':
                    return validate_output(role, json.loads(existing['body'])['output'], payload)
                raise ValueError('previous call unresolved or failed; create a new run for retry')
            count = db.execute('SELECT COUNT(*) FROM llm_calls WHERE run_id=?', (run_id,)).fetchone()[0]
            cumulative_spent = db.execute('SELECT COALESCE(SUM(reserve_usd),0) FROM llm_calls').fetchone()[0]
            run_spent = db.execute('SELECT COALESCE(SUM(reserve_usd),0) FROM llm_calls WHERE run_id=?', (run_id,)).fetchone()[0]
            batch_table=db.execute("SELECT 1 FROM sqlite_master WHERE name='regional_batch_children'").fetchone()
            parent=db.execute('SELECT batch_id FROM regional_batch_children WHERE run_id=?',(run_id,)).fetchone() if batch_table else None
            if parent:
                run_spent=db.execute('SELECT COALESCE(SUM(reserve_usd),0) FROM llm_calls WHERE run_id IN (SELECT run_id FROM regional_batch_children WHERE batch_id=?)',(parent[0],)).fetchone()[0]
            over_run_budget = self.settings.llm_run_budget_usd is not None and run_spent + reserve > self.settings.llm_run_budget_usd
            if count >= self.settings.llm_max_calls or (reserve and (cumulative_spent + reserve > self.settings.llm_budget_usd or over_run_budget)):
                raise ValueError('LLM call or cost budget exceeded')
            db.execute('INSERT INTO llm_calls VALUES (?,?,?,?,?,?)', (run_id, call_key, role, 'pending', reserve, json.dumps(metadata)))
            self.store._trace(db, run_id, sim_ts, 'llm_call', metadata, 'supervisor' if role == 'route' else
                              {'analysis': 'classify', 'recommendations': 'match', 'draft': 'link', 'policy_decision': 'policy', 'policy_design':'policy_design','policy_alternatives':'policy_design', 'regional_analyst':'regional_analyst', 'regional_reviewer':'regional_reviewer', 'regional_worker':'regional_analyst', 'regional_planner':'regional_analyst', 'regional_audit':'regional_reviewer', 'workflow_analyst':'regional_analyst', 'workflow_single':'regional_analyst', 'workflow_statistics':'statistics', 'workflow_matching':'match'}[role])
        started = time.monotonic()
        tokens_in = tokens_out = 0
        actual = None
        try:
            if self.settings.llm_mode == 'fake':
                raw = fake(role, payload)
                actual = 0.0
            else:
                # No automatic retries: every charged attempt has a durable reservation.
                with OpenAI(api_key=self.settings.openai_api_key.get_secret_value(), timeout=self.settings.llm_timeout_seconds, max_retries=0) as client:
                    response = client.responses.parse(model=model, input=[{'role': 'system', 'content': prompt},
                        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}],
                        text_format=schema, max_output_tokens=output_limit, store=False)
                if response.status != 'completed' or response.output_parsed is None or response.usage is None:
                    raise ValueError('incomplete or refused structured response')
                raw = response.output_parsed.model_dump()
                tokens_in, tokens_out = response.usage.input_tokens, response.usage.output_tokens
                actual = (tokens_in*self.settings.input_usd_per_million + tokens_out*self.settings.output_usd_per_million) / 1_000_000
                metadata['returned_model'] = response.model
                metadata['usage'] = response.usage.model_dump(mode='json')
            parsed = validate_output(role, raw, payload)
            result = {**metadata, 'output': parsed.model_dump(), 'cost_usd': actual,
                      'price_version': self.settings.price_version, 'reserved_usd': reserve,
                      'cost_basis': 'uncached input price upper estimate; raw usage retained'}
            with self.store.connection(write=True) as db:
                db.execute('UPDATE llm_calls SET status=?,body=?,reserve_usd=? WHERE run_id=? AND call_key=?',
                           ('ok', json.dumps(result, ensure_ascii=False), max(reserve, actual), run_id, call_key))
                self.store._trace(db, run_id, sim_ts, 'llm_result', result,
                    tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=(time.monotonic()-started)*1000)
            return parsed
        except Exception as exc:
            # SDK exceptions may contain request details or credentials; persist only the type.
            error = {'role': role, 'type': type(exc).__name__, 'reserved_usd': reserve, 'cost_usd': actual, 'tokens_in': tokens_in, 'tokens_out': tokens_out}
            with self.store.connection(write=True) as db:
                db.execute('UPDATE llm_calls SET status=?,body=?,reserve_usd=? WHERE run_id=? AND call_key=?',
                           ('error', json.dumps(error), max(reserve, actual or 0), run_id, call_key))
                self.store._trace(db, run_id, sim_ts, 'error', error)
            raise ValueError(f'agent {role} failed ({type(exc).__name__})') from None
