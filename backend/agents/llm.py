import json
import time
from pathlib import Path

from openai import OpenAI

from backend.agents.schemas import SCHEMAS
from backend.tools.indicators import digest

PROMPTS = Path(__file__).resolve().parents[1] / 'prompts'


def fake(role, payload):
    if role == 'policy_decision':
        from backend.policy.agent import fake_decision
        return fake_decision(payload)
    if role == 'regional_worker':
        return {'action':'finish','targets':[],'reason':'fake protocol fixture',
                'plan':fake('regional_analyst',payload)}
    if role == 'regional_analyst':
        return {'summary':'fake: 관측 대표 집단의 검토안이며 실제 모델 판단이 아닙니다.',
                'focus_ids':[r['id'] for r in payload['observations']['facts'][:3]],
                'limitations':payload['observations']['required_limitations']}
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
    parsed = SCHEMAS[role].model_validate(output)
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
        schema = SCHEMAS[role]
        metadata = {'role': role, 'model': model, 'prompt_hash': digest(prompt), 'prompt': prompt,
                    'input': payload, 'mode': self.settings.llm_mode, 'retry': 0}
        reserve = 0.0
        encoded = json.dumps({'prompt': prompt, 'payload': payload, 'schema': schema.model_json_schema()}, ensure_ascii=False)
        if len(encoded.encode()) > self.settings.llm_max_input_bytes:
            raise ValueError('LLM input budget exceeded')
        if self.settings.llm_mode == 'live':
            if not all((model, self.settings.llm_budget_usd, self.settings.input_usd_per_million,
                        self.settings.output_usd_per_million, self.settings.price_version)):
                raise ValueError('live requires model, positive budget and verified price configuration')
            reserve = ((len(encoded.encode()) + 8192) * self.settings.input_usd_per_million +
                       self.settings.llm_max_output_tokens * self.settings.output_usd_per_million) / 1_000_000
        with self.store.connection(write=True) as db:
            existing = db.execute('SELECT status,body FROM llm_calls WHERE run_id=? AND call_key=?', (run_id, call_key)).fetchone()
            if existing:
                if existing['status'] == 'ok':
                    return validate_output(role, json.loads(existing['body'])['output'], payload)
                raise ValueError('previous call unresolved or failed; create a new run for retry')
            count = db.execute('SELECT COUNT(*) FROM llm_calls WHERE run_id=?', (run_id,)).fetchone()[0]
            spent = db.execute('SELECT COALESCE(SUM(reserve_usd),0) FROM llm_calls').fetchone()[0]
            if count >= self.settings.llm_max_calls or (reserve and spent + reserve > self.settings.llm_budget_usd):
                raise ValueError('LLM call or cost budget exceeded')
            db.execute('INSERT INTO llm_calls VALUES (?,?,?,?,?,?)', (run_id, call_key, role, 'pending', reserve, json.dumps(metadata)))
            self.store._trace(db, run_id, sim_ts, 'llm_call', metadata, 'supervisor' if role == 'route' else
                              {'analysis': 'classify', 'recommendations': 'match', 'draft': 'link', 'policy_decision': 'policy', 'regional_analyst':'regional_analyst', 'regional_reviewer':'regional_reviewer', 'regional_worker':'regional_analyst'}[role])
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
                        text_format=schema, max_output_tokens=self.settings.llm_max_output_tokens, store=False)
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
